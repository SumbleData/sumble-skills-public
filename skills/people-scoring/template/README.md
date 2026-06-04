# Sumble People Scoring

People-fit scoring app for Sumble's ICP. Ranks individuals at top accounts
by Job Function, Seniority, and Skill match — plus any first-party (1P)
engagement signals connected when the app was generated — tunable via
real-time sliders.

## Run

```bash
python app.py
# open http://localhost:8002
```

No pip install needed. Stdlib only (`http.server`, `csv`, `json`).

## ICP (Sumble)

- **Job functions**: Sales, Account Executive, SDR, Revenue Operations, Marketing (+ 16 leaf JFs)
- **Skills**: clay, common-room, zoominfo, 6sense, demandbase, builtwith, champify,
  crunchbase, hg-insights, linkedin-sales-insights, linkedin-sales-navigator,
  people-data-labs, pitchbook, theirstack, usergems, wappalyzer, hightouch
- **Seniority floor**: Manager and above

## Scoring

```
seniority_frac  = job_level_rank / max_job_level_rank
jf_score        = jf_range.min + (jf_range.max - jf_range.min) * seniority_frac
seniority_score = seniority_frac
skill_score     = min(skill_count, 5) / 5

total = w_jf * jf_score + w_seniority * seniority_score + w_skills * skill_score
        + Σ (w_signal * signal_norm)   # one term per connected 1P signal
```

Default weights (Sumble-only): JF 38% · Seniority 46% · Skills 16%. When 1P
signals are connected those three are scaled to 75% and the 1P signals share
the remaining 25%. Each 1P signal's `<signal>_norm` column is pre-normalised
0–1 (p99 exponential saturation) at `data.csv` build time.

Adjust via sliders and click **Save weights**. This writes
`people-scoring-weights.json` — a self-describing scoring spec (formula,
tuned weights, per-JF ranges, 1P signal column mappings) that a coding
agent can read to productionize the score. `config.json` is never
modified; the app re-opens with the saved weights.

## Scoring the full CRM (`score_leads.py`)

`data.csv` here is a small **calibration sample** (people at ~5
companies) — just enough to tune the sliders. Once you've saved weights,
score your entire lead/CRM universe with the bundled stdlib scorer:

```bash
python score_leads.py \
  --leads leads_enriched.csv \
  --weights people-scoring-weights.json \
  --out scored_leads.csv
```

`leads_enriched.csv` must carry the same columns as `data.csv`
(`job_function_slug`, `job_level_rank`, `max_job_level_rank`,
`skill_count`, any `*_norm` 1P columns, account columns if used) — i.e.
the full CRM run through the same Sumble enrichment. The script applies
the exact app formula, sorts by `people_score` desc, and writes the
augmented CSV. `--top N` keeps only the best N.

## First-party data

When generated with 1P data, the app also carries:

- **CRM contacts** (`is_crm_contact`) — flagged with a CRM badge; the People
  tab gains a contact filter (All / CRM contacts / Whitespace).
- **Gold contacts** (`is_icp_gold`) — flagged with a Gold badge and used by
  the **Evaluation** tab, which buckets all scored people and reports hit
  rate, cumulative recall and lift over baseline.
- **1P signals** — per-person engagement metrics, each an extra weighted
  scoring factor with its own slider.

Tabs and filters that have no backing data are hidden automatically.

## Security

This app has no authentication. Bind to `127.0.0.1` only — never `0.0.0.0`.
Do not expose via tunneling without adding auth. `data.csv` contains LinkedIn
URLs, titles, locations and any joined first-party data (CRM/closed-won
flags, product and marketing signals) — treat as confidential, internal use
only.
