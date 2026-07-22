"""Render the confirmed interview answers into `territory-plan.json`.

`_raw/spec.json` (what the agent collected and the user confirmed) plus
`_raw/reps.csv` (the roster) become the portable plan file the app reads and
that `suggest_moves.py` scores against. Everything downstream reads the plan,
never spec.json — so the plan is the one file to hand to a colleague, edit by
hand, or check into a repo.

Policy constants (balance thresholds, move limits) are written into the plan
from `territory_lib`, so the app and the mover apply exactly the same rules the
pipeline did, and a user who wants different behaviour edits ONE file.

Usage:
  python3 build_plan.py --raw /abs/path/_raw
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path

import territory_lib as tl


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", default=None, help="plan path (default: <raw>/../territory-plan.json)")
    args = ap.parse_args()

    raw = Path(args.raw).expanduser().resolve()
    spec = tl.read_json(raw / "spec.json")
    out_path = Path(args.out).expanduser() if args.out else raw.parent / "territory-plan.json"

    segments = sorted(spec.get("segments") or [], key=lambda s: tl.to_int(s.get("order"), 0))
    if len(segments) < 2:
        sys.exit("[plan] spec.segments needs at least two segments.")
    seg_keys = {str(s.get("key")) for s in segments}

    boundary = dict(spec.get("boundary") or {})
    thresholds = boundary.get("thresholds") or []
    if not thresholds:
        sys.exit(
            "[plan] boundary.thresholds is empty. Run calibrate_split.py, confirm the "
            "line with the user, and write it into spec.json before building the plan."
        )
    for t in thresholds:
        if str(t.get("segment")) not in seg_keys:
            sys.exit(f"[plan] threshold names an unknown segment: {t.get('segment')!r}")

    reps_rows = tl.read_csv(raw / "reps.csv")
    if not reps_rows:
        sys.exit(f"[plan] {raw / 'reps.csv'} is missing or empty — the roster is required.")

    reps = []
    unknown_segment = []
    for r in reps_rows:
        name = str(r.get("name") or "").strip()
        if not name:
            continue
        is_rep = tl.truthy(r.get("is_rep", "1"))
        seg = str(r.get("segment") or "").strip()
        if is_rep and seg not in seg_keys:
            unknown_segment.append(f"{name} ({seg or 'blank'})")
        cap = r.get("capacity")
        reps.append({
            "name": name,
            "email": tl.norm_email(r.get("email")),
            "segment": seg,
            "is_rep": is_rep,
            "capacity": tl.to_int(cap) if str(cap or "").strip() else None,
        })
    if unknown_segment:
        sys.exit(
            "[plan] these reps have no valid segment: " + ", ".join(unknown_segment) +
            f". Valid segments: {', '.join(sorted(seg_keys))}. Fix reps.csv (or set "
            "is_rep=0 for anyone who isn't a seller) and re-run."
        )

    active = [r for r in reps if r["is_rep"]]
    if not active:
        sys.exit("[plan] reps.csv has no rows with is_rep=1.")
    missing_email = [r["name"] for r in active if not r["email"]]

    activity = dict(spec.get("activity") or {})
    company_domain = tl.norm_domain(
        activity.get("company_domain") or (spec.get("company") or {}).get("url")
    )

    plan = {
        "schema_version": tl.SCHEMA_VERSION,
        "generated_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "company": spec.get("company") or {},
        "score_source": spec.get("score_source") or {"kind": "sumble"},
        "segments": [
            {
                "key": str(s.get("key")),
                "label": str(s.get("label") or s.get("key")),
                "order": tl.to_int(s.get("order"), i + 1),
            }
            for i, s in enumerate(segments)
        ],
        "boundary": {
            "metric": str(boundary.get("metric") or "total_employees"),
            "column": boundary.get("column") or None,
            "label": boundary.get("label") or "",
            "thresholds": [
                {"segment": str(t.get("segment")), "min": tl.to_float(t.get("min"))}
                for t in sorted(thresholds, key=lambda t: tl.to_float(t.get("min")), reverse=True)
            ],
        },
        "reps": reps,
        "activity": {
            "window_days": tl.to_int(activity.get("window_days"), 90) or 90,
            "sources": list(activity.get("sources") or []),
            "company_domain": company_domain,
            "freemail_excludes": sorted(tl.FREEMAIL_DOMAINS),
        },
        "balance": {
            "include_categories": list(
                spec.get("balance_categories") or tl.DEFAULT_BALANCE_CATEGORIES
            ),
            "cv_balanced": tl.CV_BALANCED,
            "cv_uneven": tl.CV_UNEVEN,
        },
        "move_policy": {
            "cv_stop": tl.CV_STOP,
            "max_move_frac": tl.MAX_MOVE_FRAC,
            "whitespace_top_n": tl.to_int(
                spec.get("whitespace_top_n"), tl.DEFAULT_WHITESPACE_TOP_N
            ),
        },
        "territory_csv": "territory.csv",
    }
    tl.write_json(out_path, plan)

    print(f"[plan] wrote {out_path}")
    print(
        f"[plan] {len(active)} reps across {len(segments)} segments · boundary: "
        + "; ".join(f"{t['segment']} >= {t['min']:,.0f}" for t in plan["boundary"]["thresholds"])
    )
    if missing_email:
        print(
            "[plan] WARNING: no email for " + ", ".join(missing_email) +
            " — activity cannot be matched for them, so every account they own will "
            "look 'not worked'."
        )


if __name__ == "__main__":
    main()
