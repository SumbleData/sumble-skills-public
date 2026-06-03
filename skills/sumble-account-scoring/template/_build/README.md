# `_build/` — deterministic pipeline scripts (account-scoring)

No SQL. Every Sumble column comes from the unified endpoint
`POST https://api.sumble.com/v6/organizations` (match + enrich + select in one
call). Same `spec.json` + same endpoint responses → byte-identical output.
Policy constants are baked into the scripts, not chosen per run.

## Files

- **`sumble_v6.py`** — shared helpers: the entity plan (which `data.csv` column
  maps to which endpoint entity/metric), `build_select`, response indexing, and
  the employee-band→int and 3-month-`since` helpers. Imported by the other three
  scripts so the fetched payload, the merged columns, and the weights' `source`
  blocks can't drift.
- **`fetch_data.py`** — Stage 2 data pull. `list` mode resolves+enriches the CRM
  calibration sample (`_raw/sample.csv`); `filter` mode ranks Sumble's universe
  (Branch B, no CRM). Writes `_raw/responses/resp_*.json` + `_raw/fetch_index.json`.
  Needs a Sumble API key (run `python set_api_key.py` once, or
  `export SUMBLE_API_KEY=...`, or `--env-file`).
- **`set_api_key.py`** — interactive prompt that saves the key to
  `~/.config/sumble/api_key` (0600); `fetch_data.py` / `score_accounts.py`
  read it automatically.
- **`merge_data.py`** — parse the responses → `data.csv` + `_raw/_calibration_audit.json`.
- **`build_weights.py`** — `spec.json` + audit → `account-scoring-weights.json`.

## Pipeline order

1. **Resolve ICP** — agent resolves personas→`{slug,name,tier,label}` (the
   endpoint's `job_function` term is the **display Name**), techs→`{slug,…}`,
   projects→`{slug,…}`. Write `_raw/spec.json`.
2. **Sample** — agent writes `_raw/sample.csv` (`crm_account_id,name,domain[,is_gold]`)
   from the CRM calibration sample (+ gold subset).
3. **Fetch** — `python fetch_data.py --raw _raw` (list mode). One batched
   `POST /v6/organizations` per ≤1000 orgs; the endpoint matches AND enriches.
4. **Merge** — `python merge_data.py --raw _raw` → `data.csv` (+ tag-lift audit).
5. **Config** — `python build_weights.py --raw _raw` → `account-scoring-weights.json`.

## `spec.json` schema

```json
{
  "schema_version": 1,
  "company": {"name": "Acme", "url": "acme.com", "folder_slug": "acme"},
  "include_funding": true,
  "personas": [{"slug": "sales", "name": "Sales", "label": "Sales", "tier": "key"}],
  "techs":    [{"slug": "clay", "label": "Clay", "tier": "key"}],
  "projects": [{"slug": "generative-ai", "label": "Generative AI"}],
  "first_party_categories": [
    {"key": "product_usage", "label": "Product / PLG usage", "section": "intent", "default_pct": 20}
  ],
  "first_party_signals": [
    {"key": "active_users", "column": "active_users", "category": "product_usage",
     "transform": "log", "default_within": 100, "p99": 1.0,
     "source": {"kind": "first_party", "synced_pointer": "hubspot/contact.last_30d_active_users"}}
  ],
  "data_sources": {"crm_list": {"source": "...", "size": 1200}, "gold_list": {"source": "closed_won", "size": 48}}
}
```

## Policy constants

- Persona/tech decay `0.98`; other-tier discontinuity drop `0.6`.
- ACV/Intent section split `60/40` (Intent categories present when the spec has projects).
- Sumble Intent categories: project × tech `60`, project × persona `40`
  (re-normalised when 1P categories are appended).
- Tag-lift: gold ≥3 positives, universe ≥5 positives; gold=0 + universe≥10% →
  strong penalty; boost/penalty caps 50%.
- Funding (opt-in via `spec.include_funding`): fetches 4 funding attributes
  (`+4` credits/matched org) and adds two categories (renormalised) —
  "Funding (size)" in ACV at `12%` (`funding_total_raised`, log) and "Funding
  momentum" in Intent at `30%` (`funding_last_round_raised` log +
  `funding_days_since_last_round` with the `recency` transform). The `recency`
  transform scores fewer-days-since-financing higher
  (`1 − log1p(days)/log1p(p99)`, clamped; never-financed = 0). With no projects
  (so no Intent section) all three sit in the ACV "Funding" category.
  `funding_last_round_type`/`_date` are context columns, not scored.

## API-supported vs not

- `api_supported:true` — reproducible from `POST /v6/organizations`: persona
  counts (`people_count`), persona YoY growth (`people_count_growth_1y`), tech
  team counts (`team_count`), 3-month intent (`advanced_query` + `since`),
  persona concentration (`people_count ÷ employee_count`, exact integer), and
  **tech concentration** (`{tech}_team_pct` = `team_count ÷ teams_count`, the
  org-total team count attribute).
- `api_supported:false` — **first-party signals only** (joined by account, not
  from Sumble). The portable `score_accounts.py` drops these and re-normalises
  the remaining weights.
