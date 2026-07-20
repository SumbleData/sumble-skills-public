#!/usr/bin/env python3
"""Production lead scorer for the Sumble people-scoring app.

Calibrate weights interactively in the web app (tune sliders, click Save →
writes people-scoring-weights.json). Then run this script to score an
ENTIRE enriched CRM/leads file with those calibrated weights — no browser,
no row-count limit.

This applies the exact same formula as the web app (see
people-scoring-weights.json -> scoring_formula):

    seniority_frac  = job_level_rank / max_job_level_rank
    jf_score        = jf_range[slug].min
                      + (jf_range[slug].max - jf_range[slug].min) * seniority_frac
    skill_score     = min(skill_count, skill_cap) / skill_cap
    <signal>_score  = <signal>_norm        (already 0-1)
    people_score    = Σ (weight_pct/100) * factor_score      # lands in [0, 1]

The input leads CSV must already be ENRICHED — i.e. carry the same columns
as the app's data.csv (job_function_slug, job_level_rank,
max_job_level_rank, skill_count, any 1P *_norm columns, and the account
columns if you calibrated with an account factor). Produce it by running
the skill's Stage 2 enrichment over the full CRM (no 5-company restriction),
NOT just the calibration sample.

Zero-dependency: stdlib only.

Usage:
    python score_leads.py \
        --leads leads_enriched.csv \
        --weights people-scoring-weights.json \
        --out scored_leads.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from typing import Any


def _num(v: Any, default: float = 0.0) -> float:
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def load_spec(path: str) -> dict[str, Any]:
    with open(path) as f:
        spec = json.load(f)
    weights = {w["key"]: w for w in spec.get("weights", [])}
    return {
        "weights": weights,
        "jf_ranges": spec.get("job_function_ranges", {}) or {},
        "default_jf_range": spec.get("default_jf_range", {}) or {"min": 0.5, "max": 0.85},
        "skill_cap": spec.get("skill_cap", 5) or 5,
        "seniority": spec.get("seniority", {}) or {},
        "one_p_signals": spec.get("one_p_signals", []) or [],
        "id_column": spec.get("id_column", "person_id"),
        "score_label": spec.get("score_label", "people_score"),
    }


def score_row(row: dict[str, Any], spec: dict[str, Any]) -> dict[str, float]:
    weights = spec["weights"]
    rank_col = spec["seniority"].get("rank_column", "job_level_rank")
    max_col = spec["seniority"].get("max_rank_column", "max_job_level_rank")

    rank = _num(row.get(rank_col), 0.0)
    max_rank = _num(row.get(max_col), 0.0)
    sen_frac = (rank / max_rank) if max_rank > 0 else 0.0

    jf_slug = (row.get("job_function_slug") or "").strip()
    jfr = spec["jf_ranges"].get(jf_slug, spec["default_jf_range"])
    jf_lo, jf_hi = _num(jfr.get("min")), _num(jfr.get("max"))
    jf_score = jf_lo + (jf_hi - jf_lo) * sen_frac

    skill_cap = spec["skill_cap"] or 5
    skill_score = min(_num(row.get("skill_count"), 0.0), skill_cap) / skill_cap

    factor_scores: dict[str, float] = {
        "jf": jf_score,
        "skills": skill_score,
    }
    # 1P signals contribute their pre-normalised <norm_column> value directly.
    for sig in spec["one_p_signals"]:
        key = sig.get("weight_key") or sig.get("key")
        norm_col = sig.get("norm_column")
        if key and norm_col:
            factor_scores[key] = _num(row.get(norm_col), 0.0)

    total = 0.0
    for key, w in weights.items():
        pct = _num(w.get("weight_pct"), 0.0) / 100.0
        total += pct * factor_scores.get(key, 0.0)

    out = {f"{k}_score": round(v, 6) for k, v in factor_scores.items()}
    out["people_score"] = round(total, 6)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Score enriched leads with calibrated weights.")
    ap.add_argument("--leads", required=True, help="Enriched leads CSV (data.csv schema).")
    ap.add_argument("--weights", default="people-scoring-weights.json",
                    help="Calibrated weights file written by the app's Save button.")
    ap.add_argument("--out", default="scored_leads.csv", help="Output CSV path.")
    ap.add_argument("--top", type=int, default=0,
                    help="If >0, only write the top N rows by people_score.")
    args = ap.parse_args()

    spec = load_spec(args.weights)

    with open(args.leads, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("No rows in leads file.", file=sys.stderr)
        return 1

    scored = []
    for r in rows:
        s = score_row(r, spec)
        scored.append({**r, **s})

    scored.sort(key=lambda r: r["people_score"], reverse=True)
    for rank, r in enumerate(scored, 1):
        r["rank"] = rank
    if args.top > 0:
        scored = scored[: args.top]

    extra_cols = ["rank", "people_score", "jf_score", "skills_score"]
    extra_cols += [f"{(s.get('weight_key') or s.get('key'))}_score"
                   for s in spec["one_p_signals"]]
    base_cols = list(rows[0].keys())
    fieldnames = base_cols + [c for c in extra_cols if c not in base_cols]

    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(scored)

    print(f"scored {len(rows)} leads -> {args.out} (sorted by people_score desc)")
    if scored:
        top = scored[0]
        label = spec["id_column"]
        print(f"top: {top.get(label, '?')} score={top['people_score']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
