---
name: account-whitespace
description: "Build a Sumble-powered account WHITESPACE app: rank the orgs in Sumble's universe that look like a strong fit for your ICP. You must upload a CRM list to remove CRM accounts from the pool (and candidates whose parent is a CRM account split into a Subsidiaries tab); the rest is net-new whitespace. Emits a config and a portable public-API score_accounts.py for scoring larger lists."
---

# Account Whitespace

You're helping a user build a **whitespace ranker**: a small
zero-dependency Python web server (stdlib `http.server` only — no pip
install, no venv) that ranks Sumble's universe of organizations by ICP
fit and surfaces the highest-fit accounts that are NOT in the user's
CRM. The user can tune signal weights with sliders in real time.

The primary view is **Whitespace**. 

If the user uploads a CRM list (encouraged), matched orgs are removed
from the pool. Candidates whose **parent** is a CRM account are split
into a separate **Subsidiaries** tab — land-and-expand targets, not
pure whitespace. Everything else is net-new. With no CRM upload there
is one tab and every candidate is whitespace.

**Two deliverables, one calibration pass.** This skill produces (1) the
**web app** for tuning weights on the candidate pool, and (2) a portable
`score_accounts.py` — a stdlib-only script that re-implements the tuned
score against Sumble's **public REST API** (`https://api.sumble.com/v6/`,
Bearer auth) so the user can score a much larger account list later,
on their own machine, without this skill, the MCP, or internal access.

**Public-API constraint (this skill is for people outside Sumble).** Both the
skill's own data pull and the portable scorer use ONLY the public REST endpoint
`POST /v6/organizations`. Every Sumble signal is now API-reproducible — including
**tech-team concentration** (`{tech}_team_pct = team_count ÷ teams_count`), which
became reproducible once the endpoint exposed the org-total `teams_count`
attribute. Only first-party signals are `api_supported: false`: the app badges
them and the portable scorer omits them (re-normalising weights across the
API-supported signals). (YoY persona growth, once SQL-only, is now API-supported
via the endpoint's `people_count_growth_1y` metric.)

Follow the stages described in this skill VERY closely. The input
(interview) and output of running this skill should be consistent
between runs — more deterministic than many LLM skills.

## When to use

Trigger on any of:

- `/account-whitespace`
- "find me whitespace accounts"
- "rank net-new accounts I'm not selling to"
- "who in Sumble looks like our ICP but isn't in our CRM?"

## Required tools

- **Sumble MCP** (for the ICP interview only):
  - `SearchTechnologies` — resolve tech terms → slugs
  - `GetMyCompanyProfile` — pre-fill ICP (personas, technologies, projects)
  - `RunSqlQuery` — **ID/slug resolution only** (Stage 2a: job-function display
    Names, project slugs). Not used for candidate/enrichment pulls anymore.
- **Sumble public API key** — `SUMBLE_API_KEY` (from sumble.com/account). The
  candidate pool, CRM exclusion, and customer calibration all come from one REST
  endpoint, `POST https://api.sumble.com/v6/organizations` (match + enrich +
  select, and `filter`-mode ranking). The MCP has no wrapper for it, so
  `_build/fetch_data.py` calls it directly — and the generated
  `score_accounts.py` uses the same endpoint. All Sumble signals are
  API-reproducible (tech-team concentration uses the org-total `teams_count`
  attribute); only first-party signals stay `api_supported:false` — dropped +
  renormalised by the portable scorer.

  **Set the key once** — at the top of Stage 2, have the user run the prompt
  helper (reads the key without echoing, saves to `~/.config/sumble/api_key`,
  chmod 0600):
  ```bash
  ! python <skill_dir>/template/_build/set_api_key.py
  ```
  `fetch_data.py` and `score_accounts.py` find it automatically; the resolver
  also accepts `export SUMBLE_API_KEY=...` or `--env-file path/to/.env`.

If the Sumble MCP isn't available in the session, stop and tell the user how to
install it: https://docs.sumble.com/api/mcp. Docs: https://docs.sumble.com/api.

## Shell-command discipline

This runs unattended AND is shipped to non-technical users, so every Bash call
must be **permission-prompt-free**. Claude Code's permission guard fires on
compound, redirected, `cd`-prefixed, or substitution-bearing commands (e.g.
"compound command contains `cd` with output redirection", "brace with quote").
Each such prompt stalls the run. Follow these rules exactly:

- **One simple command per Bash call.** No `&&` / `;` / `|` chains, no `cd`, no
  output redirection (`>`, `>>`, `2>&1`), no backgrounding (`&`, `nohup`), and no
  command substitution (`$(…)` or backticks).
- **Use absolute paths, never `cd`.** Every `_build/*` script takes its directory
  as an argument, so run e.g.
  `python3 <skill_dir>/template/_build/fetch_data.py --raw <output_root>/_raw`
  from anywhere — no `cd`, no relative `_raw`.
- **Run the pipeline in the foreground.** The scripts stream progress to stdout and
  finish in a few minutes. NEVER background a step (`nohup … &`) and poll it with
  `ps aux | grep …` / `tail` — every poll is a fresh prompt, and the redirection
  trips the guard.
- **No inline Python, no heredocs.** Any multi-line Python, JSON shaping, counting,
  or snapshotting → `Write` a `.py` to `<output_root>/_raw/` and run it as a single
  `python3 <abs>.py`. Never `python3 -c "…{…}…"` (the `{`+`"` trips the prompt).
- **Inspect with tools, not the shell.** `Read` / `Glob` / `Grep` for files, counts,
  and logs — never `cat` / `tail` / `head` / `ls` / `wc` / `grep`.

The only Bash this skill needs is `mkdir -p <abs>`, `cp <abs> <abs>`, and
`python3 <abs>/script.py [args]` (the `_build/*` pipeline + `python app.py`) —
each as one standalone command. Everything else is a tool.

## Output

```
account_whitespace/<company>/
  app.py                              stdlib http.server, runs anywhere with Python 3.10+
  score_sheet.py                      writes data.csv (sorted) + score.csv on Save/startup (copied from template/, unchanged)
  score_accounts.py                   portable stdlib-only public-API scorer (copied from template/, unchanged)
  account-whitespace-weights.json     spec + tuned weights; the ONLY config file the app reads (and writes)
  data.csv                            RAW data — one row per Sumble org_id (all signal columns); immutable, never modified by the app
  score.csv                           SCORED sheet — identity + score + rank + per-signal contribution columns (far right), sorted by rank, zero-contribution signals dropped
  static/                             UI: sliders, table, breakdown panel, download button
  README.md
```

`data.csv` is the **immutable** raw source (persists every signal's raw count) —
the app never rewrites it. `score.csv` is the read-only scored view the app
**regenerates** from `data.csv` + the tuned weights on every Save and at startup
(`score_sheet.build_score_sheet`), sorted by rank. Each signal gets one
contribution column (`norm × effective_weight × 100`, the points it adds to the
score) on the far right, ordered most-impactful-first; signals whose total
contribution across all rows is 0 (e.g. a category/within weight of 0) are
omitted from `score.csv`. The **Download score sheet** button produces the same
sheet from the current (possibly unsaved) sliders.

`score_accounts.py` is copied unchanged and config-driven (reads the
tuned spec, calls the public API per `source.api`, drops
`api_supported:false` signals); use it to score a larger list than the
calibration pool.

**Zero-dependency** (stdlib only — no `requirements.txt`). One config
(`account-whitespace-weights.json`) holds the structural spec AND the
tuned weights; the app reads it at startup and writes it via an explicit
**Save** button (no auto-save; Cmd/Ctrl+S also saves). Save persists BOTH
the weights AND `data.csv` (adds/updates `score` + `rank` columns, one
score per `org_id` from the client's displayed values, full data
preserved). One data file (`data.csv`) — the app reads it directly; no
separate `universe.csv` / `config.json` files. Do NOT emit a `branding`
block — let the template's CSS defaults (slate + green) apply.

### `data.csv` column schema

One row per Sumble `org_id`. Columns:
- **Identity:** `org_id` (PK), `slug`, `name`, `url` (bare domain),
  `headquarters_country`, `industry`, `employee_count_int` (the org's **exact**
  headcount from `attributes.employee_count`, now an integer; legacy band
  strings map to a midpoint), `jobs_count` + `teams_count` (org totals;
  `teams_count` is the tech-concentration denominator).
- **Penalty flags (0/1):** `is_it_services`
  (`array_contains(tags, 'it_services')`), `is_professional_services`
  (`industry = 'Professional Services'`).
- **Org-attribute tags + flags:** `tags` (pipe-delimited Sumble tag
  list, e.g. `b2b|digital_native|is_ai_native`) + 0/1 convenience
  flags `is_b2b`, `is_b2c`, `is_digital_native`, `is_ai_native`. Drive
  the toolbar attribute chips AND the tag-multiplier widget. `b2b` and
  `b2c` are independent tags, not mutually exclusive — hybrid orgs
  (e.g. JPMorgan Chase, Google) get both = 1.
- **ICP signal columns** (per Stage 2a-resolved entities): persona count
  `{jf}_people` (`people_count`) + concentration `{jf}_pct` = `100 *
  {jf}_people / employee_count_int` + YoY % growth `{jf}_growth_yoy`
  (`people_count_growth_1y` ÷ 100, ratio); tech team count `{tech}_teams`
  (`team_count`) + team concentration `{tech}_team_pct` = `100 * {tech}_teams /
  teams_count` (org-total team count; api_supported:true).
- **Buying-window columns** (always present): two per key
  project, `{project}_x_relevant_tech_jobposts` and
  `{project}_x_relevant_persona_jobposts` (Template C5).
- **Whitespace-only:** `list_type` (`whitespace` | `crm_subsidiary` —
  drives the tabs; always `whitespace` with no CRM) and
  `crm_parent_name` (matched parent's name for subsidiary rows, else
  blank).
- **`is_icp_gold` (0/1, optional)** — present only when a customer
  list was uploaded (Q4). Marks calibration-sample rows whose org
  also appears in the customer list. Always 0 for the live whitespace
  pool (customers are excluded); gold rows come in via a small
  calibration sample appended for Stage 4 then dropped from the live
  `data.csv` shown in the app.
- **`crm_account_id`** is null in whitespace (CRM accounts are
  excluded, not scored).

No 1P columns — whitespace has no first-party engagement data.

### Default weights + calibration

Encoded as policy constants in `template/_build/build_weights.py` and
`template/_build/merge_data.py` — same `spec.json` + same endpoint
responses → same weights. The agent does NOT pick decay constants,
threshold rules, or default percentages per run. See
`template/_build/README.md` for the constants.

### Scoring methodology

Every signal in `account-whitespace-weights.json` must carry these
fields so the config is self-contained:

- **`transform`** — `log` (count-style, `x = ln(1 + max(raw, 0))`) or
  `linear` (growth/delta, `x = raw`).
- **`p99`** — 99th percentile of the transformed value across the
  calibration sample (positives only). Persisted so
  `score_accounts.py` can normalise one account at a time without a
  universe to fit on.
- **`api_supported` (bool)** — `true` for `sumble_api` and for
  `sumble_derived` only if all inputs are API-derived; `false` for
  `sumble_sql` (e.g. YoY persona growth — no public endpoint exposes
  historical headcount snapshots). When `false`, add a short
  `api_unsupported_reason`. False signals stay in the app (badged) but
  are dropped + weight-renormalised by `score_accounts.py`.
- **`source` block** (`{why, kind, api?, derivation?, run_sql?,
  synced_pointer?, notes?}`) with `kind ∈ sumble_api | sumble_derived
  | sumble_sql | first_party`. Include only the sub-keys that apply.
- **`sumble_link` (optional)** — `{path, filters}` for the
  Sumble-data signals. `filters.hiring_period` MUST match the
  signal's SQL window (omit for snapshot/all-time signals; `["3mo"]`
  for the 3-month intent signals). **`filters` must include every
  cross-filter the SQL `COUNT` applied** — an intent signal
  `<project>_x_relevant_tech_jobposts` whose SQL intersects `project
  AND technology IN (...)` MUST set BOTH `project: [<slug>]` AND
  `technology: [<full relevant set, same slugs as the SQL>]` (and
  likewise `job_function: [<display names>]` for
  `_x_relevant_persona_jobposts`). A link that filters by project
  alone deep-links to "all job posts mentioning this project", not
  the intersection the score counted.

**Normalisation — p99 exponential saturation.** `x =
ln(1 + max(raw, 0))` (`log`) or `x = raw` (`linear`); `norm =
clamp((1 - exp(-x / p99)) / (1 - exp(-1)), 0, 1)`. An org at p99
scores exactly 1.0.

**Final score** = `Σ (norm × section% × category% × within%)` then
`× Π(1 − penalty_pct)` (penalties stack multiplicatively, always in
[0, 1]). Weights must sum to 100 at each level; if a category's data
is unavailable, drop it and re-normalise the rest proportionally.

---

## Pipeline

Execute these stages in order. Surface progress between stages.

### Stage 1 — Interview

Deterministic interview. Follow VERY closely — same input → same
output across runs.

1. **Company name + URL + output folder.**
   Prompt the user. Default folder: `./tmp/account_whitespace/<company>/`.
   Pre-fill `company_name` from `GetMyCompanyProfile.company_summary.company_name`
   when possible.

2. **No objective question.** The score always blends fit/size with buying-window
   intent (75/25) — don't ask the user to choose, and don't write any objective
   field to `spec.json`. Still collect the question-3 buying-window combinations.

3. **Confirm the ICP.**
   Call `GetMyCompanyProfile` for the user's company URL. Propose the
   top personas, technologies, and projects
   based on the profile. Show **both** `key` and `other` tiers.

   If the lookup fails, use an LLM to propose the most relevant
   personas, technologies, and projects, then snap to Sumble slugs via
   `SearchTechnologies` and `RunSqlQuery` against `job_functions` /
   `projects`.

   **How to present this — ONE question, not three.** Render the
   proposed ICP as a single, compact summary block (markdown, no
   multi-selects, no checkboxes), then ask one yes/no/edit question.
   Do NOT ask separate per-category questions for personas, tech, and
   projects.

   Example:
   ```
   Proposed ICP for <company>:
     • Personas: Sales, RevOps, Marketing
     • Technologies: clay, common-room, hg-insights, zoominfo

   Is this ICP OK? Reply "yes" to accept, or describe what to change
   in free-form text (e.g. "drop marketing, add SDR, swap zoominfo for apollo").
   ```

   Also ask about the
   buying-window combinations:

     Do these project × technology and project × job-function
     combinations suggest a buying window for your product?

     Project × technology (modern + legacy competitors + complementary,
     key + other tiers):
     `data-infrastructure-migration` AND (`teradata` OR `hadoop` OR `cloudera` OR `aws-redshift` OR `snowflake` OR `databricks` OR ...)
     `generative-ai`                  AND (`teradata` OR `hadoop` OR `cloudera` OR `aws-redshift` OR `snowflake` OR `databricks` OR ...)

     Project × job function (key + other tiers):
     `data-infrastructure-migration`  AND (`data engineer` OR `software engineer`)
     `generative-ai`                  AND (`data engineer` OR `software engineer`)

   **Eligibility rules** — be deliberate about which
   `GetMyCompanyProfile` items qualify:
   - **Projects**: ONLY `tier: key`.
   - **Technologies**: ALL relevant categories (`modern_competitors`,
     `legacy_competitors`, AND `complementary`) across BOTH `tier: key`
     AND `tier: other`.
   - **Job functions**: BOTH `tier: key` AND `tier: other`.

   If the user responds with edits, apply them, re-resolve any new
   names to Sumble slugs, and show the updated summary back with the
   same yes/edit prompt. Loop until the user accepts.

   If no project genuinely signals intent for this company, skip the
   buying-window sub-step entirely.

4. **CRM list + customer list (two separate uploads).**

   - **CRM list (universe)** — ALL accounts in their CRM (prospects +
     opps + customers). Used for **exclusion** from the whitespace
     pool (you're already working these), with parent matches split
     into the Subsidiaries tab. *Optional but encouraged.*
   - **Customer list (closed-won subset)** — paying / closed-won
     customers only. Used for **calibration**: tag-lift heuristic for
     default multipliers + light tuning of weights & multipliers (see
     **Step 4** in "Setting the first-pass default weights" above).
     *Strongly encouraged* — without it multipliers fall back to
     neutral and Step 4 calibration is skipped.

   Treat the two as independent: a user may have one, the other,
   both, or neither. If they have only a full CRM list, ask whether
   any column flags closed-won (e.g. SF `IsCustomer__c`, HubSpot
   `lifecyclestage='customer'`) and derive the customer subset from
   it; otherwise calibration is skipped.

   **Source-confirmation flow (same for both lists):**

   1. *Surface MCPs before asking for a CSV.* If you see Salesforce
      (`salesforce`, `sf_`), HubSpot (`hubspot`), warehouse
      (`snowflake`, `bigquery`, `databricks`, `postgres`,
      `execute_sql`), or Sheets/Drive MCPs, list them as options.
      Fallback: CSV path.
   2. *List tables*, then hypothesise the source table:
      - CRM list: SF `Account` (no customer filter), HubSpot
        `companies`, warehouse `dim_accounts`/`crm_accounts`.
      - Customer list: SF `Account WHERE IsCustomer__c=true` or
        closed-won `Opportunity.AccountId`; HubSpot
        `companies WHERE lifecyclestage='customer'`; warehouse
        `customers`/`dim_accounts WHERE is_customer=true`.
   3. Confirm the hypothesis in one prompt; sample-read `LIMIT 10` to
      verify join keys (name, URL/domain) before pulling.

   If the user declines the CRM list, skip Stage 2b's exclusion
   matching. If they decline the customer list, skip the Step 4
   calibration (multipliers default to neutral; the only penalty
   columns are `is_it_services`/`is_professional_services` from Q5
   when explicitly chosen).

4.5 **Import existing `/account-scoring` config? (optional, one
   prompt).** Ask: "Do you have an `account-scoring-weights.json`
   from a previous `/account-scoring` run for this company?"
   If yes, point to its path; we'll lift sections/categories/signals,
   `multipliers[]`, `tag_multipliers.active`, and per-signal `p99` from
   it, then drop the 1P categories (`product_usage`,
   `marketing_engagement`, `third_party_intent`) and re-normalise the
   Intent section. Skip the heuristic + Step 4 calibration in this
   case — the imported weights are already tuned. If no, fall back to
   the defaults section above.

5. **Universe filters.**
   - HQ country whitelist (default: none → global)
   - Headcount (default: >50)
   - **Org-attribute handling — TWO explicit asks, in order.** All
     attributes flow through `tag_multipliers` (no `multipliers[]`
     routing). Present the table once, then ask both questions back-to-back.

     | Attribute (tag slug) | Source | Default | Hard-exclude OK? |
     |---|---|---|---|
     | `org_type_k12_school` | tag | **HARD EXCLUDE** | yes — typical |
     | `org_type_university` | tag | **HARD EXCLUDE** | yes — typical |
     | `org_type_hospital` | tag | **HARD EXCLUDE** | yes — typical |
     | `org_type_government` | tag | **HARD EXCLUDE** | yes — typical |
     | `it_services` | tag | calibrate | yes — common |
     | `professional_services` | synthetic — appended to `tags` when industry='Professional Services' (see C1) | calibrate | yes — common |
     | `b2b` | tag | calibrate | **discouraged** — calibrate instead |
     | `b2c` | tag | calibrate | **discouraged** — calibrate instead |
     | `digital_native` | tag | calibrate | rarely |
     | `is_ai_native` | tag | calibrate | rarely |

     **Ask 1 — HARD EXCLUDE which attributes?** The 4 `org_type_*` tags
     (school / university / hospital / government) default to HARD
     EXCLUDE — B2B sellers almost always skip these; user can opt any
     back in. Typical extras to add: `it_services`, `professional_services`
     (partner-shaped orgs that otherwise pile to the top of a
     competitor-tech ranking). **Steer users away from `b2b` / `b2c`**
     — independent tags and many interesting accounts are hybrid
     (JPMorgan, Google = both); calibrate instead.

     **Ask 2 — CALIBRATE which remaining attributes?** For attributes
     NOT hard-excluded, default to auto-calibration via Step 4(a) tag
     lift against the customer list. User can override any to NEUTRAL,
     or set an explicit PENALTY/BOOST pct. No customer list → all
     NEUTRAL unless the user sets explicit pcts.

     Mechanics: HARD EXCLUDE adds the tag (or `professional_services`
     industry) to `spec.universe_filters.hard_exclude_tags` /
     `exclude_professional_services_industry`; `merge_data.py` drops the
     row from the pool. PENALTY/BOOST emits a `tag_multipliers_defaults`
     entry `{tag, pct, direction}` (see Stage 3). NEUTRAL = omit. Two
     `AskUserQuestion` calls total, NOT six.

6. **Candidate pool size.**

   How many whitespace candidates to rank? **1000 recommended** — a
   fast-iteration pass to eyeball output and tweak ICP inputs before
   committing. Set it in `spec.pool_size` (and `--pool`).

   The endpoint returns up to 200 orgs per `filter` page, so the pool is
   fetched as `ceil(pool / 200)` paginated calls. Credit cost ≈
   `(1 + paid-attributes + Σ entity-metrics)` per returned org —
   communicate it upfront.

---

### Stage 2 — Fetch data from the unified endpoint

No SQL. The candidate pool, CRM exclusion, and customer calibration all come
from one REST call, `POST https://api.sumble.com/v6/organizations` (match +
enrich + select, plus `filter`-mode universe ranking). Confirm `SUMBLE_API_KEY`
is set first.

#### Stage 2a — Resolve ICP slugs/names (the only "ID resolution" step)

- **Technologies** → `SearchTechnologies` per term → slug.
- **Job functions** → the endpoint's `job_function` term is the **display Name**
  (e.g. `Sales`, `Data Engineer`). From `GetMyCompanyProfile`, or one
  `RunSqlQuery` on `job_functions` (name/slug lookup).
- **Projects** → slug, from the profile or one
  `RunSqlQuery` on `projects`.
- **Org-type tag slugs** for the hard filter (Q5) → into
  `spec.universe_filters.hard_exclude_tags`.

Write **`_raw/spec.json`** (schema: `template/_build/README.md`): personas
`{slug,name,tier,label}` (`name` is the endpoint term), techs `{slug,…}`,
projects `{slug,…}`, `universe_filters`, `pool_size`. Show the resolved set
back to the user before fetching.

#### Stage 2b — Write the CRM + customer lists (optional)

- **CRM list** (exclusion + subsidiary parents) → `_raw/crm.csv` (`name,domain`).
  Skip if the user declined a CRM upload in Q4.
- **Customer list** (closed-won, for calibration) → `_raw/customers.csv`
  (`name,domain`). Skip if none → Step 4 calibration is skipped.

There is **no separate `MatchOrganizations` step** — the endpoint resolves both
lists (and the candidate pool) as part of the same call.

#### Stage 2c — Fetch + merge

Run each as ONE command with absolute paths — no `cd`, no chaining, no
backgrounding (see Shell-command discipline). `fetch_data.py` streams batch
progress to stdout; run it in the foreground and wait — do NOT `nohup … &` it and
poll with `ps`/`tail`.

```bash
python3 <skill_dir>/template/_build/fetch_data.py --raw <output_root>/_raw --pool 1000
python3 <skill_dir>/template/_build/merge_data.py --raw <output_root>/_raw
```

`fetch_data.py` ranks the candidate pool (`filter` mode, paginated by
`order_by_column`), resolves `crm.csv` → `crm_matches.json` (id-only, for
exclusion), and enriches `customers.csv` → `customer_responses/`. `merge_data.py`
→ `data.csv` (candidates only; CRM-matched `org_id`s excluded; a candidate whose
`parent_id` is a CRM match → `list_type=crm_subsidiary`; universe hard-filters
applied) + `_raw/_customer_calibration.csv` + `_raw/_calibration_audit.json`.
Same `spec.json` + same responses → byte-identical output.

**Credit cost** ≈ `(1 + paid-attributes + Σ entity-metrics)` per returned org
(~16 for a typical ICP). Surface the estimate before fetching a 1000-org pool.

> If the key isn't set yet, run `! python <skill_dir>/template/_build/set_api_key.py`
> first (prompts + saves it), or run the two `python` commands themselves via
> `! python …` so they execute in the user's terminal.

---

### Stage 3 — Generate the app

```bash
mkdir -p <output_root>/static
cp <skill_dir>/template/app.py             <output_root>/app.py
cp <skill_dir>/template/score_sheet.py     <output_root>/score_sheet.py
cp <skill_dir>/template/score_accounts.py  <output_root>/score_accounts.py
cp <skill_dir>/template/README.md          <output_root>/README.md
cp <skill_dir>/template/static/*           <output_root>/static/
python <skill_dir>/template/_build/build_weights.py --raw <output_root>/_raw
```

→ `<output_root>/account-whitespace-weights.json`. The Subsidiaries
tab auto-appears when `data.csv` has `crm_subsidiary` rows.

Write `<output_root>/.gitignore` via the `Write` tool:
```
__pycache__/
*.csv
```

---

### Stage 4 — Run instructions

Print this to the user. Don't try to run the server inside Claude
Code — let the user start it in a terminal where it stays up.

```bash
cd ./tmp/account_whitespace/<company>
python app.py
# open http://localhost:8001 in your browser
```

Stdlib-only, runs on any Python 3.10+. Override the port via
`python app.py 9001` or `PORT=9001 python app.py`.

Click **Save** (or Cmd/Ctrl+S) to write `account-whitespace-weights.json`
AND `data.csv` (with the current `score` + `rank`) — there is no
auto-save, so nothing is written until you Save. **To score a larger
candidate list later**, run the portable scorer against the public API:

```bash
cd ./tmp/account_whitespace/<company>
export SUMBLE_API_KEY=...        # from sumble.com/account
python score_accounts.py --accounts more_candidates.csv --out scored_accounts.csv
# more_candidates.csv has columns: name,domain
```

Stdlib-only, no MCP or internal access. Reads the current weights from
`account-whitespace-weights.json` and skips any `api_supported:false`
signal (printing which). Its ranking is the API-reproducible model —
close to, but not byte-identical to, the app's full model (which
includes the SQL-only signals, flagged).
