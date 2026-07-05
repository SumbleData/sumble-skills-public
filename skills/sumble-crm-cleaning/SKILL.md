---
name: sumble-crm-cleaning
description: "Build a CRM-cleaning review web app powered by Sumble data. Finds (1) potential duplicate accounts — CRM accounts that resolve to the SAME Sumble organization (Sumble's matcher is the only duplicate evidence; no domain or name-similarity matching) — and (2) missing or conflicting parent/subsidiary links, by matching every account to Sumble's organization graph via POST /v6/organizations (attributes incl. parent_id/subsidiary_ids — no SQL, no RunSqlQuery). Interviews the user about their CRM source and which checks to run, pulls the account list from internal systems or a CSV, and generates a self-contained, zero-dependency Python + HTML/JS review app at crm_cleaning/<company>/ with accept/reject/skip per finding, survivor selection for merges, and an actions.csv export of every approved CRM change."
---

# CRM Cleaning

This skill produces a zero-dependency Python **review web app** (stdlib
`http.server`) that surfaces two kinds of CRM hygiene problems and lets the
user adjudicate each one:

1. **Potential duplicate accounts** — CRM accounts that resolve to the SAME
   Sumble organization. Sumble's matcher is the only duplicate evidence — no
   domain or name-similarity matching. Each duplicate cluster is tagged with a
   resolution bucket so the reviewer can triage hard cases from easy ones:
   **Multiple owners** (≥2 distinct owners — decide who keeps the account),
   **Split activity** (one owner, CRM footprint spread across >1 record — merge
   so no history is lost), or **Concentrated** (one owner, footprint on a single
   record — keep it, drop the shells). The Duplicates tab splits into three
   **sub-tabs** — one per bucket, hardest first — so each bucket reads as its
   own work queue.
2. **Missing parent/subsidiary links** — accounts whose Sumble parent (or
   grandparent) is *another account in the CRM* but no CRM parent link exists
   (or the CRM's link conflicts with Sumble's hierarchy); plus parent
   companies that aren't in the CRM at all (grouped per missing parent).
   **Private-equity firms are NOT suggested as parents by default** (org tag
   `is_private_equity_firm`): a buyout firm is rarely a sellable parent
   account. Opt in with `"include_pe_parents": true` in `_raw/config.json` —
   PE parents then appear flagged, under a **PE roll-ups sub-tab** of the
   Parents-not-in-CRM tab, separate from the conventional parent/sub
   roll-ups sub-tab.

Every accepted finding lands in **`actions.csv`** — one row per CRM change
(`merge`, `delete`, `set_parent`, `create_parent_and_link`) — the hand-off to
the CRM admin or a dedupe job. For a duplicate cluster the reviewer picks one
record as the primary and, per other record, chooses **merge into primary**
(default) or **delete**.

Follow the stages closely — input (interview) and output should be consistent
between runs, more deterministic than most skills. All detection logic is
policy constants in `template/_build/` (same inputs → byte-identical
findings); the agent does NOT pick thresholds or evidence rules per run.

## When to use

Trigger on `/sumble-crm-cleaning`, or on any of: "find duplicate accounts in
my CRM", "dedupe my CRM", "clean my CRM", "find missing parent accounts",
"fix my account hierarchy", "which of my accounts are subsidiaries of each
other?".

## Required tools

- **Sumble public API key** — `SUMBLE_API_KEY` (from sumble.com/account). ALL
  data comes from one REST endpoint, `POST https://api.sumble.com/v6/organizations`
  (match + attribute enrich, including `parent_id` / `subsidiary_ids`; parent
  orgs are then resolved directly by Sumble `id`). **No RunSqlQuery, no SQL,
  no MCP data pulls anywhere in this skill.**

  **Check before prompting — the key is usually already set.** BEFORE you
  surface the link or ask the user to do anything about the key, run this one
  simple command and read the result:
  ```bash
  ls ~/.config/sumble/api_key
  ```
  If that file exists (or `SUMBLE_API_KEY` is exported in the env), the key is
  configured — say so in one line and move on. Only when the check comes up
  empty do you fall through to the setup flow: tell the user their key is at
  **https://sumble.com/account (Account → API key)**, then have them run the
  hidden-input helper in their own terminal (never paste a key into chat):
  ```bash
  ! python3 <skill_dir>/template/_build/set_api_key.py
  ```
  Always `python3`, never bare `python`. If `python3` itself is missing, the
  zero-dependency shell twin is `! sh <skill_dir>/template/_build/set_api_key.sh`.
- **CRM source** (for the account list only): any session MCP that reaches the
  CRM (Salesforce, HubSpot, a warehouse) or a CSV export the user provides.

## Shell-command discipline

This runs unattended and may run in Claude Code, Codex, Cursor, or any other
coding agent — all of which gate shell commands behind approval prompts that
interrupt on anything complex. Follow these rules exactly:

- **One simple command per shell call.** No `&&` / `;` / `|` chains, no `cd`,
  no output redirection, no backgrounding, no command substitution.
- **Use absolute paths, never `cd`.** Every `_build/*` script takes its
  directory as an argument: `python3 <skill_dir>/template/_build/fetch_orgs.py
  --raw <output_root>/_raw` runs from anywhere.
- **Run the pipeline in the foreground.** The scripts stream progress to
  stdout and finish in minutes. Never background a step and poll it.
- **No inline Python, no heredocs.** Multi-line Python or JSON shaping →
  write a `.py`/`.json` file with your agent's file tool, then run/read it.
- **Inspect with your agent's file tools, not the shell** (Read/Glob/Grep, not
  `cat`/`ls`/`wc`/`grep`).

The only shell this skill needs is `mkdir -p <abs>`, `cp <abs> <abs>`, and
`python3 <abs>/script.py [args]` — each as one standalone command.

**Running a command in the user's own terminal** (the API-key helper,
launching `app.py`): in Claude Code prefix with `!`; in Codex/Cursor tell the
user to paste the same command (without the `!`) into a terminal.

## Output

```
crm_cleaning/<company>/
  app.py             stdlib http.server review app (copied from template/, unchanged)
  findings.json      everything the app renders (duplicate clusters, hierarchy
                     gaps, parents-not-in-CRM, unmatched) — regenerated by
                     _build/analyze.py, never hand-edited
  findings.csv       flat one-row-per-finding-account spreadsheet export
  decisions.json     the user's accept/reject/skip + survivor picks + notes
                     (written by the app on every click)
  actions.csv        the change list for the CRM admin (accepted findings only;
                     written by the app's Export button)
  static/            UI: tabs, filter chips, per-finding cards
  README.md
  _raw/              accounts.csv, config.json, responses/, fetch_index.json,
                     parent_orgs.json
```

**Zero-dependency rule:** `app.py` uses only the stdlib (`csv`, `json`,
`http.server`) — no `requirements.txt`, no third-party imports, so any
teammate can `python3 app.py` on the first try.

**Findings non-negotiables (the template enforces both):**
1. **Deep links, always — both directions.** Every matched account carries
   `sumble_url` (from the endpoint's free `sumble_url` attribute, slug
   fallback). The UI shows the match in each finding card's header — a
   "Sumble match:" line listing every distinct matched org (name hyperlinked
   to `sumble_url`, Sumble's domain in parens, plus any alternate
   names/domains from the optional `_raw/org_alternates.json` sidecar so the
   reviewer can see WHY the accounts matched) — while the account table stays
   CRM-only (CRM domain, location, owner) plus Sumble's employee count and
   HQ. When `crm_url_template` is set, every account name links to its CRM
   record too.
2. **Evidence, always.** Every duplicate cluster carries its
   `same_sumble_org` evidence badge plus the matched Sumble org it hinges
   on, and every hierarchy finding shows the Sumble ancestor chain it was
   derived from — the reviewer never has to trust a bare suggestion.

Detection policy (evidence tiers, confidence mapping, survivor ordering,
hierarchy-walk rules, all constants) is documented in
`template/_build/README.md`.

---

## Pipeline

Execute these stages in order. Surface progress between stages.

### Stage 1 — Interview

Goal: collect the CRM account list and the run parameters. Follow these
interview questions closely — a deterministic interview that is the same
between runs.

**Numbering rule:** the interview has **4 main questions**. Start every
interview message with a progress marker — `**Question N of 4**` (combine as
`**Questions 2–3 of 4**` when batching).

**Confirmation rule (applies to EVERY confirm step):** when you ask the user
to confirm something — the column mapping, the checks, the cost — the COMPLETE
thing being confirmed MUST be rendered in full, as markdown, in the SAME
message as the question. Never rely on question-widget option labels to carry
the details.

1. **Company + output directory.** Ask the company's name (prefill if you know
   it) and where to store the output. Default:
   `./tmp/crm_cleaning/<company>`.

2. **CRM source + columns.** Run the source-confirmation flow — never assume:
   inspect the session's MCPs and surface relevant ones by name (Salesforce,
   HubSpot, Snowflake/BigQuery/Databricks/Postgres, Sheets/Drive); else ask
   for a CSV path. Then: list tables → hypothesise the source (SF `Account` /
   HubSpot `companies` / warehouse `dim_accounts`) → confirm in one prompt →
   sample-read 10 rows and verify the columns before the full pull.

   Required fields: **account id, account name, website domain**. Strongly
   encourage all four optional fields — pitch them together up front, they
   each make the findings better:
   - **`parent_crm_id`** (SF `ParentId` / HubSpot parent company) — without it
     every existing hierarchy link looks "missing"; with it the analyzer
     suppresses already-correct links and can flag **conflicts** instead.
   - **`owner`** + **`is_customer`** — drive the merge-survivor suggestion
     (owned and customer records win).
   - **`created_date`** — survivor tiebreak (older record wins).
   - **`contact_count`**, **`opportunity_count`**, **`activity_count`** — the
     account's CRM footprint (how many contacts, opportunities, and logged
     activities hang off each record). Shown on every duplicate card and used
     to pick the survivor: when two records are the same company, the one
     carrying the relationship history is almost always the keeper. They also
     split the **Split activity** vs **Concentrated** duplicate buckets —
     without them every single-owner cluster falls into Concentrated. Cheap to
     pull (one aggregate query per object in Salesforce/HubSpot) and the
     single best primary-record signal — read at analyze time, so they can be
     added later without re-fetching.

   Print the full proposed column mapping (CRM field → `accounts.csv` column)
   and get one yes/edit confirmation. Then pull the full list and write
   `_raw/accounts.csv` (schema in `template/_build/README.md`).

   **CRM record links.** Derive the CRM's record-URL pattern so every account
   in the review UI deep-links back to the CRM (record as `crm_url_template`
   in `_raw/config.json`, `{id}` = account id):
   - Salesforce: `https://<MyDomain>.lightning.force.com/lightning/r/Account/{id}/view`
     (My Domain from the org's instance URL, e.g. `acme.my.salesforce.com` →
     `acme.lightning.force.com`)
   - HubSpot: `https://app.hubspot.com/contacts/<portalId>/record/0-2/{id}`
   - Warehouse/CSV: ask the user for their CRM's record URL pattern; leave
     unset if they don't have one (names render unlinked).

3. **Which checks?** One question, three options (default **both**):
   - **Duplicates** — potential duplicate accounts
   - **Parent/subsidiary** — missing or conflicting hierarchy links
   - **Both** (recommended — same fetch either way; the analyzer just skips a
     section)
   Record as `checks` in `_raw/config.json`.

   When parent/subsidiary is on, mention the PE default in the same message
   (one line, no extra question unless the user reacts): *private-equity-firm
   parents are excluded by default — say so if you want PE roll-ups included
   and I'll set `include_pe_parents: true` (they get their own tab).* Record
   the choice as `include_pe_parents` in `_raw/config.json` (omit or `false`
   = default exclude).

4. **Cost confirmation.** Surface the credit cost before fetching:
   **~5 credits per matched account** (1 base + 4 paid attributes), plus the
   same for each non-CRM parent org resolved (usually a small fraction). For
   a CRM of N accounts say "~5×N credits". **≥ 100,000 accounts → ask**
   whether to run it all or start with a subset (an owner's book, a record
   type, a country); smaller lists run whole without asking.
   Get one explicit "go" on the cost before Stage 2.

   Write `_raw/config.json`:
   ```json
   {
     "company": "<company>",
     "checks": ["duplicates", "parent_sub"],
     "crm_url_template": "<record URL pattern with {id}, or omit>",
     "crm_source": "<where accounts.csv came from, for the record>",
     "include_pe_parents": false
   }
   ```

### Stage 2 — Fetch from the unified endpoint

No SQL. One script matches every account and walks the org hierarchy upward
(non-CRM ancestors resolved directly by Sumble `id`, up to 3 hops):

```bash
python3 <skill_dir>/template/_build/fetch_orgs.py --raw <output_root>/_raw
```

Writes `_raw/responses/resp_*.json`, `_raw/fetch_index.json` (per-input-row
CRM fields + matched org id), and `_raw/parent_orgs.json`. Progress streams to
stdout (matched counts + credits per batch). If the key isn't set, run the
Stage-0 key helper first.

### Stage 3 — Analyze

```bash
python3 <skill_dir>/template/_build/analyze.py --raw <output_root>/_raw
```

Writes `<output_root>/findings.json` + `findings.csv` and prints a summary
(clusters, hierarchy gaps, parents-not-in-CRM, unmatched).

**Agent sanity pass (before handover, with file tools — not the shell):**
read the summary numbers and spot-check `findings.json`:
- Open the 2–3 largest duplicate clusters — do the accounts plausibly look
  like one company (names/domains agree with the matched Sumble org)?
- Open 2–3 `missing_parent_link` findings — does the Sumble chain shown
  actually connect the child to the suggested parent?
- If the duplicate count looks absurd (e.g. >30% of all accounts in
  clusters), the likely cause is a bad column mapping (e.g. domain column
  holding emails) — fix `accounts.csv` and re-run Stage 2–3 rather than
  handing over noise.
Surface the summary + anything suspicious to the user.

### Stage 4 — Generate the app

```bash
mkdir -p <output_root>/static
cp <skill_dir>/template/app.py    <output_root>/app.py
cp <skill_dir>/template/README.md <output_root>/README.md
cp <skill_dir>/template/static/index.html <output_root>/static/index.html
cp <skill_dir>/template/static/app.js     <output_root>/static/app.js
cp <skill_dir>/template/static/style.css  <output_root>/static/style.css
cp <skill_dir>/template/static/favicon.svg <output_root>/static/favicon.svg
```

Write `<output_root>/.gitignore` via your file tool:
```
__pycache__/
*.csv
decisions.json
```

### Stage 5 — Run instructions

Print this to the user. Don't try to run the server inside the agent — let
the user start it in a terminal where it stays up.

```bash
cd <output_root>
python3 app.py
# open http://localhost:8002 in your browser
```

No `pip install`, no virtualenv — stdlib-only, any Python 3.10+. Override the
port via `python3 app.py 9002` or `PORT=9002 python3 app.py`.

Explain the review loop in two sentences: hierarchy and parents-not-in-CRM
findings get accept/reject/skip, while a duplicate cluster is resolved by its
per-record actions — mark one record **Primary** (the survivor) and the others
default to **Merge**, switch any to **Delete**, or hit **Not a duplicate** to
dismiss a false match (decisions save instantly to `decisions.json`). Point out
that the Duplicates tab is split into three sub-tabs —
**Multiple owners** (hard: two reps claim the account, needs manual review),
**Split activity** (likely merge candidates — merge to preserve history), and
**Concentrated** (easy: the obvious delete case, keep the populated record) —
so the reviewer can work the easy buckets first and reserve the owner conflicts
for a judgment call. If the run set `include_pe_parents: true`, mention the
**PE roll-ups** sub-tab under Parents-not-in-CRM: PE-firm parents kept out of
the conventional roll-ups list so portfolio roll-ups get their own review
queue. Then
**Export actions.csv** to get the change list — `merge` / `delete` /
`set_parent` / `create_parent_and_link` rows keyed by CRM account id, ready
for the CRM admin, a Data Loader job, or a follow-up agent run. Mention the
**Unmatched** tab too: accounts Sumble couldn't match are often shells, typos,
or defunct entities — worth a skim while cleaning.

**Refresh path:** new CRM export → overwrite `_raw/accounts.csv` → re-run
Stage 2 + Stage 3 → restart `app.py`. Decisions persist by finding id;
findings whose ids change are simply re-reviewed.
