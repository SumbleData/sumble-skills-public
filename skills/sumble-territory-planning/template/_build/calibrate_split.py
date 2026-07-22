"""Propose a segment boundary (and guess each rep's segment) from the data.

Runs when the user does NOT have a hard-line segment definition. Writes
nothing — it prints a JSON proposal for the agent to render and confirm. The
confirmed answer goes into `_raw/spec.json`, and `build_plan.py` turns that into
`territory-plan.json`.

Two ways to find the boundary, picked automatically:

  SUPERVISED (2 segments, and the reps' segments are already known — from a
  role/team field in the CRM, or the user telling us). Sweep candidate
  thresholds across the size distribution and choose the one that makes the
  FEWEST reps look like they're working out-of-segment accounts. The reps'
  actual behaviour defines the line.

  UNSUPERVISED (segments unknown, or >2 segments). 1-D k-means on log(size) —
  company sizes are log-distributed, so clustering in log space finds the gap
  where the market actually splits rather than being dragged by one huge
  account. Thresholds sit at the geometric midpoint between adjacent cluster
  centres.

Either way the result is snapped to a round, defensible number (500, 1,000,
2,500…): the precision a 40-account sample supports is not "1,043 employees".

Also runs the DENSITY GUARD. When the boundary metric is a job-function
headcount, a function that is too granular reads zero at most small companies —
so the "boundary" would really be sorting on whether Sumble has data, not on
size. If more than 30% of accounts below the proposed line read zero, that is
reported as a warning telling the agent to offer a broader function or total
employee count instead.

Usage:
  python3 calibrate_split.py --raw /abs/path/_raw
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import territory_lib as tl

# k-means: fixed iteration cap and deterministic seeding (evenly spaced
# quantiles of the log-size distribution), so the same data always yields the
# same clusters — no RNG anywhere in this pipeline.
KMEANS_ITERS = 50


def load_accounts(raw: Path, spec: dict) -> tuple[list[dict], str, str]:
    """The account table plus (size column, source label).

    Path A reads the account-scoring run's score.csv; Path B reads the
    sumble_light.csv written by fetch_light.py.
    """
    source = spec.get("score_source") or {}
    if str(source.get("kind") or "") == "custom" and source.get("path"):
        path = Path(str(source["path"])).expanduser()
        if not path.exists():
            sys.exit(f"[calibrate] score.csv not found: {path}")
        rows = tl.read_csv(path)
        label = "account-scoring score.csv"
    else:
        path = raw / "sumble_light.csv"
        if not path.exists():
            sys.exit(
                f"[calibrate] {path} not found — run fetch_light.py first, or point "
                "spec.score_source at an account-scoring score.csv."
            )
        rows = tl.read_csv(path)
        label = "sumble_light.csv"
    if not rows:
        sys.exit(f"[calibrate] no rows in {path}")
    size_col = tl.resolve_size_column(spec, rows[0].keys())
    if size_col not in rows[0]:
        sys.exit(
            f"[calibrate] boundary column '{size_col}' is not in {path.name} "
            f"(columns: {', '.join(sorted(rows[0].keys()))}). Re-run fetch_light.py "
            "with --only-jf, or choose total employee count as the boundary metric."
        )
    return rows, size_col, label


def kmeans_1d(values: list[float], k: int) -> list[float]:
    """Deterministic 1-D k-means. Returns sorted cluster centres."""
    vals = sorted(values)
    if len(vals) <= k:
        return vals
    # Seed at evenly spaced quantiles — stable and spread across the range.
    centres = [tl.percentile(vals, (i + 0.5) / k) for i in range(k)]
    for _ in range(KMEANS_ITERS):
        buckets: list[list[float]] = [[] for _ in range(k)]
        for v in vals:
            best = min(range(k), key=lambda i: abs(v - centres[i]))
            buckets[best].append(v)
        new = [
            (sum(b) / len(b)) if b else centres[i]
            for i, b in enumerate(buckets)
        ]
        if all(abs(a - b) < 1e-9 for a, b in zip(new, centres)):
            break
        centres = new
    return sorted(centres)


def _misfits_at(pairs: list[tuple[float, str]], threshold: float, big_key: str) -> int:
    """How many owned accounts a given line puts in the wrong rep's segment."""
    err = 0
    for size, seg in pairs:
        implied_big = size >= threshold
        actual_big = seg == big_key
        if implied_big != actual_big:
            err += 1
    return err


def supervised_threshold(pairs: list[tuple[float, str]], big_key: str) -> tuple[float, int]:
    """Best split of (size, rep_segment) pairs: the threshold minimising the
    number of accounts whose size-implied segment disagrees with the segment of
    the rep who actually owns them. Ties break to the LOWER threshold (a lower
    line moves fewer accounts up into enterprise, the more disruptive direction).

    Returns (threshold, misfit_count).
    """
    sizes = sorted({p[0] for p in pairs})
    if len(sizes) < 2:
        return (sizes[0] if sizes else 0.0), len(pairs)
    # Candidates: every observed size (the split lands just at/above it).
    best_t, best_err = sizes[0], len(pairs) + 1
    for t in sizes:
        err = _misfits_at(pairs, t, big_key)
        if err < best_err:
            best_t, best_err = t, err
    return best_t, best_err


def snap_supervised(
    raw_threshold: float, pairs: list[tuple[float, str]], big_key: str
) -> tuple[int, int]:
    """Round the boundary to a defensible number WITHOUT making the fit worse.

    Snapping to the nearest round number can move accounts across the line: an
    optimal 4,252 rounded to 5,000 reclassifies every account in between. So
    score each round candidate on the same misfit count the sweep used and take
    the best, breaking ties by closeness to the optimum. The result is still a
    number a sales leader can state in one sentence, but it no longer costs
    accuracy to say it.

    Returns (threshold, misfit_count).
    """
    best = tl.snap_to_human(raw_threshold)
    best_err = _misfits_at(pairs, best, big_key)
    for cand in tl.HUMAN_THRESHOLDS:
        err = _misfits_at(pairs, cand, big_key)
        closer = abs(math.log(max(cand, 1) / max(raw_threshold, 1))) < abs(
            math.log(max(best, 1) / max(raw_threshold, 1))
        )
        if err < best_err or (err == best_err and closer):
            best, best_err = cand, err
    return best, best_err


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", required=True)
    args = ap.parse_args()

    raw = Path(args.raw).expanduser().resolve()
    spec = tl.read_json(raw / "spec.json")
    segments = sorted(spec.get("segments") or [], key=lambda s: tl.to_int(s.get("order"), 0))
    if len(segments) < 2:
        sys.exit("[calibrate] spec.segments needs at least two segments.")

    rows, size_col, source_label = load_accounts(raw, spec)
    ownership = tl.read_csv(raw / "ownership.csv")
    reps = tl.read_csv(raw / "reps.csv")

    # domain -> size, for joining ownership to size
    size_by_domain: dict[str, float] = {}
    for r in rows:
        dom = tl.norm_domain(r.get("url") or r.get("domain") or r.get("input_domain"))
        if dom:
            size_by_domain[dom] = tl.to_float(r.get(size_col))

    sizes = [tl.to_float(r.get(size_col)) for r in rows]
    positive = [s for s in sizes if s > 0]

    rep_segment = {
        str(r.get("name") or ""): str(r.get("segment") or "").strip()
        for r in reps
        if tl.truthy(r.get("is_rep", "1"))
    }
    known_segments = {s for s in rep_segment.values() if s}
    seg_keys = [str(s.get("key")) for s in segments]
    big_key = seg_keys[-1]  # highest order = largest segment

    # --- pick a method -----------------------------------------------------
    owned_pairs: list[tuple[float, str]] = []
    for o in ownership:
        seg = rep_segment.get(str(o.get("owner") or ""), "")
        dom = tl.norm_domain(o.get("domain"))
        if seg and dom in size_by_domain:
            owned_pairs.append((size_by_domain[dom], seg))

    use_supervised = (
        len(segments) == 2
        and len(known_segments & set(seg_keys)) >= 2
        and len(owned_pairs) >= 10
    )

    if use_supervised:
        method = "supervised"
        rawthr, _ = supervised_threshold(owned_pairs, big_key)
        snapped_thr, misfits = snap_supervised(rawthr, owned_pairs, big_key)
        thresholds_raw = [rawthr]
        snapped_override = [snapped_thr]
        method_note = (
            f"swept {len(owned_pairs):,} rep-owned accounts; the chosen line leaves "
            f"{misfits:,} of them ({100.0 * misfits / max(len(owned_pairs), 1):.0f}%) "
            "owned by a rep from the other segment"
        )
    else:
        method = "kmeans"
        logs = [math.log1p(max(s, 0.0)) for s in positive] or [0.0]
        centres = kmeans_1d(logs, len(segments))
        thresholds_raw = [
            math.expm1((centres[i] + centres[i + 1]) / 2.0) for i in range(len(centres) - 1)
        ]
        why = (
            "rep segments are not known yet"
            if len(segments) == 2
            else f"{len(segments)} segments (the sweep only handles a two-way split)"
        )
        method_note = f"1-D k-means on log(size) over {len(positive):,} accounts — {why}"
        snapped_override = None

    # Supervised snapping is misfit-aware (see snap_supervised); unsupervised
    # has no error signal to optimise, so nearest-round-number is the best rule.
    snapped = snapped_override or [tl.snap_to_human(t) for t in thresholds_raw]
    # Highest threshold → largest segment, working down.
    thresholds = [
        {"segment": seg_keys[i + 1], "min": snapped[i]} for i in range(len(snapped))
    ]

    # --- density guard -----------------------------------------------------
    boundary_preview = {"thresholds": thresholds}
    lowest_line = min(snapped) if snapped else 0
    below = [s for s in sizes if s < lowest_line]
    zero_below = sum(1 for s in below if s <= 0)
    zero_frac = (zero_below / len(below)) if below else 0.0
    metric = str((spec.get("boundary") or {}).get("metric") or "total_employees")
    warnings: list[str] = []
    if metric.startswith("jf_people:") and zero_frac > tl.MAX_ZERO_FRACTION_BELOW:
        warnings.append(
            f"{zero_frac:.0%} of accounts below the proposed line read ZERO on "
            f"'{metric.split(':', 1)[1]}'. That metric is too granular to size these "
            "companies — it is mostly measuring whether Sumble has data on them. "
            "Offer a broader parent job function (e.g. Engineer, Sales) or total "
            "employee count instead."
        )
    unmatched = sum(1 for s in sizes if s <= 0)
    if unmatched > 0.2 * len(sizes):
        warnings.append(
            f"{unmatched:,} of {len(sizes):,} accounts ({unmatched / len(sizes):.0%}) "
            "have no value for the boundary metric and will all land in the smallest "
            "segment."
        )

    # --- per-rep segment guess --------------------------------------------
    by_rep: dict[str, list[float]] = {}
    for o in ownership:
        owner = str(o.get("owner") or "")
        dom = tl.norm_domain(o.get("domain"))
        if owner and dom in size_by_domain:
            by_rep.setdefault(owner, []).append(size_by_domain[dom])

    rep_guesses = []
    for owner in sorted(by_rep):
        vals = by_rep[owner]
        med = tl.median(vals)
        if len(vals) < tl.MIN_ACCOUNTS_FOR_SEGMENT_GUESS:
            guess, confidence = "unknown", "too few accounts"
        else:
            guess = tl.segment_for_size(med, boundary_preview, segments)
            confidence = "median account size"
        rep_guesses.append({
            "rep": owner,
            "n_accounts": len(vals),
            "median_size": round(med, 1),
            "guessed_segment": guess,
            "basis": confidence,
            "existing_segment": rep_segment.get(owner, ""),
        })

    proposal = {
        "schema_version": tl.SCHEMA_VERSION,
        "source": source_label,
        "size_column": size_col,
        "boundary_metric": metric,
        "method": method,
        "method_note": method_note,
        "accounts_considered": len(rows),
        "distribution": {
            "min": round(min(sizes), 1) if sizes else 0,
            "p10": round(tl.percentile(sizes, 0.10), 1),
            "p25": round(tl.percentile(sizes, 0.25), 1),
            "median": round(tl.median(sizes), 1),
            "p75": round(tl.percentile(sizes, 0.75), 1),
            "p90": round(tl.percentile(sizes, 0.90), 1),
            "max": round(max(sizes), 1) if sizes else 0,
            "zero_or_missing": unmatched,
        },
        "raw_thresholds": [round(t, 1) for t in thresholds_raw],
        "proposed_thresholds": thresholds,
        "segment_counts": {
            seg["key"]: sum(
                1 for s in sizes if tl.segment_for_size(s, boundary_preview, segments) == seg["key"]
            )
            for seg in segments
        },
        "rep_segment_guesses": rep_guesses,
        "warnings": warnings,
    }
    print(json.dumps(proposal, indent=2))


if __name__ == "__main__":
    main()
