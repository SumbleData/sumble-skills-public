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
  "techs":    [{"slug": "clay", "label": "Clay", "tier": "key"},
               {"slug": "cloud-data-warehouse", "label": "Cloud Data Warehouse", "tier": "key", "kind": "category"}],
  "projects": [{"slug": "generative-ai", "label": "Generative AI"}],
  "universe_filters": {
    "preselect": "auto",
    "min_employees": 50,
    "hq_country_whitelist": [],
    "hard_exclude_tags": ["org_type_k12_school", "org_type_university", "org_type_hospital", "org_type_government"],
    "exclude_professional_services_industry": true,
    "exclude_industries": ["Defense & Space", "Mining & Metals"]
  },
  "section_plan": {
    "sections": [
      {"key": "size", "label": "Size", "default_pct": 50},
      {"key": "growth_momentum", "label": "Growth & momentum", "default_pct": 30},
      {"key": "concentration", "label": "Concentration", "default_pct": 20}
    ],
    "category_section": {"icp_persona_growth": "growth_momentum"},
    "category_meta": {"icp_persona_count": {"default_pct": 50}}
  },
  "first_party_categories": [
    {"key": "product_usage", "label": "Product / PLG usage", "section": "growth_momentum", "default_pct": 20}
  ],
  "first_party_signals": [
    {"key": "active_users", "column": "active_users", "category": "product_usage",
     "transform": "log", "default_within": 100, "p99": 1.0,
     "source": {"kind": "first_party", "synced_pointer": "hubspot/contact.last_30d_active_users"}}
  ],
  "data_sources": {"crm_list": {"source": "...", "size": 1200}, "gold_list": {"source": "closed_won", "size": 48}}
}
```

`section_plan` is OPTIONAL — omit it to take the default three-segment taxonomy
verbatim. When present it overrides segment labels/weights (`sections`), the
category→segment mapping (`category_section`), and per-category label/weight
(`category_meta`). To REPEAT a Sumble signal in a second segment, add a
`first_party_categories` entry for the new segment and a `first_party_signals`
entry whose `column` points at the existing data.csv column with
`api_supported:true` + a `source` block.

`universe_filters` bounds the whitespace pool (modes B/C). `min_employees`,
`hq_country_whitelist`, and `hard_exclude_tags` are pushed into the free rank
query; `exclude_industries` (display names) + `exclude_professional_services_industry`
are guaranteed post-fetch drops in `merge_data.py`. **`exclude_industries` is
derived per company** by the agent (gold-set absence + knowledge of the
company), NOT a fixed default — the example values are illustrative only.

## Policy constants

- Persona/tech decay `0.98`; other-tier discontinuity drop `0.6`.
- Default segment blend (overridable via `spec.section_plan`):
  **Size `50` / Growth & momentum `30` / Concentration `20`** (empty segments
  drop out and the rest renormalise to 100).
- Default category→segment placement: Size = persona headcount `45`, tech teams
  `30`, project×tech `15`, project×persona `10`, funding total `12`;
  Concentration = persona concentration `60`, tech-team concentration `40`;
  Growth & momentum = persona YoY growth `100`, funding momentum `30`.
  Within-segment weights renormalise to 100 over whichever categories are
  present (project×* only with projects, funding only with `include_funding`).
- Tag-lift: gold ≥3 positives, universe ≥5 positives; gold=0 + universe≥10% →
  strong penalty; boost/penalty caps 50%. Runs over the six attribute tags AND
  over synthesized `industry__<slug>` tags (each org's `industry`; top ±8 by
  lift). The calibrated multipliers are written to `tag_multipliers` (APPLIED by
  default, not just suggested) and mirrored in `tag_multipliers_defaults`.
- Funding (opt-in via `spec.include_funding`): fetches 4 funding attributes
  (`+4` credits/matched org) and adds two categories (renormalised) —
  "Funding (total raised)" in **Size** at `12%` (`funding_total_raised`, log)
  and "Funding momentum" in **Growth & momentum** at `30%`
  (`funding_last_round_raised` log + `funding_days_since_last_round` with the
  `recency` transform). The `recency` transform scores fewer-days-since-financing
  higher (`1 − log1p(days)/log1p(p99)`, clamped; never-financed = 0). The
  Growth & momentum segment always exists, so funding momentum lands there even
  with no projects. `funding_last_round_type`/`_date` are context columns, not
  scored.

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
