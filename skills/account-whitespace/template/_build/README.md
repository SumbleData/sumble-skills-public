# `_build/` — deterministic pipeline scripts (account-whitespace)

No SQL. Every Sumble column comes from the unified endpoint
`POST https://api.sumble.com/v6/organizations` (match + enrich + select, and —
in `filter` mode — rank the universe). Same `spec.json` + same responses →
byte-identical output.

## Files

- **`sumble_v6.py`** — shared helpers: entity plan (column → endpoint entity),
  `build_select`, `build_data_row`, employee-band→int, 3-month `since`.
- **`fetch_data.py`** — Stage 2 pull. Ranks the candidate pool (`filter` mode);
  resolves the CRM list to org ids for exclusion (`crm.csv` → `crm_matches.json`);
  enriches the closed-won customers for calibration (`customers.csv` →
  `customer_responses/`). Needs a Sumble API key (run `python set_api_key.py`
  once, or `export SUMBLE_API_KEY=...`, or `--env-file`).
- **`set_api_key.py`** — interactive prompt that saves the key to
  `~/.config/sumble/api_key` (0600); `fetch_data.py` / `score_accounts.py`
  read it automatically.
- **`merge_data.py`** — responses → `data.csv` (candidates only, CRM accounts
  excluded, subsidiaries tagged) + `_raw/_customer_calibration.csv` + tag-lift audit.
- **`build_weights.py`** — `spec.json` + audit → `account-whitespace-weights.json`.

## Pipeline order

1. **Resolve ICP** — personas→`{slug,name,tier,label}` (endpoint `job_function`
   term = display **Name**), techs→`{slug,…}`, projects→`{slug,…}`,
   `universe_filters`, `pool_size`. Write `_raw/spec.json`.
2. **Lists (optional)** — write `_raw/crm.csv` (`name,domain` — full CRM, for
   exclusion) and/or `_raw/customers.csv` (`name,domain` — closed-won, for
   calibration).
3. **Fetch** — `python fetch_data.py --raw _raw --pool 1000`. Candidate pool via
   one paginated `filter` query; CRM + customers via list mode.
4. **Merge** — `python merge_data.py --raw _raw` → `data.csv`. Candidates whose
   `org_id` is a CRM match are excluded; whose `parent_id` is a CRM match become
   `list_type=crm_subsidiary`; the rest are `whitespace`. The universe
   hard-filters (min employees, HQ whitelist, excluded tags) are applied here.
5. **Config** — `python build_weights.py --raw _raw` → `account-whitespace-weights.json`.

## `spec.json` schema

```json
{
  "schema_version": 1,
  "company": {"name": "Acme", "url": "acme.com", "folder_slug": "acme"},
  "pool_size": 1000,
  "personas": [{"slug": "sales", "name": "Sales", "label": "Sales", "tier": "key"}],
  "techs":    [{"slug": "clay", "label": "Clay", "tier": "key"}],
  "projects": [{"slug": "generative-ai", "label": "Generative AI"}],
  "universe_filters": {
    "min_employees": 200,
    "hq_country_whitelist": [],
    "hard_exclude_tags": ["org_type_k12_school", "org_type_university", "it_services"],
    "exclude_professional_services_industry": false,
    "order_by_column": "employee_count"
  }
}
```

`order_by_column` ranks the candidate filter — `account_score` (if your domain
has Sumble account scores) or `employee_count`/`jobs_count`/`people_count`.

## Policy constants

- Persona/tech decay `0.98`; other-tier discontinuity drop `0.6`.
- ACV/Intent section split `75/25` (Intent categories present when the spec has projects).
- Sumble Intent categories: project × tech `60`, project × persona `40`.
- Tag-lift: gold ≥3 positives, universe ≥5 positives; gold=0 + universe≥10% →
  strong penalty; boost/penalty caps 50%.

## API-supported vs not

Same as account-scoring: persona counts/growth, tech team counts, 3-month intent
(`advanced_query` + `since`), persona concentration (`people_count ÷
employee_count`), and **tech concentration** (`team_count ÷ teams_count`, the
org-total team count attribute) are all `api_supported:true`. Only first-party
signals are `api_supported:false` — dropped + renormalised by `score_accounts.py`.
