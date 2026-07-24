"""Build the scored sheet from data.csv + the weights config (stdlib only).

Reads data.csv (the immutable RAW API-pull file — never modified here) and the
weights config, and writes ONE complete file:
  - score.csv : the single human-facing sheet, sorted by rank. It is a SUPERSET
                of data.csv: `rank` (far left) → EVERY data.csv column (raw
                signals + identity) → `score` → one CONTRIBUTION column per
                signal (points = norm * effective_weight * multiplier * 100, so
                the contributions SUM EXACTLY to `score`) → deep links on the far
                right (`sumble_url` org page + one per signal). Signals whose
                TOTAL contribution across all rows is 0 are dropped (from the
                contribution columns only; their raw column is still present).

So you only ever need score.csv — it has the data, the score, the per-signal
contributions, and the deep links in one place. data.csv is the immutable raw
archive the app re-scores from; it is never rewritten. score.csv is regenerated
on every Save and at startup.

The score mirrors the app's client math exactly: p99 exponential-saturation
normalisation, effective weight = section% * category% * within% (renormalised
over signals/categories/sections that have live weight), summed, then times the
product of column- and tag-multipliers. All signals are included (unlike the
portable score_accounts.py, which drops api_supported:false signals).
"""

from __future__ import annotations

import csv
import glob
import json
import math
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlencode

IDENTITY_PREFERRED = [
    "org_id", "name", "url", "account_category", "employee_count_int",
    "headquarters_country", "industry", "list_type", "crm_parent_name",
]


def _f(v: object) -> float:
    try:
        return float(v or 0)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _sumble_link(base: str, slug: str, spec: dict | None) -> str:
    """Per-org Sumble deep link for a signal's sumble_link spec — mirrors the
    app's buildSumbleLink (filters → advanced-search `as=` JSON)."""
    if not spec or not slug:
        return ""
    path = spec.get("path", "") or ""
    url = f"{base}{slug}{path}"
    groups = [
        {"operator": "OR", "fields": {field: {"include": values, "exclude": []}}}
        for field, values in (spec.get("filters") or {}).items()
        if isinstance(values, list) and values
    ]
    if not groups:
        return url
    params: list[tuple[str, str]] = []
    if "people" in path:
        params += [("sort", "Sumble Lead Score"), ("desc", "1")]
    params.append(("as", json.dumps({"operator": "AND", "children": groups},
                                     separators=(",", ":"))))
    return url + "?" + urlencode(params, quote_via=quote_plus)


def _find_weights(app_dir: Path) -> Path:
    for name in ("account-whitespace-weights.json", "account-scoring-weights.json"):
        if (app_dir / name).exists():
            return app_dir / name
    hits = sorted(glob.glob(str(app_dir / "*-weights.json")))
    if not hits:
        raise FileNotFoundError(f"no *-weights.json in {app_dir}")
    return Path(hits[0])


def _norms(rows: list[dict], signals: dict[str, dict]) -> dict[str, list[float]]:
    """Per-signal normalised value for every row (p99 exponential saturation;
    `recency` is a lower-is-better signal that decays with log(days))."""
    out: dict[str, list[float]] = {}
    scale = 1.0 - math.exp(-1.0)
    for key, spec in signals.items():
        col = spec["column"]
        transform = spec.get("transform", "log")
        raws = [_f(r.get(col)) for r in rows]
        if transform == "recency":
            pos = sorted(v for v in raws if v > 0)
            p99 = max(pos[min(len(pos) - 1, int(0.99 * len(pos)))], 1.0) if pos else 1.0
            denom = math.log1p(max(p99, 1.0))
            out[key] = [
                0.0 if (v <= 0 or denom <= 0)
                else max(0.0, min(1.0 - math.log1p(v) / denom, 1.0))
                for v in raws
            ]
            continue
        is_linear = transform == "linear"
        xs = [v if is_linear else math.log1p(max(v, 0.0)) for v in raws]
        pos = sorted(x for v, x in zip(raws, xs) if v > 0)
        p99 = max(pos[min(len(pos) - 1, int(0.99 * len(pos)))], 1e-9) if pos else 1e-9
        out[key] = [max(0.0, min((1.0 - math.exp(-min(x / p99, 700.0))) / scale, 1.0)) for x in xs]
    return out


def _effective_weights(config: dict) -> dict[str, float]:
    """sec% * cat% * within% per signal, renormalised over live weights. All
    signals included (full app model)."""
    signals = {k: v for k, v in config.get("signals", {}).items() if isinstance(v, dict)}
    categories = config.get("categories", {})
    sections = config.get("sections", {})
    has_secs = bool(sections)

    within_sum: dict[str, float] = {}
    for s in signals.values():
        cat = s.get("category", "_")
        within_sum[cat] = within_sum.get(cat, 0.0) + _f(s.get("default_within"))
    live_cats = {c for c in within_sum if within_sum[c] > 0}
    sec_of = {c: categories.get(c, {}).get("section") for c in categories}

    def cat_pool(cat: str) -> list[str]:
        if not has_secs:
            return list(live_cats)
        return [c for c in live_cats if sec_of.get(c) == sec_of.get(cat)]

    live_secs = {sec_of.get(c) for c in live_cats} if has_secs else set()
    sec_sum = sum(_f(sections[s].get("default_pct")) for s in live_secs if s in sections)

    eff: dict[str, float] = {}
    for k, s in signals.items():
        cat = s.get("category", "_")
        if within_sum.get(cat, 0) <= 0:
            eff[k] = 0.0
            continue
        within_frac = _f(s.get("default_within")) / within_sum[cat]
        pool = cat_pool(cat)
        cat_sum = sum(_f(categories.get(c, {}).get("default_pct")) for c in pool)
        cat_frac = (_f(categories.get(cat, {}).get("default_pct")) / cat_sum) if cat_sum else 0.0
        if has_secs:
            sec = sec_of.get(cat)
            sec_frac = (_f(sections[sec].get("default_pct")) / sec_sum) if (sec in sections and sec_sum) else 0.0
        else:
            sec_frac = 1.0
        eff[k] = sec_frac * cat_frac * within_frac
    return eff


def build_score_sheet(app_dir: Path, weights_path: Path | None = None) -> dict[str, Any]:
    app_dir = Path(app_dir)
    weights_path = weights_path or _find_weights(app_dir)
    config = json.loads(weights_path.read_text())
    data_path = app_dir / config.get("data_csv", "data.csv")
    if not data_path.exists():
        return {"rows": 0}

    with data_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        raw_fields = [c for c in (reader.fieldnames or []) if c not in ("score", "rank")]
        rows = list(reader)

    signals = {k: v for k, v in config.get("signals", {}).items() if isinstance(v, dict)}
    norms = _norms(rows, signals)
    eff = _effective_weights(config)
    mults = config.get("multipliers", []) or []
    tag_mults = config.get("tag_multipliers", []) or []

    # Per-row per-signal contribution (points) + final score. Contributions are
    # scaled by the row's multiplier factor so they SUM EXACTLY to the score.
    contrib: dict[str, list[float]] = {k: [0.0] * len(rows) for k in signals}
    scores: list[float] = []
    for i, r in enumerate(rows):
        per = {k: norms[k][i] * eff.get(k, 0.0) for k in signals}
        base = sum(per.values())
        mult = 1.0
        for m in mults:
            pct = _f(m.get("default_pct")) / 100.0
            if pct > 0 and r.get(m.get("column")):
                mult *= 1 - pct
        row_tags = {t.strip() for t in str(r.get("tags") or "").split("|") if t.strip()}
        for e in tag_mults:
            pct = _f(e.get("pct")) / 100.0
            if e.get("tag") in row_tags and pct > 0:
                mult *= (1 + pct) if e.get("direction") == "boost" else (1 - pct)
        for k in signals:
            contrib[k][i] = round(per[k] * mult * 100.0, 4)
        scores.append(round(base * mult * 100.0, 4))

    order = sorted(range(len(rows)), key=lambda i: -scores[i])
    rank_of = {i: r for r, i in enumerate(order, 1)}

    # NOTE: data.csv is the immutable raw API-pull file — we never rewrite it
    # here. All scoring/ranking lives in score.csv, regenerated on every Save.

    # score.csv: identity + score + rank + nonzero contribution columns (far right).
    totals = {k: sum(contrib[k]) for k in signals}
    live = [k for k in signals if totals[k] > 0]
    live.sort(key=lambda k: -totals[k])  # most impactful first
    labels: dict[str, str] = {}
    used: set[str] = set()
    for k in live:
        lab = signals[k].get("label", k)
        if lab in used:
            lab = f"{lab} [{k}]"
        used.add(lab)
        labels[k] = lab

    # score.csv is the ONE complete post-Save file: it carries EVERY data.csv
    # column (raw signals + identity), nice identity columns first, then the rest
    # in their data.csv order — followed by score, rank, contributions, links. So
    # the user never needs to join score.csv back to data.csv; data.csv is just
    # the immutable raw archive the app re-scores from.
    ident = [c for c in IDENTITY_PREFERRED if c in raw_fields] + [
        c for c in raw_fields if c not in IDENTITY_PREFERRED
    ]
    base_url = config.get("sumble_url_base", "https://sumble.com/orgs/")
    slug_col = config.get("slug_column", "slug")
    # Per-signal deep links for the live signals that carry a sumble_link.
    link_keys = [k for k in live if signals[k].get("sumble_link")]

    # Layout: rank (far left) → all data columns → score → contribution cols →
    # deep links (org page + one per signal) on the far right. Contributions sum
    # to score.
    score_fields = (
        ["rank"] + ident + ["score"]
        + [labels[k] for k in live]
        + ["sumble_url"] + [f"{labels[k]} link" for k in link_keys]
    )
    score_path = app_dir / "score.csv"
    tmp2 = score_path.with_suffix(".csv.tmp")
    with tmp2.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(score_fields)
        for i in order:
            slug = rows[i].get(slug_col, "") or ""
            org_url = rows[i].get("sumble_url") or (f"{base_url}{slug}" if slug else "")
            row = [rank_of[i]] + [rows[i].get(c, "") for c in ident] + [scores[i]]
            row += [contrib[k][i] for k in live]
            row += [org_url]
            # Per-signal links come straight from the API ({column}_link in
            # data.csv), not a hand-built URL.
            row += [rows[i].get(f"{signals[k]['column']}_link", "") for k in link_keys]
            w.writerow(row)
    tmp2.replace(score_path)

    return {
        "rows": len(rows),
        "signals_total": len(signals),
        "signals_kept": len(live),
        "signals_dropped_zero": len(signals) - len(live),
        "score_csv": str(score_path),
    }


if __name__ == "__main__":
    import sys

    d = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    print(build_score_sheet(d))
