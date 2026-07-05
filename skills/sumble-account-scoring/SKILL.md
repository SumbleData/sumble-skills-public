---
name: sumble-account-scoring
description: "Build an account-scoring AND/OR whitespace web app powered by Sumble data and optional first-party data. One skill, three objectives: score the accounts in your CRM, find whitespace (high-ICP-fit orgs NOT in your CRM), or both in one ranked sheet. Interviews the user about their ICP, pulls data from internal systems and possibly Sumble MCP, and generates a self-contained, zero-dependency Python + HTML/JS app at account_scoring/<company>/ with real-time slider re-weighting, an account-category column + filters (customer / allocated / unallocated / whitespace), and an evaluation mechanism to tune the score. Outputs a config file describing the scoring method and a Python script that applies it across all accounts."
---

# Account Scoring

This skill produces two things:

1. A zero-dependency Python **web app** (stdlib `http.server`) that ranks the
   user's accounts (and/or whitespace) and lets them tune signal weights with
   sliders. Data comes from the Sumble MCP plus optional 1P.
2. A portable config file account-scoring-weights.json that describes everything
   required to replicate the score in a production system, plus
   `score_accounts.py` to apply it to a larger list later.

**How much to score is the user's call, asked in the interview — not a forced
sample.** By default we score everything they hand us: an account list of
< 100,000 is scored whole (the recommended default — credits are rarely the
binding constraint, and one full pass makes the app and calibration complete).
Only when the list is very large (≥ 100,000) do we ask whether to spend the
credits to score it all or to score a representative subset/sample (Q4.1) — the
tradeoff is theirs, surfaced with the credit cost. Whitespace is ranked for free
and only the chosen pool is enriched. For a one-off score of an even larger book
later (or daily refresh), hand `account-scoring-weights.json` to
`score_accounts.py`.

Follow the stages closely — input (interview) and output should be
consistent between runs, more deterministic than most skills.

## When to use

Trigger on `/sumble-account-scoring`, or on any of: "score my accounts",
"build an account score", "find whitespace accounts", "rank net-new accounts
I'm not selling to", "who looks like our ICP but isn't in our CRM?", or "score
my CRM and find whitespace". This is the **single, consolidated** skill for
account scoring AND whitespace — Stage 1 Q4 asks the objective (score /
whitespace / both) and the rest of the run adapts.

## Required tools

- **Sumble MCP** (for the ICP interview only):
  - `SearchTechnologies` — fuzzy tech discovery when you don't yet have a term
  - `GetMyCompanyProfile` — pre-fill ICP (personas, technologies, projects)
  - `RunSqlQuery` — **only** the Stage 2a tech-category roll-up aggregation
    (coverage %); it has no endpoint equivalent. Name/slug resolution for
    technologies, job functions, and projects now uses the v6 lookup endpoints
    via `_build/lookup.py` (NOT RunSqlQuery).
- **Sumble public API key** — `SUMBLE_API_KEY` (from sumble.com/account). All
  Stage-2 data now comes from one REST endpoint,
  `POST https://api.sumble.com/v6/organizations` (match + enrich + select in a
  single call). The MCP has no wrapper for it, so the `_build/fetch_data.py`
  script calls it directly.

  **Check before prompting — the key is usually already set.** BEFORE you
  surface the link or ask the user to do anything about the key, check whether it
  already resolves. Run this one simple command and read the result:
  ```bash
  ls ~/.config/sumble/api_key
  ```
  If that file exists (or `SUMBLE_API_KEY` is exported in the env), the key is
  configured — say so in one line and move on. Do NOT prompt for it, and do NOT
  surface the setup link. Only when the check comes up empty do you fall through
  to the setup flow below.

  **Set the key once (only if the check above came up empty).** First tell the
  user **where to get it: their key is at
  https://sumble.com/account (Account → API key)** — surface this link before
  prompting. Then have them run the helper, which prints that link, reads the
  key **without echoing** (so it never lands in the chat transcript or shell
  history), and saves it to `~/.config/sumble/api_key` (chmod 0600):
  ```bash
  ! python3 <skill_dir>/template/_build/set_api_key.py
  ```
  **Always `python3`, never bare `python`** — stock macOS (and many Linux
  boxes) ship `python3` only, and `python ...` fails with "command not found".
  **If `python3` itself is missing or broken**, use the zero-dependency POSIX
  shell version (identical behavior — hidden input, `~/.config/sumble/api_key`,
  chmod 600):
  ```bash
  ! sh <skill_dir>/template/_build/set_api_key.sh
  ```
  Use a hidden-input helper as the default — **don't ask the user to paste the
  key into the chat** (it would be logged). `fetch_data.py` and
  `score_accounts.py` then find it automatically. Power-user alternatives the
  resolver also accepts: `export SUMBLE_API_KEY=...` (this session only) or a
  gitignored `.env` file passed via `--env-file path/to/.env`.

If the Sumble MCP isn't available in the session, stop and tell the user
how to install it: https://docs.sumble.com/api/mcp.

## Shell-command discipline

This runs unattended AND is shipped to non-technical users — and it may run in
**Claude Code, Codex, Cursor, or any other coding agent**. They all gate shell
commands behind a command-approval / permission system that **interrupts the run
on anything complex** (compound, redirected, `cd`-prefixed, or
substitution-bearing commands — Claude Code, for instance, blocks "compound
command contains `cd` with output redirection" and "brace with quote"). Each
interruption stalls the run, in every agent. Keeping commands trivially simple is
the portable way to avoid that everywhere. Follow these rules exactly:

- **One simple command per shell call.** No `&&` / `;` / `|` chains, no `cd`, no
  output redirection (`>`, `>>`, `2>&1`), no backgrounding (`&`, `nohup`), and no
  command substitution (`$(…)` or backticks).
- **Use absolute paths, never `cd`.** Every `_build/*` script takes its directory
  as an argument, so run e.g.
  `python3 <skill_dir>/template/_build/fetch_data.py --raw <output_root>/_raw`
  from anywhere — no `cd`, no relative `_raw`.
- **Run the pipeline in the foreground.** The scripts stream progress to stdout
  (the agent shows it live) and finish in a few minutes. NEVER background a step
  (`nohup … &`) and poll it with `ps aux | grep …` / `tail` — every poll is a
  fresh approval prompt, and the redirection trips the guard.
- **No inline Python, no heredocs.** Any multi-line Python, JSON shaping, counting,
  or snapshotting → write a `.py` to `<output_root>/_raw/` (with your agent's file
  tool) and run it as a single `python3 <abs>.py`. Never `python3 -c "…{…}…"` (the
  `{`+`"` trips the prompt).
- **Inspect with your agent's file tools, not the shell.** Use the native
  file-read / glob / grep tools (Read·Glob·Grep in Claude Code; the equivalents in
  Codex / Cursor) — never `cat` / `tail` / `head` / `ls` / `wc` / `grep`.

The only shell this skill needs is `mkdir -p <abs>`, `cp <abs> <abs>`, and
`python3 <abs>/script.py [args]` (the `_build/*` pipeline + Stage 4
`python3 app.py`) — each as one standalone command. Everything else is a tool.

**Running a command in the user's own terminal.** A couple of steps (the API-key
helper, launching `app.py`) are best run by the user so they're interactive / stay
up. In **Claude Code** prefix the command with `!` to run it in the user's
terminal (e.g. `! python3 <skill_dir>/template/_build/set_api_key.py`). In
**Codex / Cursor** (no `!` syntax), just tell the user to paste that same command
(without the `!`) into a terminal themselves. Always write `python3`, never bare
`python` (absent on stock macOS); when Python is unavailable entirely, every
`set_api_key.py` usage has a shell twin: `sh <skill_dir>/template/_build/set_api_key.sh`.

## Output

```
account_scoring/<company>/
  app.py                          stdlib http.server (copied from template/, unchanged — no deps)
  account-scoring-weights.json    weights + scoring formula + data-source
                                   metadata + derived columns + table layout
                                   + per-signal p99 + api_supported; the app
                                   opens from this file, and a separate
                                   scoring skill reproduces the score from it
  score_sheet.py                  GENERATOR SCRIPT (not a CSV) — regenerates score.csv from data.csv + weights on Save/startup (copied from template/, unchanged)
  data.csv                        IMMUTABLE raw API pull (all raw signal columns); the re-score source, never rewritten by the app
  score.csv                       THE one file you use — a SUPERSET of data.csv: rank → all data columns → score → base_score → profile_adjustment (+detail) → per-signal contribution columns → deep links, sorted by rank (zero-contribution signals drop only their contribution column)
  static/                         UI: sliders, table, per-row breakdown
  README.md
```

**Only two CSVs, with one clear job each** (`score_sheet.py` is the generator
*script*, not a third CSV):
- `data.csv` — the **immutable** raw API pull (every signal's raw count). The
  app never rewrites it; it's the source the app re-scores from. You can ignore
  it unless you want the untouched raw archive.
- `score.csv` — **the one file you use.** A *superset* of `data.csv`: it carries
  every data column PLUS `score`, `rank`, `base_score`, `profile_adjustment`
  (+ a `profile_adjustment_detail` column naming each applied boost/penalty,
  e.g. `digital_native +15%; it_services -35%`), one per-signal **contribution**
  column (`norm × effective_weight × 100`, ordered most-impactful-first,
  summing exactly to `base_score`), and **deep links** (`sumble_url` + one per
  signal) — sorted by rank. The boost/penalty multipliers are NOT folded into
  the contributions; they're explicit:
  `score = base_score × profile_adjustment`. So you never join score.csv back
  to data.csv. The app **regenerates** it from `data.csv` + the tuned weights
  on every Save and at startup (`score_sheet.build_score_sheet`); a signal with
  0 total contribution drops only its contribution column (its raw column
  stays). The **Download score sheet** button produces the same sheet from the
  current sliders, and the per-account breakdown panel shows the same story:
  signal contributions → base score → each boost/penalty line → final score.

**Two score-sheet non-negotiables (NEVER strip these — the template enforces
both with fallbacks):**
1. **Deep links, always.** Every Sumble count/growth signal carries a
   `sumble_link` spec in the weights config (`build_weights.py` writes them — do
   NOT drop them if you edit the config by hand). The app's per-row breakdown,
   `score.csv`, the in-app **Download score sheet**, and `score_accounts.py`
   output all emit per-signal deep links: they prefer the API's canonical
   `{column}_link` from `data.csv` and fall back to building the URL from the
   `sumble_link` spec, so links appear even when one source is missing.
   `sumble_url` (the org's Sumble page) is always present. Concentration
   signals are the one deliberate exception (no per-signal deep link).
2. **HQ country, always.** `headquarters_country` is fetched for every org and
   `score.csv`, the in-app download, and `score_accounts.py` output always
   carry the column (blank when unknown). Don't drop it from `data.csv`.

Before handing over (Stage 4), spot-check the `score.csv` header with your file
tools: it must contain `headquarters_country`, `sumble_url`, and at least one
`<signal> link` column. If any is missing, the config or data was built wrong —
fix it before telling the user the app is ready.

**Zero-dependency rule:** `app.py` uses only the stdlib (`csv`, `json`,
`math`, `http.server`) — no `requirements.txt`, no third-party imports,
so any teammate can `python3 app.py` on the first try.

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

**Account category (always present; blank in pure Branch B):**
- `account_category` (str) — one of `customer` (closed-won), `allocated`
  (CRM, rep-assigned), `unallocated` (CRM, no rep), `whitespace` (high-fit
  org NOT in the CRM; label "Whitespace — new account"), `whitespace_subsidiary`
  (whitespace whose parent IS a CRM account — land-and-expand; label
  "Whitespace — parent in CRM"; detected from BOTH `parent_id` and the inverse
  direction, membership in a CRM org's `subsidiary_ids`, since the endpoint
  omits `parent_id` on some rows), or `""` when no CRM was provided. The two
  whitespace kinds are separate filter chips so net-new accounts and
  parent-in-CRM subsidiaries can be viewed independently. Single
  source of truth: `is_icp_gold = (account_category == "customer")` and
  `in_crm = account_category in {customer, allocated, unallocated}`. The app
  renders a **Category** column + filter chips **only when ≥2 distinct
  non-blank categories are present**, and the Evaluation tab shows a
  rank-distribution-by-category table.

**Evaluation flag (always present, default false):**
- `is_icp_gold` (bool) — true for closed-won / strong-ICP rows
  (`account_category == "customer"`)

**Penalty flags (always present, 0/1):**
- `is_it_services` — `array_contains(tags, 'it_services')` (IT services
  shops are typically partners, not customers)
- `is_professional_services` — `array_contains(tags, 'professional_services')`
  (consultancies, accounting/legal firms, etc.; same partner-not-customer
  argument. A native Sumble org tag, exactly like `it_services`.)

**Org attributes (always present, pipe-delimited `tags` column + 0/1
flags).** The template surfaces these in the toolbar as filter chips
*and* in the tag-multiplier widget, so they need to be in `data.csv`
even when they're not in `multipliers[]`. The chips light up via either
a `flag` column (above) OR membership in the `tags` column.
- `tags` (str, pipe-delimited) — the full Sumble tag list for the org,
  joined with `|` (e.g. `b2b|digital_native|is_ai_native`).
  Source: `organizations.tags` array, verbatim — `professional_services` is a
  native Sumble org tag (no industry-based synthesis; it arrives like
  `it_services`). Industries are NOT synthesized into tags — calibration is
  purely over the org's Sumble tags. Drives the tag-multiplier picker and the
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

**Funding columns** (only when `spec.include_funding` is true — **OFF by
default and never suggested**: funding only covers venture-backed companies,
so scoring it artificially boosts them; see the Stage 1 Q2 note. Enable only
on explicit user request, with the coverage-skew warning) — pulled
from the `/v6/organizations` funding attributes (1 credit each per matched
org). Three scoring signals (all `api_supported:true`, reproduced by
`score_accounts.py`):
- `funding_total_raised` (int USD, `log`) → **"Funding (total raised)"**
  category in the **Size** segment — overall firepower.
- `funding_last_round_raised` (int USD, `log`) → **"Funding momentum"**
  category in the **Growth & momentum** segment — recent capital.
- `funding_days_since_last_round` (int days, **`recency`** transform) →
  "Funding momentum" / Growth & momentum — recency of the latest round.
  Derived from `funding_last_round_date` (whole days to today, min 1; "" when
  never financed → 0). The `recency` transform inverts the usual normaliser
  (`norm = clamp(1 − log1p(days) / log1p(p99), 0, 1)`): fewer days → higher
  score, beyond the p99-of-days → 0, never-financed → 0.

`funding_last_round_type`/`_date` are also carried as context (not scored).
The Growth & momentum segment always exists (persona growth), so funding
momentum lands there regardless of whether the spec has projects. Set
`"include_funding": true` in `spec.json` (Stage 2a) to enable — again, only
when the user explicitly asked. (These default segment placements move if
`spec.section_plan` reassigns the `funding` / `funding_momentum` categories.)

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

- **Low DOF.** Only the segment blend (Size / Concentration / Growth &
  momentum, or whatever segments the spec defines) and the per-segment category
  weights are fit. The within-category signal weights (geometric decay) are
  FROZEN — that's where overfitting would otherwise live.
- **Shrinkage to the priors.** Objective is
  `AUC(gold) − λ·‖w − w_default‖²`, so a weight moves only when the gold
  evidence overcomes the prior.
- **Box bounds.** No category weight drifts more than ±20 points, and the
  segment blend ±25 points, from its default — the model stays recognizable.
- **K-fold CV picks λ on held-out gold** via the 1-SE rule over paired
  per-fold gains vs the defaults (among λs within one standard error of the
  best mean gain, the largest — most shrinkage — wins); the optimizer is
  derivative-free coordinate ascent (a few sweeps).
- **Adopt-only-if-it-generalizes.** A paired per-fold test: the fit replaces
  the defaults only when the mean held-out AUC gain clears both an absolute
  floor (0.002) and one standard error of the per-fold gains — the bar scales
  with the evidence, so a consistent small gain on a large gold set is adopted
  while same-size noise on a tiny one is not.
- **Small-gold guard.** Fewer than ~20 gold rows → skip the fit, keep priors.
- **Speed/balance.** The fit ranks gold against a deterministic systematic
  subsample of ≤5,000 non-gold rows; reported full-sample metrics use all rows.

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

**Numbering rule:** the interview has **4 main questions**. Start every
interview message with a progress marker — `**Question N of 4**` (sub-steps
as `Question 4 of 4 — part 4.1`, etc.) — so the user always knows where they
are and how much interview remains. When you combine questions into one
message, label it with the range (e.g. `**Questions 2–4 of 4**`).

**Confirmation rule (applies to EVERY confirm step in this interview):** when
you ask the user to confirm something — the ICP, the segments, the
buying-window combos, the universe filters — the COMPLETE thing being
confirmed MUST be rendered in full, as markdown, in the SAME message as the
question. Never ask "confirm the proposed ICP/filters?" while the details
live only in an earlier message, in a tool result, or inside multiple-choice
option labels (interactive question widgets truncate labels and descriptions
— they are NOT a substitute for printing the list). If anything changed since
the last time it was shown, re-print the whole updated list, not a diff.

1. Please ask the company's name and their URL. You can prefill if you know it and ask the user to confirm. Also ask them where they want the account scoring to be stored. Can default to ./tmp/account_scoring/<company> directory. 

2. **Segments (the score's top-level breakdown).** The score is a weighted
   blend of **segments** (the config's `sections`). The default is three
   orthogonal segments — **don't re-derive them, just propose them and let the
   user adjust**:
   - **Size (50%)** — how big is the opportunity: persona headcount, tech
     team counts, recent project×tech / project×persona job posts.
   - **Growth & momentum (30%)** — is now the time: persona YoY growth.
   - **Concentration (20%)** — how strong / focused the fit: persona
     concentration (% of company) and tech-team concentration (% of teams).

   **Do NOT suggest funding attributes.** Funding data only exists for
   venture-backed companies — everyone else reads 0 — so scoring it
   artificially boosts startups (the partial-coverage principle in
   `articles/01`); what funding indicates shows up in growth attributes
   anyway. Include funding ONLY if the user explicitly asks for it, and when
   they do, warn them about the coverage skew (it can be reasonable when
   their universe is overwhelmingly venture-backed).
   
   Present these three with their blend and one yes/edit prompt. The user can
   **rename, reweight, drop, or add segments**, and may **repeat a signal in
   more than one segment** (e.g. project×tech under both Size and Concentration).
   For inspiration, offer a **business-segment breakdown** when the company
   sells distinct product lines — e.g. for Oracle a segment scoring OCI fit and
   a separate segment scoring Apps fit, each with its own techs/personas. Weave
   any 1P signals (Q4.3) into an existing segment or a new one.

   Encode the user's choices in `spec.section_plan` (schema in
   `template/_build/README.md`): `{sections:[{key,label,default_pct}],
   category_section:{<category>:<segment>}, category_meta:{...}}`. Omit
   `section_plan` to take the three defaults verbatim. Don't write any
   objective field. (The buying-window confirmation still happens in Q3.)

3. Confirm the ICP. Call `GetMyCompanyProfile` for the URL and propose
   personas + technologies (+ projects), showing both `key` and `other`
   tiers. (If the lookup fails, propose with an LLM and snap to slugs via
   `SearchTechnologies` / `RunSqlQuery` on `job_functions`/`projects`.)

   **Resolve slugs and roll up into categories BEFORE you present — so the
   user confirms the FINAL shape, not raw techs that change in Stage 2a.**
   First snap every proposed tech to its slug (`SearchTechnologies`), then run
   the category roll-up (the procedure + SQL in Stage 2a → "Roll individual
   techs up into predefined categories"). Present the ICP with the rolled-up
   **categories** in place of their absorbed individual techs (showing each
   category's coverage% and the techs it absorbs), and the unabsorbed techs as
   individuals. This is just early invocation of the Stage 2a logic; Stage 2a
   then only persists the already-confirmed result to `spec.json`.

   Present as **ONE** compact markdown summary + a single yes/edit prompt
   (no multi-selects, no per-category questions); loop on edits until
   accepted. **The summary must be COMPLETE — every element of the ICP the
   pipeline will fetch, with nothing elided:** all personas with key/other
   tiers; every technology category with its coverage% and the full list of
   absorbed techs; every individual tech with its tier; every project; and —
   only if the user explicitly asked for funding — that funding attributes
   are on. Render it in the message itself (see the Confirmation rule above
   — never rely on question-widget option labels to carry the list). Example:
   ```
   Proposed ICP for <company>:
     • Personas (key): Sales, RevOps · (other): Marketing
     • Technology categories: Inference & Serving (31% — absorbs vllm,
       baseten, modal, replicate)
     • Technologies (individual): clay (key), common-room (key),
       hg-insights (other), zoominfo (other)
     • Projects: Generative AI, Digital Transformation
   Reply "yes", or describe changes (e.g. "drop marketing, add SDR",
   "split out vllm from Inference & Serving").
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

4. **Objective — score, whitespace, or both? Ask this FIRST; it drives the
   rest.** Record as `spec.mode`:
   - **(A) Score CRM accounts** (`score`) — rank the accounts already in their
     CRM.
   - **(B) Whitespace** (`whitespace`) — rank high-ICP-fit orgs NOT in their
     CRM.
   - **(C) Both** (`both`) — score the CRM *and* surface whitespace, in one sheet.

   All three build the **same** app — one ranked sheet with the
   account-category column + chips and the Evaluation tab; they differ only in
   which accounts fill the pool. This is the consolidated home for scoring AND
   whitespace.

   **Inputs — ask only what the objective needs.** Up to three things, in
   **either shape** (one table with flag columns, OR separate lists — leave both
   open). **Actively encourage the user to share all three of (a), (b), and (c)
   whenever the objective scores the CRM (modes A/C)** — they are complementary,
   not redundant: (a) is the *overall universe*, and it's the combination of (a)
   and (b) that lets the app distinguish **unallocated** accounts (in the
   universe but not rep-assigned) from **allocated** ones. Without (a) you lose
   the universe denominator; without (b) every CRM account collapses to one
   bucket and the unallocated view disappears. Pitch all three together up front
   rather than settling for whatever the user volunteers first.
   - **(a) Whole CRM universe** — every account in their CRM. The scored set in
     A/C; in B/C used to *exclude* owned accounts from the whitespace pool
     (optional in B — without it, whitespace is just an ICP ranking of Sumble's
     universe). **The overall universe** — the denominator that (b) is subtracted
     from to reveal unallocated accounts.
   - **(b) Rep-allocated accounts** — assigned to a rep / owner (e.g.
     `Owner.Name`/`hubspot_owner_id` present, `is_owned`). Only relevant when
     scoring the CRM (A/C); flags `allocated` vs `unallocated`. **Pair it with
     (a)** so the app can surface which universe accounts are *unallocated* —
     high-fit accounts nobody is working yet.
   - **(c) Closed-won / customers** — closed-won flag (`IsCustomer__c`,
     `lifecyclestage='customer'`, a closed-won `Opportunity`). Strongly
     encouraged in ALL modes. **When asking for this input, explain it in
     plain language — internally it's called the "gold set", which confuses
     users, so spell out what it is and how it's used.** Say something like:
     > "Your existing customers act as the **answer key** for the score.
     > They're used in three ways: (1) the **Evaluation tab** checks that
     > known customers rank near the top — if they don't, the weights are
     > wrong; (2) the **weight fit** nudges the starting sliders toward
     > whatever separates your customers from everyone else; (3) the
     > **industry/attribute boosts** are calibrated from which segments your
     > customers concentrate in. Customers are never filtered out or treated
     > as prospects — they're the measuring stick."
     In B (whitespace-only) they are also scored and shown as `customer` rows
     alongside whitespace so the user can confirm known-good accounts still
     rank highly. Avoid the bare term "gold set" in user-facing messages;
     if you use it, define it inline ("gold set = your closed-won customers,
     the known-good examples the score is checked against").

   Resolve overlaps so **each account lands in exactly one `account_category`**,
   precedence customer > allocated > unallocated:
   - `customer` — closed-won (also sets `is_icp_gold`)
   - `allocated` — in CRM, rep-assigned, not closed-won
   - `unallocated` — in CRM, not rep-assigned, not closed-won (surfaced so the
     team can spot accounts that *should* be allocated)
   - `whitespace` — high-fit org NOT in the CRM (modes B/C)

   **If they have NO lists at all** (and don't want whitespace): score Sumble's
   universe (`--mode filter`, Stage 2c) — no categories, no gold, no
   calibration, `account_category` left blank (the app hides the category column
   + chips). Closed-won (c) is the one input worth pushing for in any mode —
   without it the Evaluation tab can't check ICP recovery.

   **Source-confirmation flow (run before reading anything) — never
   assume.** Inspect the session's MCPs and surface relevant ones by name
   (Salesforce, HubSpot, Snowflake/BigQuery/Databricks/Postgres,
   Sheets/Drive, Gong/Fireflies/Granola); else ask for a CSV path. Then:
   list tables → hypothesise the source (universe → SF `Account` /
   HubSpot `companies` / warehouse `dim_accounts`; allocated → a non-null
   `Account.OwnerId` / `Owner.Name` / `hubspot_owner_id` / `account_owner`;
   closed-won → `Account IsCustomer__c=true` or closed-won
   `Opportunity.AccountId` / HubSpot `lifecyclestage='customer'` / warehouse
   `customers`) → confirm in one prompt → sample-read `LIMIT 10` and verify
   join keys (name, URL/domain) before the full pull. **Don't ask about
   IT-services / Professional-services penalties separately** — those are
   tags handled by the same lift calibration as the other attributes
   (Step 4a).

   **4.1 — How big is the scored CRM universe? (modes A/C only.)** We score the
   set the user chooses here; a larger book can be scored later by
   `score_accounts.py`.
   - **< 100,000 accounts → score them all** (the recommended default; the
     sample = the whole provided universe). Credits are rarely the binding
     constraint and a full pass keeps the app + calibration complete.
   - **≥ 100,000 accounts → ask which to score** (a credit / time tradeoff):
     1. **All accounts in CRM** — most complete, costs the most credits and
        runs longest.
     2. **Only rep-allocated accounts (b)** — the accounts the team works.
     3. **A subset they specify** — they tell us how to narrow it (a
        segment, a saved view, a filter).
     4. **A stratified sample we draw (recommended at this scale)** — target
        ~30% closed-won, ~40% rep-allocated, ~30% unallocated, sized to
        ~50,000. A representative non-gold distribution + steadier p99 at
        bounded credit cost. If a stratum's pool is smaller than its target,
        take all of it and let the others fill the remainder.
   Surface the credit cost of the chosen size upfront (~`(1 + paid-attrs +
   Σ entity-metrics)`/org). Tell the user the full CRM gets scored later by
   `score_accounts.py` — no bulk MCP run.

   **4.2 — Whitespace pool size (modes B/C).** Ask **how many** net-new
   candidates to rank — **recommend 10,000** (default). Surface the credit cost
   first: candidate *ranking* is FREE (id/name/url selects cost no credits); only
   the final pool is enriched, so cost ≈ `pool × (1 + paid-attrs + Σ
   entity-metrics)`/org. We resolve the whole CRM universe (a) to Sumble org_ids
   and exclude them, then preselect ICP-fit candidates; they get
   `account_category = whitespace` in the same sheet, filterable.

   **Preselection is stratified** (`spec.universe_filters.preselect`,
   default `auto`): `auto` uses the caller's Sumble **account score** when their
   domain has one, else a **stratified** pool that avoids size-bias — 20% by key
   technology job posts, 20% by key project job posts, 20% by key persona
   **concentration** (size-neutral density), 40% by **fastest-growing** key
   personas (split evenly across them). The persona strata use the v6 endpoint's
   per-job-function sorts — `order_by_column: people_concentration` and
   `people_count_growth_1y` with `order_by_job_function: <persona>` — so they
   rank by the persona's true share / YoY people growth, not org-total proxies.
   Each stratum is gated on a min-employee floor (`min_employees`, default 50)
   and deduped against the CRM and prior strata. A candidate whose **parent** is a
   CRM account is land-and-expand: `merge_data.py` relabels it
   `account_category = whitespace_subsidiary` (label "Whitespace — parent in
   CRM"; plain whitespace is "Whitespace — new account") — **not** a separate
   tab, just another category chip in the one sheet, separate from the new-
   account chip so the user can filter either kind in or out independently. In **whitespace-only (B)**,
   the scored `sample.csv` holds just the closed-won customers (calibration +
   eval) — no CRM scored set.

   **Universe filters (modes B/C) → `spec.universe_filters`.** Set the bounds on
   the whitespace pool (whitespace rows only — your CRM accounts are never
   filtered). **Before asking the user to confirm, ALWAYS print the complete
   proposed filter block in the message** — `min_employees`, the country
   whitelist (or "global"), every hard-exclude tag by name, the
   professional-services switch, and every excluded industry by display name.
   This applies even when reusing a prior run's filters ("same as last time"
   is not a confirmation — re-list them). Two kinds — handle them differently:

   - **Cheap, near-universal org-type / firmographic bounds** (the ranker pushes
     these into the query, so they cost nothing): `min_employees` (default
     **50**); `hq_country_whitelist` (default none → global); `hard_exclude_tags`
     — the four org-type tags `org_type_k12_school`, `org_type_university`,
     `org_type_hospital`, `org_type_government` are sensible **proposed** defaults
     for B2B (offer them, let the user keep/drop any), plus `it_services` as a
     common extra. (Steer users away from hard-excluding `b2b`/`b2c` — many good
     accounts are hybrid; calibrate those instead.)

     **ALWAYS ask about PE firms explicitly**: should private-equity firms be
     hard-excluded from the whitespace pool (`is_private_equity_firm` in
     `hard_exclude_tags`)? PE/buyout firms often rank high on tech-hiring
     signals via their portfolio yet are rarely a sellable account themselves —
     recommend excluding unless the user actually sells to PE firms (fintech,
     fund-admin, deal tooling). Their portfolio companies are separate orgs and
     stay rankable either way.

   - **Industry HARD EXCLUDEs — DERIVED PER COMPANY, never a fixed list.** Do
     NOT exclude the same industries every run. Instead **suggest** the
     industries to exclude from the BLEND of:
     1. the **gold / customer set** — industries with **zero (or near-zero)
        customer presence** (read the `industries` block of
        `_raw/_calibration_audit.json`, or reason over the customer list before
        the run), and
     2. **your knowledge of the company** (+ `GetMyCompanyProfile` / its website /
        `parallel-search`) — verticals it obviously can't or won't sell to
        (e.g. a US-only SaaS → exclude Defense, Government, Mining…).
     Present the tailored list, get the user's confirmation, and write the
     **display names** to `universe_filters.exclude_industries`
     (e.g. `["Defense & Space", "Mining & Metals"]`); `merge_data.py` drops those
     rows. NOTE: the endpoint can't filter industries in the rank query, so
     excluded-industry orgs are enriched then dropped (a small credit cost) —
     alternatively, lean on the **auto-applied industry penalties** (Step 4a) to
     sink them instead of excluding, and tell the user which you chose.
     `professional_services` is a native org TAG, so the preferred way to
     exclude it is via `hard_exclude_tags` (free, rank-time); the legacy
     `exclude_professional_services_industry: true` switch still works
     (tag-based, applied at merge).

   **Free preview (optional).** Before spending credits on a 10K pool, you can
   show the user who'd be in it: `fetch_data.py … --whitespace 10000 --rank-only`
   does the FREE rank and writes `_raw/_preselection.json` (candidate names +
   stratum composition), no enrichment. Eyeball it, adjust the ICP / filters,
   then run the real fetch.

   **4.3 — Other 1P signals to fold in (optional, any mode).** product/PLG usage,
   marketing engagement, meeting activity, third-party intent (one
   `{slug}_{measure}` column each). Run the same source-confirmation flow
   per source before reading.

   The closed-won set (c) drives Step 4(a) tag-lift calibration —
   boost/penalty defaults for the six org-tag attributes (`b2b`, `b2c`,
   `digital_native`, `is_ai_native`, `it_services`, `professional_services`).
   Calibration is purely over the org's Sumble tags (`professional_services`
   is one of them, natively); whole industries are **not** synthesized into
   `industry__<slug>` tags or calibrated. These are **applied by default**
   (written to `tag_multipliers`, not just suggested) — the app opens with
   them active and tunable. The audit lands in
   `_raw/_calibration_audit.json` (`attrs`).

   **Agent's role — blend the gold-lift data with knowledge of the world.**
   The gold set is often small, so don't rely on it alone. Combine the
   `_calibration_audit.json` lifts with what you can learn about the company from
   the **MCP servers + the wider world**:
   - `GetMyCompanyProfile` (already pulled in Q3) and Sumble `GetCompanyProfile`
     — what the company sells and to whom.
   - the company's **website / URL** and **`parallel-search` web_search** — research
     their actual customers, target verticals, and obvious non-buyers.
   - your own **world knowledge** of the business and its industry.

   Use these to propose **industry/attribute boosts or penalties the gold set is
   too small (or too biased) to surface** — e.g. "you clearly don't sell to
   Defense/Government — penalize"; "Fintech is a core vertical they name on their
   site — boost". Where the data and world-knowledge AGREE, apply with
   confidence; where the gold set is thin, lean on world knowledge; where they
   CONFLICT (data says penalize an industry the company actively targets),
   surface the conflict to the user rather than silently trusting the small
   sample. Apply confirmed **org-tag** boosts/penalties to
   `account-scoring-weights.json.tag_multipliers`
   (`{tag: "<attr>", pct, direction}`). Industries are not calibrated as
   tags, so act on industry decisions via `universe_filters.exclude_industries`
   (drop them) instead — `professional_services` needs no special handling:
   it's a native org tag, calibrated and excludable like any other tag.

   **Whitespace hard-exclude recommendations (modes B/C).** Suggest excludes
   **per company, never a fixed list** — see Q4.2's "Universe filters" for the
   full mechanics. In short: org-type tags (`org_type_*`, `it_services`) go in
   `hard_exclude_tags` (cheap, rank-time) — and **always ask the PE-firm
   question** (`is_private_equity_firm`, see Q4.2) — while **industries are
   DERIVED** from
   the gold-lift audit (zero/near-zero-customer industries) + world/MCP knowledge
   of the company and written to `universe_filters.exclude_industries` (display
   names), confirmed with the user. Industry excludes drop post-fetch (no rank
   filter), so either accept the small credit cost or lean on the auto-applied
   industry penalties — tell the user which you did.

**Per-tag multiplier widget** is in the template (up/down-weight any tag
   at scoring time) — surface it in the app; don't enumerate tags in the
   interview.

### Stage 2 — Fetch data from the unified endpoint

No SQL signal pulls. Every column comes from one REST call,
`POST https://api.sumble.com/v6/organizations` (match + enrich + select). The
`_build/` scripts build the request from `spec.json`, POST it, and merge the
JSON into `data.csv`. Confirm `SUMBLE_API_KEY` is set first.

#### Stage 2a — Resolve ICP slugs/names (the only "ID resolution" step)

Resolve every ICP term to its canonical Sumble slug/name in ONE call to the
lookup helper (it uses the v6 lookup endpoints; needs `SUMBLE_API_KEY`):

```bash
python3 <skill_dir>/template/_build/lookup.py --technologies clay,common-room,zoominfo --projects "generative ai,digital transformation" --titles "Machine Learning,AI Engineer,Revenue Operations"
```

It prints `{technologies, projects, job_functions}`, each item `{input, slug,
name}` (technologies also list their `categories`). Use:
- **Technologies** → `slug`. Keep the user's input string + resolved slug; show
  both back before fetching. (`SearchTechnologies` is still handy for *fuzzy
  discovery* when you don't yet have a term.)
- **Job functions** → the endpoint's `job_function` term is the **display
  `name`** (e.g. `Revenue Operations`, `Sales`). `--titles` maps each
  job-function name to its canonical function.
- **Projects** → `slug`.

**Parent / aggregate personas.** A persona `name` may be a *parent* job function
(e.g. `Sales` over its SDR / AE children, or `Sales, Marketing, Customer Support
& Business Development` over Sales + Marketing). The `/v6/organizations` endpoint
**aggregates the whole subtree** — `people_count`, growth, and concentration for
a parent return the summed figures across every descendant function — and
`lookup.py` resolves a parent term straight to its node, so a parent persona
needs **no** `kind: "category"` flag (unlike techs).

`GetMyCompanyProfile` still pre-fills the ICP; `lookup.py` just canonicalises
the names. The only remaining `RunSqlQuery` is the tech-category roll-up below.

##### Roll individual techs up into predefined categories

**This procedure is invoked during Q3 (ICP confirmation), before the user
confirms — see Stage 1 Q3. It lives here for the mechanics; by Stage 2a the
roll-up is already confirmed and you only persist it to `spec.json`. Re-run it
here only if the ICP techs changed after Q3.**

Before finalizing the tech list, check whether groups of the ICP techs are
better expressed as a single **predefined Sumble technology category** (one
deduped `team_count` per category, `kind: "category"` in `spec.techs`). Fewer,
less-sparse signals that match how Sumble already groups the stack — e.g. AWS
Redshift + BigQuery + Snowflake → the **Cloud Data Warehouse** category.

**A category signal counts the WHOLE category, not just the absorbed ICP
techs.** When you adopt `{"slug": <cat>, "kind": "category"}`, the enrichment
(`technology_category` + `granularity: aggregate`) counts teams using ANY
technology in that predefined Sumble category — including techs that were never
in the ICP. This is the tradeoff `icp_coverage_pct` quantifies (below): it is
the share of the category's signal that comes from the ICP techs, so
`100% − coverage` is how much extra, non-ICP breadth you take on by rolling up.
Make this explicit to the user at Q3 confirmation, and prefer individual techs
when coverage is low (the category would mostly measure things outside the ICP).

Run ONE `RunSqlQuery` with the resolved ICP tech slugs filled into `icp`:

```sql
WITH icp(tech_slug) AS (VALUES ('aws-redshift'),('bigquery'),('snowflake') /* … */)
SELECT tc.slug AS category, tc.name,
  ROUND(100.0 * SUM(t.total_mentions)
        FILTER (WHERE tc.tech_slug IN (SELECT tech_slug FROM icp))
        / NULLIF(SUM(t.total_mentions), 0), 1) AS icp_coverage_pct,
  STRING_AGG(CASE WHEN tc.tech_slug IN (SELECT tech_slug FROM icp)
                  THEN tc.tech_slug END, ', ') AS icp_techs_in_cat
FROM technology_categories tc
JOIN technologies t ON t.slug = tc.tech_slug
GROUP BY 1, 2
HAVING SUM(t.total_mentions)
       FILTER (WHERE tc.tech_slug IN (SELECT tech_slug FROM icp)) > 0
   AND icp_coverage_pct >= 2.0
ORDER BY icp_coverage_pct DESC;
```

`icp_coverage_pct` = share of that category's total job-post mentions accounted
for by the ICP's own techs. **High coverage = the category is a faithful proxy**
(rolling them up barely broadens the signal); low coverage = the category is far
broader than the ICP, so prefer the individual techs. Apply the rules:
- **Drop any category with `icp_coverage_pct < 2%`** (`HAVING` already does this).
- Techs sit in **overlapping** categories. Walk categories **highest coverage
  first**; let each absorb its ICP techs not already taken by a higher-coverage
  category (no double-counting).
- **Suggest a category** (replace its absorbed individual techs with one
  `{"slug": <cat>, "kind": "category"}` entry) only when it absorbs **≥2** ICP
  techs. Keep unabsorbed techs as individual `{"slug": …}` entries.
- Present the proposed rollups as part of the Q3 ICP confirmation (category,
  coverage%, the techs it absorbs) and loop on the user's edits — the user
  confirms categories, not the raw pre-rollup techs.

Validate each suggested category slug exists in `technology_categories`. The
pipeline handles `kind: "category"` end to end — the endpoint enrichment
(`technology_category` + `granularity: aggregate`), the whitespace ranking
(`technology_category IN`), the score signal, and `score_accounts.py`.

Write **`_raw/spec.json`** (schema: `template/_build/README.md`). Personas carry
`{slug, name, tier, label}` (`name` is the endpoint term), techs
`{slug, label, tier[, kind:"category"]}`, projects `{slug,…}`. Show the resolved
set back to the user before fetching.

#### Stage 2b — Write the input list

Both `sample.csv` and `crm.csv` are optional; write whichever the objective
needs. `sample.csv` is the **scored** sample; `crm.csv` is the exclusion list.

- **`_raw/sample.csv`** (`crm_account_id,name,domain,is_gold,is_owned`) — the
  scored sample. `merge_data.py` derives `account_category` from
  `is_gold`/`is_owned` (customer > allocated > unallocated).
  - **Score / Both (A/C):** the scored CRM set sized + composed per Q4.1
    (everything if ≤5K; otherwise the user's choice — all / allocated / subset /
    stratified sample). `is_gold=1` closed-won, `is_owned=1` rep-allocated.
  - **Whitespace-only (B):** just the closed-won customers (`is_gold=1`), for
    calibration + eval. Omit entirely if they have no closed-won list.
- **`_raw/crm.csv`** (`name,domain`) — the **whole** CRM universe (a), written
  in modes B/C to exclude owned org_ids from the whitespace pool. Optional even
  in B: without it `--whitespace` ranks Sumble's universe with nothing excluded.
- **No lists at all:** skip both — Stage 2c runs `--mode filter` (the endpoint
  ranks Sumble's universe by an ICP advanced query). Put any audience filters in
  `spec.json.universe_filters`.

The endpoint matches by name/url — **no separate `MatchOrganizations` step**.

#### Stage 2c — Fetch + merge

Run each as ONE command with absolute paths — no `cd`, no chaining (see
Shell-command discipline):

```bash
# Score CRM (A):
python3 <skill_dir>/template/_build/fetch_data.py --raw <output_root>/_raw
# Both — score CRM + N net-new whitespace candidates (CRM org_ids excluded) (C):
python3 <skill_dir>/template/_build/fetch_data.py --raw <output_root>/_raw --whitespace 10000
# Whitespace-only (B) — sample.csv holds just customers (or is absent):
python3 <skill_dir>/template/_build/fetch_data.py --raw <output_root>/_raw --whitespace 10000
# No lists — rank Sumble's universe by ICP:
python3 <skill_dir>/template/_build/fetch_data.py --raw <output_root>/_raw --mode filter --pool 1000
# then, all paths:
python3 <skill_dir>/template/_build/merge_data.py --raw <output_root>/_raw
```

`fetch_data.py` POSTs to `/v6/organizations` in ≤250-org batches (or paginated
`filter` pages), saving `_raw/responses/resp_*.json` and a per-org
`_raw/fetch_index.json` carrying `account_category`; with `--whitespace` it also
resolves `crm.csv` → `crm_matches.json` and appends enriched whitespace
candidates. `merge_data.py` parses them into `data.csv` (`account_category` +
`is_icp_gold` set) + `_raw/_calibration_audit.json` (tag-lift, auto-computed).
Same `spec.json` + same responses → byte-identical output; policy constants
live in the scripts.

**Credit cost** ≈ `(1 + paid-attributes + Σ entity-metrics)` per matched org
(~16 for a typical ICP). Surface the estimate before running a large sample.

**Timing** — enrichment runs as blocking ≤250-org POST batches, so wall-clock
scales with the org count. Budget a **broad ~1–2 minutes per 1,000 enriched
orgs** (a typical CRM + 10k-whitespace pull is ~10–20 minutes). **Give the user
this rough time estimate alongside the credit estimate before any bulk
enrichment run**, so a multi-minute fetch isn't a surprise — and run it in the
background, surfacing progress between stages rather than blocking.

> If the key isn't set yet, run `! python3 <skill_dir>/template/_build/set_api_key.py`
> (no Python? `! sh <skill_dir>/template/_build/set_api_key.sh` does the same)
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
python3 <skill_dir>/template/_build/build_weights.py --raw <output_root>/_raw
python3 <skill_dir>/template/_build/fit_weights.py --raw <output_root>/_raw
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
python3 app.py
# open http://localhost:8001 in your browser
```

No `pip install`, no virtualenv, no extra setup — `app.py` is stdlib-only
and runs on any Python 3.10+. Override the port via `python3 app.py 9001`
or `PORT=9001 python3 app.py`.

To score a larger list once weights are tuned, hand
`account-scoring-weights.json` to the separate scoring skill.

---

### Stage 5 — Whitespace filtering (optional; ALWAYS offer it after handover)

**Right after printing the Stage 4 run instructions (modes B/C only — skip when
there is no whitespace), follow up with ONE question about filtering the
whitespace down.** Lead by encouraging the user to LOOK FIRST: open the app,
eyeball the top whitespace (filter chips → Whitespace), and only then decide
whether a filter is needed — the ranked list is often good enough as-is, and
seeing it tells them WHICH failure mode to filter (wrong industry? too small?
services shops?). Offer three paths:

1. **Look first (recommended default)** — revisit filtering after they've
   browsed the sheet; remind them it's available any time.
2. **Criteria filter (free, instant)** — rules over columns already in
   `data.csv` (employee count, HQ country, industry, tags, any signal). Write a
   rules JSON and run `--mode criteria`. Good for crisp cuts the data already
   expresses.
3. **LLM / web-research filter** — one call per whitespace row answering "does
   this company fit the ICP?" against a ~200-word ICP prompt. Output per row:
   boolean + one-sentence reason.

The LLM path is **provider-agnostic** — `template/_build/filter_whitespace.py`
takes `--provider anthropic | openai | gemini | parallel | exa`, each behind the
same interface (the user brings their OWN API key for whichever they have):

| Provider | Default engine | ~cost / 1K rows | Notes |
|---|---|---|---|
| `anthropic` | claude-sonnet-4-6 + web search | ~$35 | $10/1K searches + tokens |
| `openai` | gpt-5-mini + web_search | ~$17 | $10/1K calls + tokens |
| `gemini` | gemini-2.5-flash + grounding | ~$38 | 1,500 grounded/day free, then $35/1K; Google ToS limits storing grounded output |
| `parallel` | Task API `base` processor | ~$10 | research + structured output in one call; `lite`/`core` swap quality/cost |
| `exa` | /answer | ~$5 | cheapest; answer quality below the LLM+search options |

Mechanics (the script handles all of it):
- Targets `account_category == "whitespace"` (NEW accounts) by default, ordered
  by current rank — `whitespace_subsidiary` rows (parent already in the CRM) are
  land-and-expand, not net-new, so postprocessing spend skips them unless
  `--include-subsidiaries` is passed. **Recommend `--top 2000`** (or the user's
  working depth) — filtering the tail of 19K rows is wasted spend.
- Keys (portable — assume nothing about the user's machine). Resolution
  order: `--api-key` → `--key-cmd "<command>"` (stdout is the key; works with
  any secret manager: `gcloud secrets versions access`, `op read`,
  `aws secretsmanager get-secret-value`, `pass show`) → the provider's
  standard env var → `--env-file` → `~/.config/sumble/<provider>_api_key`.
  **Default flow for users without a secret manager:** have them run
  `python3 <skill_dir>/template/_build/filter_whitespace.py --provider <p>
  --set-key` ONCE in their terminal — hidden input (getpass), saved chmod 600,
  found automatically on every later run. Never ask the user to paste a key
  into chat. If no key resolves, the script itself prints where to get one
  and the `--set-key` one-liner.
- `--estimate-only` prints cost/time; the run confirms before spending unless
  `--yes`. Surface the estimate to the user BEFORE running.
- Checkpointed to `_raw/ws_filter_results.jsonl` — interrupt-safe, re-run
  resumes, errors retry on re-run.
- Output: `ws_fit` / `ws_fit_reason` / `ws_filter_provider` columns in
  `data.csv` + score.csv (rows are FLAGGED in the data, never dropped), plus
  `llm_fit` / `llm_unfit` appended to `tags`. The app reacts automatically
  once classified rows exist:
  - **The Whitespace chip splits into THREE chips** — "WS · unprocessed"
    (whitespace rows the filter never judged, e.g. below the --top depth; ON
    by default), "WS · ICP fit" (ON by default, green) and "WS · not a fit"
    (OFF by default, red) — so after the filter runs the sheet opens
    PRE-PRUNED: rows the LLM judged not-a-fit are hidden until that chip is
    toggled on. The three are ordinary category chips (same multi-select
    mechanics, counts, and "All" reset); CRM categories are untouched.
  - **Breakdown verdict box** — clicking a classified row shows
    "✓ ICP fit / ✗ Not an ICP fit", the provider, and the model's
    one-sentence reason, so a rep sees WHY.
  Restart `app.py` to pick up new columns.
- **The fit definition is the USER'S, not yours — never run the LLM filter on
  a prompt the user hasn't approved.** Mandatory sequence before any paid run:
  1. **Ask the user, in their own words:** "What makes a company a clear FIT
     for this filter, and what makes one a clear NON-fit?" (one question; give
     2-3 example criteria from their spec as a starting point).
  2. **Draft** the ~200-word prompt from their answer + the spec (what the
     company sells, explicit fit rules, explicit non-fit rules) and write it
     to `_raw/ws_filter_prompt.txt`.
  3. **Print the ENTIRE prompt verbatim in the message** and get an explicit
     yes/edit (the Stage 1 Confirmation rule applies here too — never
     summarize it or hide it behind "as drafted"). Loop on edits.
  4. Only then show the cost/time estimate and run.
  The script records a hash of the prompt next to the checkpoint: if the
  prompt later changes, old verdicts are auto-archived
  (`ws_filter_results.jsonl.stale`) and the run reclassifies from scratch —
  verdicts from two different fit definitions never mix.

```bash
# estimate, then run (example: OpenAI on the top 2,000 whitespace rows)
python3 <skill_dir>/template/_build/filter_whitespace.py --dir <output_root> \
  --provider openai --top 2000 --prompt-file <output_root>/_raw/ws_filter_prompt.txt \
  --estimate-only
python3 <skill_dir>/template/_build/filter_whitespace.py --dir <output_root> \
  --provider openai --top 2000 --prompt-file <output_root>/_raw/ws_filter_prompt.txt --yes

# criteria mode (free): rules JSON of {column, op, value[, label]}
python3 <skill_dir>/template/_build/filter_whitespace.py --dir <output_root> \
  --mode criteria --rules <output_root>/_raw/ws_filter_rules.json
```

Quality guidance when the user asks which provider: evidence beats model — the
script already packs the row's firmographics (name, domain, industry, size,
tags) into the prompt and tells the model to trust the DOMAIN (avoids
same-name-company errors). `anthropic`/`openai` give the best
search-and-reason quality; `parallel` is the best no-LLM-key option
(structured research API); `gemini` is cheapest at scale if paced under the
free grounding tier and its storage ToS is acceptable; `exa` is the budget
sanity-check. Calibrate before trusting: if gold/customer rows exist, spot-run
the filter on ~20 of them — they should nearly all come back `fit`.

---


