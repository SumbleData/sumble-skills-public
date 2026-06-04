---
name: people-scoring
description: "Build a people-scoring web app powered by Sumble data and optional first-party data. Interviews the user about their ICP (job functions + skills via GetMyCompanyProfile), then builds a SMALL calibration sample from ~5 user-named companies so the app is ready in minutes. Generates a self-contained, zero-dependency Python + HTML/JS app at people_scoring/<company>/ with real-time slider re-weighting, plus a production score_leads.py that applies the calibrated weights to an entire enriched CRM."
---

# People Scoring

Two deliverables from one run:

1. **A calibration web app** — a zero-dependency Python + HTML/JS app
   that ranks people and lets the user tune the scoring factors (Job
   Function, Seniority, Skills, plus any connected 1P signals) via
   sliders in real time. It runs over a **small calibration sample**
   built from ~5 companies the user names, so the whole pipeline
   finishes in minutes (not the 30+ it takes to enrich a full CRM).
   Tuning ends with the Save button writing `people-scoring-weights.json`.

2. **A production scorer** — `score_leads.py`, a stdlib script that
   reads `people-scoring-weights.json` and scores an entire enriched
   leads/CRM file with the calibrated weights. You calibrate on 5
   companies; you apply to everything.

Data comes from Sumble (via the Sumble MCP) and, optionally, the user's
own first-party data.

Follow the stages exactly — input and output should be near-deterministic
across runs.

Trigger on `/people-scoring`.

## Why 5 companies for calibration

Resolving and enriching a full CRM (tens of thousands of people) means
~30 MCP batches and 30+ minutes, and it kept losing staging files to
worktree cleanup. None of that is needed to *calibrate weights* — the
user just needs enough variety to see the score behave and judge the
slider trade-offs. ~5 companies (a few hundred to low-thousands of
people) gives that, builds in minutes, and keeps the browser snappy.
The full-CRM scoring happens later, offline, via `score_leads.py`.

## Required tools

- **Sumble MCP** — `GetMyCompanyProfile`, `SearchTechnologies`,
  `RunSqlQuery`, `MatchOrganizations`, `ListTables`. If unavailable,
  stop and tell the user to install it: https://docs.sumble.com/api/mcp.
- **`organizations-duckdb` MCP** — `query`. Used for matched skills
  (Template P2). The Sumble MCP's curated DuckDB has **no** people-skill
  table; `organizations-duckdb` has `people_technologies_by_person_id`
  (columns `person_id`, `technology_id`) plus `technologies`
  (`id`, `slug`). NOTE: there is no `sumble-data-postgres` MCP and no
  `pdl_people_technologies` table — use `organizations-duckdb`. It also
  caps results at 1000 rows.
- **`users-db-postgres` MCP** (`execute_sql`) — only when the 1P
  source / account scores / gold set live in the Sumble users DB. See
  the disconnect caveats below.
- **First-party MCPs (optional)** — Salesforce, HubSpot, warehouse
  (Snowflake/BigQuery/Databricks/Postgres), Sheets/Drive. CSV path is
  always a valid fallback.

> **Sumble MCP schema note:** `RunSqlQuery` exposes a curated DuckDB,
> NOT internal AlloyDB. Run `ListTables` once at the start of Stage 2
> to confirm. Stable tables: `people_info` (denormalises `job_level`,
> `job_level_rank`, `country_id` — skip the `job_levels` join),
> `organizations`, `job_functions`, `job_levels`, `countries`.
> `people_info.linkedin_url` is canonical
> `https://www.linkedin.com/in/<slug>` — join 1P LinkedIn URLs to it by
> equality (see Stage 2c), never `regexp_extract` over the whole table.

## Staging directory — use `$TMPDIR`, NOT the repo

**Stage the entire pipeline under `$TMPDIR/people_scoring_<company>/`**
(staging CSVs, batch SQL, helper `.py` scripts, intermediate dumps).
Subagents — **even foreground ones with no `run_in_background`** — can
run in isolated git worktrees whose cleanup wipes repo-relative paths
when they finish. This has destroyed a full `tmp/.../\_raw/` directory
mid-run (36K-row 1P universe + 37 resolved batches, gone in one sweep,
only files written *after the last subagent returned* survived).
Anything under the repo (`tmp/`, `people_scoring/`, `account_scoring/`)
is at risk across every `Agent` dispatch. `$TMPDIR` is outside the repo
and survives. Only write the final deliverables (the app folder with
`data.csv` / `config.json`) into the repo at the very end, after all
subagent work is complete. MCP tool-result auto-saves under
`~/.claude/projects/.../tool-results/` also survive (outside the
worktree) and are your recovery net — but a subagent's dumps land in
that subagent's own session dir, so fire recovery-critical chunk calls
from the main agent when practical.

## Shell discipline

Every shell command with syntax Claude Code can't statically analyse
(loops, command substitution, pipes, redirects, heredocs, globs in
argv) pops a permission prompt and adds friction across a 30-minute
run. **Use Read/Glob/Grep, Write, and single Python invocations
instead.** The only Bash this skill needs is the `cp` + `python app.py`
in Stage 3 — everything else goes through a Claude Code tool or one
inline Python call.

**Never use heredocs in Bash.** Even `python3 - <<'PY' ... PY` trips a
"brace with quote (expansion obfuscation)" permission prompt every
time. The non-negotiable pattern is: `Write` a helper `.py` file under
`./tmp/people_scoring/<company>/_raw/` (or `$TMPDIR`), then
`python3 <path>.py`. One-liner `python3 -c "..."` is fine **only** if
the snippet has no `{`/`}` literals and no f-strings — otherwise write a
file. This shows up most often when parsing MCP tool-result dumps; just
default to writing a helper file every time.

**Postgres MCP tool-result files are Python-repr strings, not JSON —
even when your SQL uses `to_jsonb`.** The MCP saves big results to
`tool-results/...txt` files. The outer envelope is JSON
(`{"result":[{"type":"text","text":"..."}]}`), but the inner `text` is
a Python `repr` of `list[dict]` — including `datetime.datetime(...)`
and `Decimal('...')` Call literals. `to_jsonb(t) AS r` doesn't avoid
this; you just get `[{'r': {...}}, ...]` in Python-repr form and have
to unwrap the `r` wrapper. `ast.literal_eval` chokes on the
Call literals; use a controlled-namespace `eval`:

```python
import json, datetime, decimal
def load_pg_dump(path):
    data = json.load(open(path))
    text = data['result'][0]['text']
    try:
        rows = json.loads(text)  # small responses come back as inline JSON
    except Exception:
        ns = {'datetime': datetime, 'Decimal': decimal.Decimal,
              '__builtins__': {'None': None, 'True': True, 'False': False}}
        rows = eval(text, ns)
    if rows and isinstance(rows[0], dict) and set(rows[0].keys()) == {'r'}:
        rows = [r['r'] for r in rows]  # unwrap to_jsonb's `r`
    return rows
```

Cast non-string columns to `text` in the SQL (`last_seen_at::text`)
so the eval'd payload uses plain strings — saves a normalization pass.

Sanity-check off the in-memory pandas `df`, not by shell-looping over
`_raw/` chunk files.

**Postgres MCP disconnects mid-query on big results.** Symptom:
`MCP error -32000: Connection closed`. The MCP returns to "no such tool"
state until the user re-runs `/mcp` to reconnect. Triggered by queries
that materialise too much before streaming (heavy `GROUP BY` + `ORDER
BY` over the union, multi-table joins on 30K+ rows). Mitigations:

- Keep each chunk under ~20K rows. `LIMIT 18000 ORDER BY id` works.
- Avoid `ORDER BY` on big unions — sort client-side after the dump.
- Split unions: pull users + meetings as separate queries, merge in
  pandas.
- When it does disconnect, ask the user to `/mcp` rather than retrying;
  the connection is permanently dead for this session until they reload.

## Output

```
people_scoring/<company>/
  app.py                      stdlib http.server, unchanged from template/
  config.json                 weights, JF ranges, 1P signal mappings
  data.csv                    calibration sample — people at ~5 named companies
  data.calibration-info.json  the 5 companies + per-company people counts
  score_leads.py              production scorer (unchanged from template/)
  static/                     UI: account picker, sliders, tables, breakdown
  README.md
  .gitignore
  people-scoring-weights.json self-describing scoring spec (written by Save button)
```

`data.csv` schema: see `template/SCHEMA.md`. `score_leads.py` consumes
the same schema for the full CRM in production (Stage 5).

> **Zero-dependency rule.** Stock Python 3.10+, stdlib only (`csv`,
> `json`, `http.server`). No `pip install`, no virtualenv, no third-party
> imports in `app.py`, and no `requirements.txt` in the generated folder.

## Scoring

```
seniority_frac  = job_level_rank / max_job_level_rank
jf_score        = jf_range[jf].min + (jf_range[jf].max - jf_range[jf].min) * seniority_frac
seniority_score = seniority_frac
skill_score     = min(skill_count, skill_cap) / skill_cap   # default cap = 5
1p_score        = <signal>_norm   # pre-normalised in Stage 2d

total = w_jf*jf_score + w_seniority*seniority_score + w_skills*skill_score
      + Σ (w_signal * 1p_score)
```

Weights sum to 100%.

**Defaults — Sumble-only:** `jf=38`, `seniority=46`, `skills=16`
(mirrors Sumble's internal weights without the Account factor).

**Defaults — with 1P:** the three Sumble factors keep their 38/46/16
ratio scaled to 75% of the total; the remaining 25% is split evenly
across however many 1P signals are connected.

If the user has no ICP skills, drop `w_skills` and re-normalise.

**1P normalisation (build-time, p99 exponential saturation):**
```
x    = ln(1 + max(raw, 0))
p99  = 99th percentile of x over rows where raw > 0
norm = clamp((1 - exp(-x / p99)) / (1 - exp(-1)), 0, 1)
```
Build-time (not client-side) keeps slider re-weighting instant.

---

## Pipeline

Execute in order. Surface progress between stages.

### Stage 1 — Interview

Follow this script exactly. **One question, not three** for the ICP step.

1. **Company name + URL.** Pre-fill if you recognise it; ask to confirm.

2. **Confirm ICP via `GetMyCompanyProfile`.** Call it on the URL. If it
   succeeds, do **not** trim the returned job functions or technologies.
   If it fails, propose via LLM, then snap to Sumble slugs via
   `SearchTechnologies` (skills) and `RunSqlQuery` on `job_functions`
   (JFs). Render as one summary block and ask one yes/edit question:

   ```
   Proposed ICP for <customer>:
     • Job functions: Sales, Revenue Operations, Marketing
     • Skills: clay, common-room, hg-insights, zoominfo, outbound, abm

   Is this ICP OK? Reply "yes" to accept, or describe what to change
   (e.g. "drop marketing, add SDR").
   ```

   Loop on edits until accepted.

3. **People scope.** Pick one path (this decides where calibration
   people *come from*; Step 3.5 restricts them to ~5 companies):

   - **a. 1P only** — score the people already in the user's own
     systems (CRM contacts, product userbase, marketing audience). No
     Sumble whitespace; the candidate set is exactly what they bring.
   - **b. 1P + Sumble whitespace** — score the people in their 1P
     systems AND identify new "whitespace" people from the Sumble
     corpus at the same accounts.
   - **c. Sumble universe only** — score people pulled from Sumble for
     a target account list, without touching any internal system.

   Branch on the answer:

   **If a or b** 
    — ask where to find 1P people from. Enumerate
     candidate MCP tables / CSVs (CRM contacts, product users,
     marketing audience), propose one, confirm, sample-read `LIMIT 10`
     to verify join keys, then pull. Also ask whether they have
     internal 1P data to feed into the score: product engagement /
     PLG signals, marketing touches, third-party intent on
     individuals. Each becomes one weighted factor; resolved in
     Stage 2d.
    - **Join key for 1P data:** LinkedIn slug (preferred); fallback to
    reverse enrichment endpoint if they are you email address but no linkedin slug. 

   **If b or c** 
    — ask **seniority floor** for the Sumble-side
     pull. Free-form, default **Head and above**. Common alternatives:
     "all levels", "Manager and above", "Director and above", "VP and
     above". Resolved to `min_job_level_rank` in Stage 2a.

   **Scope of the seniority floor by path:**
   - **a** (1P only): floor is **not applied** — keep every 1P row.
     ICP JFs and skills are still resolved in Stage 2a because the
     score uses them, but they are *scoring inputs*, not filters.
   - **b** (1P + Sumble whitespace): keep **every** 1P row regardless
     of seniority; apply the floor **only** to the Sumble whitespace
     pull. The two sets are unioned in Stage 2d.
   - **c** (Sumble universe only): floor applies to the whole pull.

3.5. **Calibration companies (~5).** Ask the user to name **about 5
   companies** to build the calibration sample from. This is the single
   biggest lever on runtime — only these companies' people get enriched
   and loaded into the app.

   ```
   Which ~5 companies should I calibrate on? Name them (domains or
   names). Pick a spread you know well — ideally a mix of strong-fit
   and weak-fit accounts, and a couple of different sizes — so the
   sliders have variety to work against. Reply "you pick" and I'll
   choose a representative 5 from your data.
   ```

   - If the user says "you pick": for path a/b choose 5 employers from
     the 1P set spanning customer / non-customer and size; for path c
     choose 5 from the target account list across account-score tiers.
   - Resolve the 5 to Sumble `org_id`s with `MatchOrganizations`
     (Stage 2b). These org_ids are the **only** accounts pulled/enriched.
   - Default 5; accept 3–10 if the user wants. More than ~10 starts to
     reintroduce the slowness this avoids — push back gently above 10.

4. **Account score / ranking?** Yes / default-no. Two sub-questions:
   - Do they want account score factored into the people score?
   - If yes, do they have account scores internally that should be
     joined (e.g. can point to MCP or CSV)?

  If people can't be joined to internal accounts you can join via Sumble using the Sumble org id attached to a Sumble person id (found in section 3) and match the account score to Sumble org id via `MatchOrganizations`

5. **Gold set (evaluation only).** Yes / default-no.

   Ask whether they have a list of people who turned out to be amazing
   leads — CRM champions, contacts on closed-won deals — that can be
   used to evaluate how well the score surfaces good people. Matched
   rows get `is_icp_gold = 1`. Drives the Evaluation tab.

   MCP / CSV / skip. For MCP, enumerate objects, propose a table,
   confirm, sample-read `LIMIT 10`. Same join-key rule as step 3.

Show a single summary back before running expensive queries.

### Stage 2 — Build & run the queries

#### 2a — Resolve ICP IDs

**Job functions** — expand seeds to the **full descendant subtree**.
Most people are tagged with leaf JFs (e.g. `account-executive`), not
parents (`sales`). A naïve parent filter returns nothing. This is the
most common cause of "a handful of people per customer". Do not skip.

```sql
WITH RECURSIVE seeds AS (
  SELECT id, name, slug, parent_id
  FROM job_functions
  WHERE LOWER(slug) IN ('sales','revenue-operations','marketing')
     OR LOWER(name) IN ('sales','revenue operations','marketing')
),
expanded AS (
  SELECT * FROM seeds
  UNION ALL
  SELECT jf.id, jf.name, jf.slug, jf.parent_id
  FROM job_functions jf JOIN expanded e ON jf.parent_id = e.id
)
SELECT DISTINCT id, name, slug FROM expanded;
```

Surface the count back ("47 leaf JFs").

**Job-level rank floor** — resolve to a numeric `level_rank`:
```sql
SELECT id, name, level_rank
FROM job_levels
WHERE LOWER(name) IN ('head','director','vp','svp','cxo','manager','senior manager')
ORDER BY level_rank;
```
"all levels" → `min_job_level_rank = 0`. Show the resolved floor back.

**Skills** — call `SearchTechnologies` once per term, **all in one
message as parallel tool uses**. Keep both the user's input string and
the resolved slug; show both back before running the pull.

#### 2b — Match the ~5 calibration companies → Sumble org_ids

You only need org_ids for the **5 calibration companies** from Step 3.5
— this is a single `MatchOrganizations` call (≤10 rows), not a CRM-wide
match. Pass each company as `{name, url}`.

Use `MatchOrganizations`. **Never substitute a `WHERE url/domain = ANY(...)`
query** — it drops subdomain/apex/holding-company variants.

- Response shape: `{results: [{input: {url, name, location},
  match: {id, slug, name, domain}}]}` — no `confidence` field; the
  top-level `matched_count` / `total` give the hit rate.
- Save `input_url, org_id, org_name, org_slug, org_domain` per matched
  row. Surface the 5 resolved orgs back to the user to confirm before
  pulling people ("matched: Datadog → datadog [id 2611], …").
- If a company fails to match, tell the user and ask for an alternative
  (or proceed with 4).

Account-score join is on **domain** (`account_scores.domain`), done in
Stage 2d — independent of this org match.

#### 2c — Pull / enrich people at the 5 calibration companies

Everything here is scoped to the **5 org_ids** from Stage 2b, so it's
small — typically 1–3 `RunSqlQuery` calls total, no subagents needed.

**Path c (Sumble universe):** pull people directly with P1, filtered to
the 5 org_ids + ICP JFs + seniority floor.

**Path a / b (1P):** filter the 1P set to people whose employer is one
of the 5 companies, then resolve those rows to `person_id` and enrich.
For path a there is no seniority floor. With only 5 companies the 1P
subset is small (hundreds), so slug resolution is one query.

**Resolving 1P LinkedIn URLs → person_id (equality join, NOT regexp).**
`people_info.linkedin_url` is canonical `https://www.linkedin.com/in/<slug>`.
Build the full URL on your side and join by equality — never
`regexp_extract` over `people_info` (it scans tens of millions of rows
and times out). One query covers all 5 companies' 1P rows:
```sql
WITH input AS (SELECT * FROM (VALUES
  ('https://www.linkedin.com/in/slug1'),
  ('https://www.linkedin.com/in/slug2'), ...) v(url))
SELECT i.url, pi.person_id, pi.name, pi.current_title, pi.linkedin_url,
       pi.location, c.code AS country_code,
       pi.organization_id AS org_id, o.name AS org_name, o.slug AS org_slug,
       pi.job_function_id, jf.slug AS job_function_slug,
       jf.name AS job_function_name, pi.job_level, pi.job_level_rank
FROM input i
JOIN people_info pi ON LOWER(pi.linkedin_url) = i.url
LEFT JOIN organizations o ON o.id = pi.organization_id
LEFT JOIN job_functions jf ON jf.id = pi.job_function_id
LEFT JOIN countries c ON c.id = pi.country_id;
```
Derive `sumble_url` client-side: `https://sumble.com/people/<slug>`.

**Template P1 — Sumble-side people pull** (`RunSqlQuery`, path b/c):
```sql
SELECT pi.person_id, pi.name, pi.current_title, pi.linkedin_url,
       pi.location, c.code AS country_code,
       o.id AS org_id, o.name AS org_name, o.slug AS org_slug,
       pi.job_function_id, jf.slug AS job_function_slug,
       jf.name AS job_function_name, pi.job_level, pi.job_level_rank
FROM people_info pi
JOIN organizations o      ON o.id = pi.organization_id
LEFT JOIN job_functions jf ON jf.id = pi.job_function_id
LEFT JOIN countries     c  ON c.id  = pi.country_id
WHERE pi.organization_id IN (<5 calibration org_ids>)
  AND pi.job_function_id IN (<icp_job_function_ids>)
  AND COALESCE(pi.job_level_rank, 0) >= <min_job_level_rank>
  AND pi.linkedin_url IS NOT NULL;
```
`RunSqlQuery` caps at 1000 rows. With 5 companies you may exceed 1000
for very large employers — if a single org returns 1000, page it
(`AND pi.person_id > <last>` ordered by person_id) or tighten the
seniority floor. Prefer firing from the main agent; if you use
subagents, they MUST write to `$TMPDIR` (see Staging directory).

**Template P2 — matched skills per person.** Run via the
**`organizations-duckdb` MCP** (`query`). Resolve the ICP skill slugs to
`technologies.id` first, then:
```sql
SELECT pt.person_id,
       COUNT(DISTINCT t.slug) AS skill_count,
       STRING_AGG(DISTINCT t.slug, ',') AS matched_skills
FROM people_technologies_by_person_id pt
JOIN technologies t ON t.id = pt.technology_id
WHERE pt.technology_id IN (<icp_technology_ids>)
  AND pt.person_id IN (<person_ids_from_P1>)
GROUP BY pt.person_id;
```
Only people WITH an ICP skill come back; everyone else gets
`skill_count = 0`, `matched_skills = ''`. Caps at 1000 rows — with 5
companies you're well under, one call.

**Template P3 — global max job-level rank** (`RunSqlQuery`):
```sql
SELECT MAX(level_rank) AS max_job_level_rank FROM job_levels;
```

**Assembly — inline, no subagent:**
```python
import pandas as pd

df = pd.concat(p1_chunks).merge(pd.concat(p2_chunks), on='person_id', how='left')
df['matched_skills'] = df['matched_skills'].fillna('')
df['skill_count']    = df['skill_count'].fillna(0).astype(int)
df['max_job_level_rank'] = max_job_level_rank

# 1P flags ALWAYS present, default 0; Stage 2d sets them when applicable.
df['is_crm_contact'] = 0
df['is_icp_gold']    = 0

# Skip the write if Step 3 connected any 1P data — Stage 2d writes it then.
df.to_csv('data.csv', index=False)
```

Emit only one-line summaries per batch (`P1 chunk 3/5: 187 rows`).

**Sanity check** (single Python block, off the in-memory `df`): total
people, distinct orgs covered, orgs with zero matches, mean/median
people per covered org. If median < 3 for orgs with 100+ employees,
JF expansion in Stage 2a is the usual culprit — surface it rather than
writing a tiny CSV.

Expected runtime: ~30s for ~10K people across ~500 orgs in parallel.

#### 2d — Join first-party data (skip if none connected and path = c)

The shape of `df` going **into** this stage depends on path:
- **Path a**: `df` = 1P contacts only. Stage 2c was skipped. We need
  to enrich every 1P row with Sumble's `person_id`, `job_function_id`,
  `job_level_rank`, and `skill_count` before scoring.
- **Path b**: `df` = Sumble whitespace pull from Stage 2c. We will
  resolve 1P contacts to `person_id`s, union them in (no seniority
  floor on 1P), dedup on `person_id`, then enrich the now-merged
  frame.
- **Path c**: `df` = Sumble whitespace pull from Stage 2c. Only 1P
  *signals* (not contact lists) get joined, by LinkedIn slug or
  reverse-enriched email.

**Resolving 1P rows to `person_id`** — three-pass waterfall, in order:

1. **LinkedIn slug match (equality join — see Stage 2c).** Build the
   canonical `https://www.linkedin.com/in/<slug>` URL and join by
   equality on `people_info.linkedin_url`. Because the calibration set
   is only ~5 companies' 1P rows (hundreds), this is **one query**, not
   the 28-batch slog a full CRM would need. Never `regexp_extract` over
   `people_info`. Covers the majority of CRM rows that have a
   `linkedin_url`.
2. **Lower-cased name + matched `org_id`.** For rows with no LinkedIn
   URL but a known employer. Use the `org_id` from Stage 2b. Free; low
   precision — surface the match rate so the user can decide whether
   to trust it.
3. **Reverse-enrichment by email** (paid fallback). For rows with an
   email but no LinkedIn URL and no name+org match:
   `POST https://api.sumble.com/v5/people/detail` with
   `{"email": "<addr>"}`, header `Authorization: Bearer
   $SUMBLE_API_KEY`. Returns `linkedin_url` on hit (30 credits per
   call). Then back to pass 1.

   **Always confirm before running pass 3.** Show the count of
   email-only unmatched rows and the credit cost (`N × 30`); proceed
   only on explicit user OK. Batch sequentially; cache by
   lower-cased email so repeats are free.

```python
import re, asyncio, numpy as np

def li_slug(url):
    if not isinstance(url, str): return None
    m = re.search(r'linkedin\.com/in/([^/?#]+)', url.lower())
    return m.group(1) if m else None

def slug_match(one_p_df, url_col, sumble_df):
    one_p_df = one_p_df.copy()
    one_p_df['_slug'] = one_p_df[url_col].map(li_slug)
    keyed = sumble_df[['person_id', '_slug']].dropna(subset=['_slug'])
    return one_p_df.merge(keyed, on='_slug', how='left')

# --- Path a: 1P is the universe; df starts as 1P -----------------
if path == 'a':
    df = one_p_contacts.copy()
    df['_slug'] = df['linkedin_url'].map(li_slug)
    # Sumble-enrich every 1P row: P1 (per matched org_id), P2 (skills),
    # P3 (max_job_level_rank). Same queries as Stage 2c, but the WHERE
    # clause is `linkedin_url IN (...) OR (name = ? AND organization_id
    # = ?)`. Then merge person_id, job_function_id, job_level/rank back.
    df = enrich_with_sumble(df)
    # Email-only rows: ask the user, then call reverse enrichment.
    df = reverse_enrich_unmatched(df, email_col='email')

# --- Path b: union Sumble whitespace + 1P (no seniority floor on 1P) --
if path == 'b':
    # df is the Sumble whitespace pull already.
    one_p_resolved = resolve_to_person_id(one_p_contacts)  # passes 1-3
    one_p_resolved = enrich_with_sumble(one_p_resolved)
    df = pd.concat([df, one_p_resolved]).drop_duplicates(
        subset=['person_id'], keep='first')

# --- Path c: df already from 2c; nothing to merge from 1P contacts ---

# --- Flags (paths a + b only — path c has no 1P contact list) --------
df['is_crm_contact'] = 0
df['is_icp_gold']    = 0
if path in ('a', 'b'):
    crm_ids = set(one_p_contacts_resolved['person_id'].dropna())
    df['is_crm_contact'] = df['person_id'].isin(crm_ids).astype(int)
if gold_contacts is not None:
    gold_resolved = resolve_to_person_id(gold_contacts)
    gold_ids = set(gold_resolved['person_id'].dropna())
    df['is_icp_gold'] = df['person_id'].isin(gold_ids).astype(int)

# --- 1P engagement signals (all paths) --- raw + p99-saturation norm
def p99_norm(raw):
    x = np.log1p(raw.clip(lower=0))
    pos = x[raw > 0]
    p99 = max(np.percentile(pos, 99), 1e-9) if len(pos) else 1e-9
    return ((1 - np.exp(-x / p99)) / (1 - np.exp(-1))).clip(0, 1)

for sig in one_p_signals:
    raw_col, norm_col = f'{sig.key}_raw', f'{sig.key}_norm'
    df[raw_col]  = df['person_id'].map(sig.raw_value_map).fillna(0.0)
    df[norm_col] = p99_norm(df[raw_col])

df.drop(columns=['_slug'], errors='ignore').to_csv('data.csv', index=False)
```

Report:
- Resolve-to-person waterfall hit rates per pass (slug / name+org /
  reverse-enrichment) and the total cost of pass 3.
- `is_crm_contact=1`, `is_icp_gold=1` counts; per-1P-signal non-zero
  rows. A flag count of 0 means matching failed — surface it.
- For path b, how many 1P rows merged in net of dedup against the
  Sumble whitespace pull.

#### 2e — Finalise the calibration `data.csv` (no sampling needed)

The 5-company restriction already keeps the dataset small (hundreds to
a few thousand rows — well within the browser's snappy range), so there
is **no stratified sampling step**. The enriched `df` from Stage 2c/2d
*is* the calibration sample. Just:

1. Add `max_job_level_rank` (from P3) to every row; ensure
   `matched_skills`/`skill_count` filled (0/'' when none) and the
   `is_crm_contact` / `is_icp_gold` flags present (default 0).
2. Join the account score on `domain`
   (`account_scores.domain` → `account_rank`, `account_score`) if
   Stage 1.4 connected one.
3. Write `data.csv` and a small `data.calibration-info.json`:
```python
json.dump({
  'calibration_companies': [
      {'name': o['org_name'], 'domain': o['org_domain'],
       'org_id': o['org_id'], 'people': counts[o['org_id']]}
      for o in calibration_orgs
  ],
  'total_people': len(df),
  'path': path,                       # a / b / c
  'has_account_score': bool(account_join),
  'gold_people': int(df['is_icp_gold'].sum()),
}, open(APP / 'data.calibration-info.json', 'w'), indent=2)
```

**Sanity check** off the in-memory `df`: people per calibration company
(flag any company with 0 — usually a JF-expansion miss in 2a or a bad
org match in 2b), total people, `is_icp_gold` count. Surface a one-line
summary: `5 companies, 1,240 people, 38 gold`.

---

### Stage 3 — Generate the app

```bash
mkdir -p ./people_scoring/<company>
cp -r <skill_dir>/template/. ./people_scoring/<company>/
```

That copies `app.py`, `score_leads.py`, `README.md`, `.gitignore`,
`SCHEMA.md`, and the `static/` directory — all unchanged. Copy
`data.csv` + `data.calibration-info.json` from `$TMPDIR` into the app
folder now (this is the moment to move final deliverables out of
`$TMPDIR` and into the repo). Then **write `config.json`** populating
per-run fields. See `template/config.json` for the full schema;
per-run, set:

- `customer_name`, `score_label`
- `weights` — three entries (`jf`/`seniority`/`skills`) for Sumble-only;
  add one `1p_<key>` entry per connected 1P signal (see Scoring defaults).
- `job_function_ranges` — one entry per leaf JF in the ICP. Use
  `default_jf_range` for any JF you don't have a hand-tuned range for.
- `one_p_signals` — one entry per connected 1P signal (`weight_key`
  must match a `weights` key); empty `[]` for Sumble-only.
- `account_picker.account_rank_column` / `account_score_column` — only
  when Stage 1.4 connected an account score.
- `filters_applied` — informational summary: `seniority_floor_label`,
  `seniority_floor_rank`, `icp_job_function_count`, `icp_skill_count`,
  plus calibration stats (`calibration_companies`, `total_people`,
  `gold_people`). Rendered as a one-line header on the People tab.

**Sumble-only run:** keep the 38/46/16 weights, omit `1p_*` entries,
set `"one_p_signals": []`. Always keep the `flags` block — the
`is_crm_contact` / `is_icp_gold` columns are present in every `data.csv`
(all-zero when unconnected) and the app hides the dependent UI.

App behaviour (tabs, filters, badges, Save button, weights file
overlay) is implemented in the template and documented in
`template/README.md` — don't restate it in the generated README beyond
what the template already covers.

---

### Stage 4 — Calibrate (run instructions)

Print to the user (do **not** try to launch the server inside Claude
Code — let the user start it in a real terminal):

```bash
cd ./people_scoring/<company>
python app.py 8002
# open http://localhost:8002 — tune the sliders, then click Save
```

Tell them the loop: tune sliders → click **Save** (writes
`people-scoring-weights.json`) → that file drives the production scorer
in Stage 5. `data.csv` here is only the 5-company calibration sample;
it is intentionally small.

Security: the generated `README.md` already covers the no-auth warning
and 127.0.0.1-only binding — don't restate it in the chat reply unless
the user is about to expose the port.

---

### Stage 5 — Score the full CRM in production

Once weights are calibrated (`people-scoring-weights.json` saved), the
user scores their **entire** lead/CRM universe with `score_leads.py`:

```bash
python score_leads.py \
  --leads leads_enriched.csv \
  --weights people-scoring-weights.json \
  --out scored_leads.csv
```

`score_leads.py` (shipped in the app folder, stdlib-only) re-implements
the exact app formula and is deterministic — no browser, no row cap.

**Producing `leads_enriched.csv` (the full CRM):** it must carry the
same columns as `data.csv` (`job_function_slug`, `job_level_rank`,
`max_job_level_rank`, `skill_count`, any `*_norm` 1P columns, account
columns if used). Produce it by running the **same Stage 2 enrichment
over the full 1P/CRM universe** — i.e. *without* the 5-company
restriction. That is the slow path (the 28-batch slug resolution +
skill batches); it runs once, offline, and is fine to parallelise
across subagents **as long as every output lands in `$TMPDIR`**. Then
point `--leads` at the assembled enriched CSV.

Offer to build `leads_enriched.csv` for the user when they're ready —
but only after weights are calibrated, so the expensive full-CRM
enrichment happens exactly once, against final weights.
