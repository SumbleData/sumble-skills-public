---
name: account-scoring
description: "Build an account-scoring web app powered by Sumble data and optional first-party data. Interviews the user about their ICP, pulls data from internal systems and possibly Sumble MCP, and generates a self-contained, zero-dependency Python + HTML/JS app at account_scoring/<company>/ with real-time slider re-weighting and an evaluation mechanism to tune the score. Outputs a config file describing the account scoring method and a Python script that allows the method to be applied across all accounts."
---

# Account Scoring

This skill produces two things:

1. A zero-dependency Python **web app** (stdlib `http.server`) that ranks
   a **calibration sample** of companies and lets the user tune signal
   weights with sliders. Data comes from the Sumble MCP plus optional 1P.
2. A portable config file account-scoring-weights.json that describes everything required to replicate the score in a production system.   

**Why a calibration sample:** It's too slow to you bulk-score a whole CRM using this skill. This skill
calibrates weights on a sample; applying this scoring at scale is a separate skill that
reads account-scoring-weights.json.

Follow the stages closely — input (interview) and output should be
consistent between runs, more deterministic than most skills.

## When to use

Trigger is `/account-scoring`

## Required tools

- **Sumble MCP** (for the ICP interview only):
  - `SearchTechnologies` — resolve tech terms → slugs
  - `GetMyCompanyProfile` — pre-fill ICP (personas, technologies, projects)
  - `RunSqlQuery` — **ID/slug resolution only** (Stage 2a: snap job-function
    display Names and project slugs). NOT used for signal pulls anymore.
- **Sumble public API key** — `SUMBLE_API_KEY` (from sumble.com/account). All
  Stage-2 data now comes from one REST endpoint,
  `POST https://api.sumble.com/v6/organizations` (match + enrich + select in a
  single call). The MCP has no wrapper for it, so the `_build/fetch_data.py`
  script calls it directly.

  **Set the key once** — at the top of Stage 2, have the user run the prompt
  helper (it reads the key without echoing and saves it to
  `~/.config/sumble/api_key`, chmod 0600):
  ```bash
  ! python <skill_dir>/template/_build/set_api_key.py
  ```
  `fetch_data.py` and `score_accounts.py` then find it automatically. The
  resolver also accepts `export SUMBLE_API_KEY=...` or `--env-file path/to/.env`.

If the Sumble MCP isn't available in the session, stop and tell the user
how to install it: https://docs.sumble.com/api/mcp.

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
- **Run the pipeline in the foreground.** The scripts stream progress to stdout
  (the harness shows it live) and finish in a few minutes. NEVER background a step
  (`nohup … &`) and poll it with `ps aux | grep …` / `tail` — every poll is a
  fresh prompt, and the redirection trips the guard.
- **No inline Python, no heredocs.** Any multi-line Python, JSON shaping, counting,
  or snapshotting → `Write` a `.py` to `<output_root>/_raw/` and run it as a single
  `python3 <abs>.py`. Never `python3 -c "…{…}…"` (the `{`+`"` trips the prompt).
- **Inspect with tools, not the shell.** `Read` / `Glob` / `Grep` for files, counts,
  and logs — never `cat` / `tail` / `head` / `ls` / `wc` / `grep`.

The only Bash this skill needs is `mkdir -p <abs>`, `cp <abs> <abs>`, and
`python3 <abs>/script.py [args]` (the `_build/*` pipeline + Stage 4
`python app.py`) — each as one standalone command. Everything else is a tool.

## Output

```
account_scoring/<company>/
  app.py                          stdlib http.server (copied from template/, unchanged — no deps)
  account-scoring-weights.json    weights + scoring formula + data-source
                                   metadata + derived columns + table layout
                                   + per-signal p99 + api_supported; the app
                                   opens from this file, and a separate
                                   scoring skill reproduces the score from it
  score_sheet.py                  writes data.csv (sorted) + score.csv on Save/startup (copied from template/, unchanged)
  data.csv                        RAW calibration sample (all signal columns); immutable, never modified by the app (see column schema below)
  score.csv                       SCORED sheet — identity + score + rank + per-signal contribution columns (far right), sorted by rank, zero-contribution signals dropped
  static/                         UI: sliders, table, per-row breakdown
  README.md
```

`data.csv` is the **immutable** raw source (persists every signal's raw count) —
the app never rewrites it. `score.csv` is the read-only scored view the app
**regenerates** from `data.csv` + the tuned weights on every Save and at startup
(`score_sheet.build_score_sheet`). Each signal gets one contribution column
(`norm × effective_weight × 100`) on the far right, ordered most-impactful-first;
signals with 0 total contribution are omitted. The **Download score sheet** button
produces the same sheet from the current (possibly unsaved) sliders.

**Zero-dependency rule:** `app.py` uses only the stdlib (`csv`, `json`,
`math`, `http.server`) — no `requirements.txt`, no third-party imports,
so any teammate can `python app.py` on the first try.

`account-scoring-weights.json` is the **only** file the app reads — the
structural spec (sections/categories/signals/multipliers) AND the current
weights, in the `default_pct`/`default_within` fields; Save mutates them
in place. It's also the hand-off to the separate scoring skill, so keep
it self-contained (per-signal `source`, `p99`, `api_supported`). Do NOT
emit a `branding` block — template CSS defaults (slate + green) apply.

### `data.csv` column schema

One row per Sumble `org_id`. Column naming convention:
`{signal_slug}_{measure}` (snake_case). The same column names are
referenced from `account-scoring-weights.json` so `app.py` is generic.

**Identity (all rows):**
- `org_id` (int, required) — Sumble organization id (`attributes.id`), primary key
- `slug` (str) — `attributes.slug`
- `name` (str) — `attributes.name`
- `url` (str) — bare website domain (`attributes.url`; no scheme prefix). The default `table_columns` shown in the app are Sumble-only: `name, url, employee_count_int` (+ score). `headquarters_country`, `industry`, and the CRM identity columns are NOT shown — they stay in `data.csv` for the full export. The app dedups rows to one per Sumble `org_id` (duplicate CRM records collapse; gold preferred), so the table shows unique Sumble matches. `sumble_score` is NOT pulled or shown.
- `headquarters_country` (str, ISO-2) — `attributes.headquarters_country`
- `industry` (str) — `attributes.industry`
- `employee_count_int` (int) — the org's **exact** headcount, read from the `attributes.employee_count` attribute, which the endpoint now returns as an exact integer (e.g. `2615`). A legacy band string (`"1,001 - 5,000"`) maps to its midpoint via `sumble_v6.emp_band_to_int`; missing → 0.
- `jobs_count` (int) — org-total job-post count (`attributes.jobs_count`); firmographic.
- `teams_count` (int) — org-total team count (`attributes.teams_count`); the denominator for tech-team concentration (`{tech}_team_pct = 100 * {tech}_teams / teams_count`).

**CRM linkage:**
- `crm_account_id` (str, nullable) — internal CRM / Salesforce id, carried through from `_raw/sample.csv` (Branch A only). Kept in `data.csv` (NOT shown in the app, since duplicated CRM records would surface the same Sumble org multiple times).
- `crm_account_name` / `crm_url` (str, nullable) — the CRM's OWN account name + domain (from `_raw/sample.csv`), carried through alongside the Sumble-matched `name`/`url` so a bad match is visible in the full `data.csv` export (Branch A only; not shown in the app).

**Saving (manual):** the app does NOT auto-save. The **Save** button POSTs the current slider weights + the client-computed score/rank to `/api/save-weights`; the server writes BOTH `account-scoring-weights.json` (weights) AND `data.csv` (adds/updates `score` + `rank` columns, one score per unique `org_id`, full data preserved). Scores come from the client (what you see), not a server recompute, so `data.csv` matches the app exactly.

> The unified endpoint does the matching: each input `{name,url}` resolves to a
> Sumble org and its `attributes`/`entities` come back in the same response.
> Unmatched inputs come back with empty `attributes` and are dropped by
> `merge_data.py`.

**Evaluation flag (always present, default false):**
- `is_icp_gold` (bool) — true for closed-won / strong-ICP rows

**Penalty flags (always present, 0/1):**
- `is_it_services` — `array_contains(tags, 'it_services')` (IT services
  shops are typically partners, not customers)
- `is_professional_services` — `industry = 'Professional Services'`
  (consultancies, accounting/legal firms, etc.; same partner-not-customer
  argument)

**Org attributes (always present, pipe-delimited `tags` column + 0/1
flags).** The template surfaces these in the toolbar as filter chips
*and* in the tag-multiplier widget, so they need to be in `data.csv`
even when they're not in `multipliers[]`. The chips light up via either
a `flag` column (above) OR membership in the `tags` column.
- `tags` (str, pipe-delimited) — the full Sumble tag list for the org,
  joined with `|` (e.g. `b2b|digital_native|is_ai_native`). Source:
  `organizations.tags` array. Drives the tag-multiplier picker and the
  attribute-chip filters.
- `is_b2b` / `is_b2c` / `is_digital_native` / `is_ai_native` (0/1) —
  convenience flags derived from `tags` (`array_contains(tags, '<slug>')`
  on the canonical Sumble slugs `b2b`, `b2c`, `digital_native`,
  `is_ai_native`). Optional — the chip falls back to a `tags`-membership
  check if these aren't emitted. **`b2b` and `b2c` are independent tags,
  not mutually exclusive** — a hybrid org gets both flags set to 1
  (e.g. JPMorgan Chase, Google: both consumer-facing AND
  business-facing). Treat them as separate facets, not as a binary
  choice.

**ICP signal columns** (one set per ICP element from Stage 2a; example
slugs):
- Persona count `{jf}_people` (int); concentration `{jf}_pct` (0–100);
  YoY % growth `{jf}_growth_yoy` (float, e.g. `0.20` = +20%).
- Tech team counts `{tech}_teams` (int, individual tech or category);
  tech team concentration `{tech}_team_pct` = `100 * {tech}_teams /
  NULLIF(organizations.teams_count, 0)` (0–100).

**Buying-window columns** (always present) — two per key project:
`{project}_x_relevant_tech_jobposts`
and `{project}_x_relevant_persona_jobposts` (Template C5). The relevant
sets follow the Stage 1 eligibility rules (tech = competitors +
complementary across key+other; personas key+other; projects key only).

**Funding columns** (only when `spec.include_funding` is true) — pulled
from the `/v6/organizations` funding attributes (1 credit each per matched
org). Three scoring signals (all `api_supported:true`, reproduced by
`score_accounts.py`):
- `funding_total_raised` (int USD, `log`) → **"Funding (size)"** category in
  the **ACV** section — overall firepower.
- `funding_last_round_raised` (int USD, `log`) → **"Funding momentum"**
  category in the **Intent** section — recent capital.
- `funding_days_since_last_round` (int days, **`recency`** transform) →
  "Funding momentum" / Intent — recency of the latest round. Derived from
  `funding_last_round_date` (whole days to today, min 1; "" when never
  financed → 0). The `recency` transform inverts the usual normaliser
  (`norm = clamp(1 − log1p(days) / log1p(p99), 0, 1)`): fewer days → higher
  score, beyond the p99-of-days → 0, never-financed → 0.

`funding_last_round_type`/`_date` are also carried as context (not scored).
When there are no projects (so no Intent section), all three sit in the ACV
"Funding" category. Rationale: more capital / a large, recent round =
bigger budget and an active hiring ramp = more interviews. Set
`"include_funding": true` in `spec.json` (Stage 2a) to enable.

**Non-Sumble (1P) columns** — anything the user can join by account, one
`{slug}_{measure}` column + one signal each, grouped into categories
(e.g. "Product usage", "Marketing engagement", "Third-party intent").
Inspect the attached MCPs and suggest what's available; null when missing.


### Default weights + calibration

**Two-step weighting: thoughtful priors, then a regularized fit to gold.**
`build_weights.py` lays down the policy-default weights (the priors).
`fit_weights.py` (Stage 3) then runs a small, deliberately-conservative solver
that nudges those weights toward separating the gold (closed-won) accounts —
without overfitting. The design:

- **Low DOF.** Only the section blend (ACV vs Intent) and the per-section
  category weights are fit. The within-category signal weights (geometric
  decay) are FROZEN — that's where overfitting would otherwise live.
- **Shrinkage to the priors.** Objective is
  `AUC(gold) − λ·‖w − w_default‖²`, so a weight moves only when the gold
  evidence overcomes the prior.
- **Box bounds.** No category weight drifts more than ±10 points, and the
  section blend ±15 points, from its default — the model stays recognizable.
- **K-fold CV picks λ on held-out gold**, never the training fit; the optimizer
  is derivative-free coordinate ascent (a few sweeps).
- **Adopt-only-if-it-generalizes.** The fit replaces the defaults only if
  held-out AUC beats the priors by ≥ 0.01; otherwise the priors stand.
- **Small-gold guard.** Fewer than ~40 gold rows → skip the fit, keep priors.

It's a warm start, not an autopilot: the fitted weights are the app's initial
slider positions, still fully tunable, and the Evaluation tab shows the
gold-lift you're tuning against. Deterministic — stratified round-robin folds
(no RNG) + a derivative-free optimizer mean same config + same `data.csv` →
same fitted weights. Constants live at the top of `fit_weights.py`.

Encoded as policy constants in `template/_build/build_weights.py` and
`template/_build/merge_data.py` — same `spec.json` + same endpoint
responses → same weights. The agent does NOT pick decay constants,
threshold rules, or default percentages per run. See
`template/_build/README.md` for the constants.

---

## Pipeline

Execute these stages in order. Surface progress between stages.

### Stage 1 — Interview

Goal: collect the input required to produce a first version of the score. Please follow these interview questions very closely and do not go off script. I want a deterministic interview that is the same between different runs of this skill. 

1. Please ask the company's name and their URL. You can prefill if you know it and ask the user to confirm. Also ask them where they want the account scoring to be stored. Can default to ./tmp/account_scoring/<company> directory. 

2. **No objective question.** The score always blends fit/size with buying-window
   intent (60/40) — don't ask the user to choose, and don't write any objective
   field to `spec.json`. The buying-window confirmation still happens in Q3.

3. Confirm the ICP. Call `GetMyCompanyProfile` for the URL and propose
   personas + technologies (+ projects), showing both `key` and `other`
   tiers. (If the lookup fails, propose with an LLM and snap to slugs via
   `SearchTechnologies` / `RunSqlQuery` on `job_functions`/`projects`.)
   Present as **ONE** compact markdown summary + a single yes/edit prompt
   (no multi-selects, no per-category questions); loop on edits until
   accepted. Example:
   ```
   Proposed ICP for <company>:
     • Personas: Sales, RevOps, Marketing
     • Technologies: clay, common-room, hg-insights, zoominfo
   Reply "yes", or describe changes (e.g. "drop marketing, add SDR").
   ```

   **Also confirm the buying-window combinations**
   — does each KEY project × the relevant set signal intent-to-buy-now?
   Show them as `project AND (tech₁ OR tech₂ …)` and `project AND
   (persona₁ OR …)`. Eligibility for the relevant sets:
   - **Projects**: `tier: key` only (the trigger).
   - **Technologies**: modern + legacy competitors + complementary,
     across `tier: key` AND `other`.
   - **Job functions**: both `tier: key` AND `other`.
   If no project genuinely signals intent, skip this sub-step.

4. **CRM account universe — upload or not?** Ask whether they want to
   upload their own CRM account list (the accounts they want scored).
   This forks the rest of the run.

   **Branch A — CRM uploaded.** We score a calibration **sample** of the
   CRM here; the full list is scored later by the separate scoring skill.
   1. Confirm the calibration sample drawn from their CRM. **Don't sample
      the whole CRM uniformly** — most of a large CRM is dead weight (in a
      100K-account CRM where only ~10K are assigned to a rep, the other
      ~90K are usually stale/junk and not worth calibration credits).
      Oversample the accounts that actually matter — customers and
      rep-assigned accounts — and size the sample by what the CRM exposes:
      - **Customers AND rep-assignment both known → recommend 5,000
        accounts**, composed of ~33% customers (the gold set,
        oversampled) and the remaining ~67% from rep-assigned,
        non-customer accounts. **Exclude unassigned accounts** — they're
        the junk tail.
      - **No customer flag OR no rep-assignment signal → recommend 10,000
        accounts**, drawn at random. Without a way to separate real
        targets from junk, a larger sample compensates.
      If the qualifying pool is smaller than the target, match all of it.
      Ask whether to oversample any other segment. A larger sample gives a
      more representative non-gold distribution and steadier p99
      normalization, so the ranked list is more trustworthy (smaller
      samples calibrate faster but rank less reliably). Surface the credit
      cost of the chosen size upfront (~`(1 + paid-attrs + Σ
      entity-metrics)`/org). Tell the user the full CRM gets scored later
      by the separate scoring skill — no bulk MCP run.
   2. Ask what other (non-Sumble) data to fold in:
      - **ICP gold set** — closed-won / strong-ICP accounts; sets
        `is_icp_gold` for the Evaluation tab AND drives Step 4(a)
        tag-lift calibration (boost/penalty defaults for ALL six
        attributes — `b2b`, `b2c`, `digital_native`, `is_ai_native`,
        `it_services`, `professional_services` — uniformly through
        `tag_multipliers`).
      - **1P signals** — product/PLG usage, marketing engagement,
        meeting activity, third-party intent (one `{slug}_{measure}`
        column each).
      For the gold set and each 1P source, run the source-confirmation
      flow below before reading anything. **Don't ask about IT-services
      / Professional-services penalties as a separate question** —
      they're tags handled by the same lift calibration as the other
      four attributes (Step 4a). No special priors.

   **Branch B — no CRM.** Rank Sumble's universe with the endpoint's
   `filter` mode (Stage 2c `--mode filter`).
   1. Ask **how many accounts to score** (1000 recommended).
      Communicate the credit cost upfront (`(1 + paid-attrs + Σ
      entity-metrics)` per returned org).
   2. The candidate universe is ranked by an ICP advanced query and
      `order_by_column` (default `employee_count`, or `account_score` if
      your domain has Sumble account scores), then enriched with the same
      `select` — one `POST /v6/organizations` per page. No CRM match, no
      gold set, no 1P signals.
   3. Ask about audience filters / penalties: HQ-country whitelist
      (default global), headcount floor (default ≥200), excluded org
      types (default `it_services`, `professional_services`, `k12`,
      `university`, `hospital`, `government`), and any tag
      whitelist/blacklist. Hard filters drop orgs from the pool; the
      partner penalties above still apply as in-app multipliers.

**Source confirmation (Branch A gold set + 1P) — never assume.** Inspect
   the session's MCPs and surface relevant ones by name (Salesforce,
   HubSpot, Snowflake/BigQuery/Databricks/Postgres, Sheets/Drive,
   Gong/Fireflies/Granola); else CSV path. Then: list tables → hypothesise
   the source table (SF gold → `Account IsCustomer__c=true` or closed-won
   `Opportunity`; HubSpot → `lifecyclestage=customer`; warehouse →
   `dim_accounts`/`customers`/`product_usage_*`) → confirm in one prompt →
   sample-read `LIMIT 10` and verify join keys before the full pull.
   **Also look for a rep-assignment signal** (SF `Account.OwnerId` /
   `Owner.Name`, HubSpot `hubspot_owner_id`, or an `owner`/`account_owner`
   column in the export) — it drives the Q4.1 sample composition
   (oversample customers + rep-assigned accounts; an account with a real
   owner is one the company actually works, vs the unassigned junk tail).
   If neither a customer flag nor an owner field is present, fall back to
   the larger random sample (Q4.1).

**Per-tag multiplier widget** is in the template (up/down-weight any tag
   at scoring time) — surface it in the app; don't enumerate tags in the
   interview.

### Stage 2 — Fetch data from the unified endpoint

No SQL signal pulls. Every column comes from one REST call,
`POST https://api.sumble.com/v6/organizations` (match + enrich + select). The
`_build/` scripts build the request from `spec.json`, POST it, and merge the
JSON into `data.csv`. Confirm `SUMBLE_API_KEY` is set first.

#### Stage 2a — Resolve ICP slugs/names (the only "ID resolution" step)

- **Technologies** → `SearchTechnologies` per term → slug. Keep the user's input
  string and the resolved slug; show both back before fetching.
- **Job functions** → the endpoint's `job_function` term is the **display Name**
  (e.g. `Revenue Operations`, `Sales`). Take the names from
  `GetMyCompanyProfile`, or canonicalise via a single `RunSqlQuery`:
  ```sql
  SELECT id, name, slug FROM job_functions
  WHERE LOWER(name) IN ('sales','marketing','revenue operations')
     OR LOWER(slug) IN ('sales','marketing','revenue-operations');
  ```
- **Projects** → slug, from the profile or one
  `RunSqlQuery` on `projects`.

Write **`_raw/spec.json`** (schema: `template/_build/README.md`). Personas carry
`{slug, name, tier, label}` (`name` is the endpoint term), techs `{slug,…}`,
projects `{slug,…}`. Show the resolved set back to the user before fetching.

#### Stage 2b — Write the input list

- **Branch A (CRM uploaded):** write `_raw/sample.csv`
  (`crm_account_id,name,domain[,is_gold]`) — the calibration sample sized
  and composed per Q4.1: **5,000** when customers + rep-assignment are both
  known (~33% customers / ~67% rep-assigned non-customers, unassigned
  accounts excluded), or **10,000 random** when either is unknown.
  `is_gold=1` on the customer rows. The endpoint matches by name/url, so
  there is **no separate `MatchOrganizations` step**.
- **Branch B (no CRM):** no input list — Stage 2c runs in `filter` mode (the
  endpoint ranks Sumble's universe by an ICP advanced query). Put the audience
  filters from Q4-B.3 in `spec.json.universe_filters`.

#### Stage 2c — Fetch + merge

Run each as ONE command with absolute paths — no `cd`, no chaining (see
Shell-command discipline):

```bash
# Branch A (CRM list):
python3 <skill_dir>/template/_build/fetch_data.py --raw <output_root>/_raw
# Branch B (no CRM):
python3 <skill_dir>/template/_build/fetch_data.py --raw <output_root>/_raw --mode filter --pool 1000
# then, both branches:
python3 <skill_dir>/template/_build/merge_data.py --raw <output_root>/_raw
```

`fetch_data.py` POSTs to `/v6/organizations` in ≤1000-org batches (or paginated
`filter` pages), saving `_raw/responses/resp_*.json`; `merge_data.py` parses
them into `data.csv` (`is_icp_gold` flagged) + `_raw/_calibration_audit.json`
(tag-lift, auto-computed). Same `spec.json` + same responses → byte-identical
output; policy constants live in the scripts.

**Credit cost** ≈ `(1 + paid-attributes + Σ entity-metrics)` per matched org
(~16 for a typical ICP). Surface the estimate before running a large sample.

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
python <skill_dir>/template/_build/fit_weights.py --raw <output_root>/_raw
```

→ `<output_root>/account-scoring-weights.json`. `build_weights.py` renders
the spec + audit into the live config with the **policy-default** weights;
`fit_weights.py` then nudges those weights toward the gold set (see "Default
weights + calibration" below) and rewrites the config in place. Surface the
`_raw/_weight_fit_report.json` summary to the user (default vs fitted held-out
AUC, and whether the fit was adopted) so they know how the sliders were set.

Write `<output_root>/.gitignore` via `Write`:
```
__pycache__/
*.csv
```

---

### Stage 4 — Run instructions

Print this to the user. Don't try to run the server inside Claude Code —
let the user start it in a terminal where it stays up.

```bash
cd ./tmp/account_scoring/<company>
python app.py
# open http://localhost:8001 in your browser
```

No `pip install`, no virtualenv, no extra setup — `app.py` is stdlib-only
and runs on any Python 3.10+. Override the port via `python app.py 9001`
or `PORT=9001 python app.py`.

To score a larger list once weights are tuned, hand
`account-scoring-weights.json` to the separate scoring skill.

---


