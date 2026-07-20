"""Build the scored sheet from data.csv + config.json (stdlib only).

Reads data.csv (the immutable raw pull — never modified here) and the live
config (slider weights in each weight's `current`), and writes ONE complete
file:

  score.csv : the single human-facing sheet, sorted by rank. A SUPERSET of
              data.csv: `rank` (far left) → EVERY data.csv column (identity +
              raw signals, deep links included: `sumble_url`, `linkedin_url`,
              `org_sumble_url`) → `people_score` (0-100) → one CONTRIBUTION
              column per factor (points = factor_score * weight, so the
              contributions SUM EXACTLY to `people_score`), ordered
              most-impactful first; factors with zero total contribution drop
              their contribution column only.

So you only ever need score.csv — data + score + per-factor contributions +
deep links in one place. data.csv is the immutable raw archive the app
re-scores from; it is never rewritten. score.csv is regenerated on every Save
and at startup, and the in-app Download button serves the same sheet.

The score mirrors the app's client math and score_leads.py exactly:
  seniority_frac  = job_level_rank / max_job_level_rank
  jf_score        = jf_range.min + (jf_range.max - jf_range.min) * seniority_frac
  skill_score     = min(skill_count, skill_cap) / skill_cap
  1p factor       = its pre-normalised <norm_column> value
  people_score    = 100 * Σ (weight_pct/100) * factor_score
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

IDENTITY_PREFERRED = [
    "person_id",
    "name",
    "current_title",
    "org_name",
    "job_function_name",
    "job_level",
    "matched_skills",
    "skill_count",
    "location",
]


def _f(v: object, default: float = 0.0) -> float:
    if v in (None, ""):
        return default
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _weight_pct(spec: dict[str, Any]) -> float:
    cur = spec.get("current")
    return _f(cur if cur is not None else spec.get("default"))


def factor_scores(row: dict, config: dict) -> dict[str, float]:
    """Per-row factor scores, weights factored out — same formula as
    score_leads.py / the app's client JS / _build/fit_weights.py."""
    sen = config.get("seniority", {}) or {}
    rank = _f(row.get(sen.get("rank_column", "job_level_rank")))
    max_rank = _f(row.get(sen.get("max_rank_column", "max_job_level_rank")))
    sen_frac = (rank / max_rank) if max_rank > 0 else 0.0

    jfr_all = config.get("job_function_ranges", {}) or {}
    default_rng = config.get("default_jf_range", {}) or {"min": 0.5, "max": 0.85}
    jf_slug = (row.get("job_function_slug") or "").strip()
    rng = jfr_all.get(jf_slug, default_rng)
    jf_score = _f(rng.get("min")) + (_f(rng.get("max")) - _f(rng.get("min"))) * sen_frac

    cap = config.get("skill_cap", 5) or 5
    skill_score = min(_f(row.get("skill_count")), cap) / cap

    out = {"jf": jf_score, "skills": skill_score}
    for sig in config.get("one_p_signals", []) or []:
        key = sig.get("weight_key") or f"1p_{sig.get('key')}"
        out[key] = _f(row.get(sig.get("norm_column") or f"{sig.get('key')}_norm"))
    return out


def build_score_sheet(
    app_dir: Path, config_in: dict[str, Any] | None = None
) -> dict[str, Any]:
    app_dir = Path(app_dir)
    config: dict[str, Any] = (
        config_in
        if config_in is not None
        else json.loads((app_dir / "config.json").read_text())
    )
    data_path = app_dir / config.get("csv", "data.csv")
    if not data_path.exists():
        return {"rows": 0}

    with data_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        raw_fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not rows:
        return {"rows": 0}

    weights = {k: _weight_pct(v) for k, v in (config.get("weights") or {}).items()}
    labels = {
        k: str((config.get("weights") or {}).get(k, {}).get("label", k))
        .replace(" (%)", "")
        .strip()
        for k in weights
    }

    contrib: dict[str, list[float]] = {k: [0.0] * len(rows) for k in weights}
    scores: list[float] = []
    for i, r in enumerate(rows):
        fs = factor_scores(r, config)
        total = 0.0
        for k, w in weights.items():
            pts = (w / 100.0) * fs.get(k, 0.0) * 100.0
            contrib[k][i] = round(pts, 4)
            total += pts
        scores.append(round(total, 4))

    order = sorted(range(len(rows)), key=lambda i: -scores[i])
    rank_of = {i: r for r, i in enumerate(order, 1)}

    totals = {k: sum(contrib[k]) for k in weights}
    live = [k for k in weights if totals[k] > 0]
    live.sort(key=lambda k: -totals[k])  # most impactful first
    used: set[str] = set()
    col_label: dict[str, str] = {}
    for k in live:
        lab = f"{labels[k]} (pts)"
        if lab in used:
            lab = f"{labels[k]} [{k}] (pts)"
        used.add(lab)
        col_label[k] = lab

    ident = [c for c in IDENTITY_PREFERRED if c in raw_fields] + [
        c for c in raw_fields if c not in IDENTITY_PREFERRED
    ]
    score_fields = ["rank"] + ident + ["people_score"] + [col_label[k] for k in live]

    score_path = app_dir / "score.csv"
    tmp = score_path.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(score_fields)
        for i in order:
            row = [rank_of[i]] + [rows[i].get(c, "") for c in ident]
            row += [scores[i]] + [contrib[k][i] for k in live]
            w.writerow(row)
    tmp.replace(score_path)

    return {
        "rows": len(rows),
        "factors_total": len(weights),
        "factors_kept": len(live),
        "score_csv": str(score_path),
    }


if __name__ == "__main__":
    import sys

    d = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    print(build_score_sheet(d))
