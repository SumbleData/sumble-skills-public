---
name: sumble-territory-planning
description: "Companion to sumble-account-scoring: plan and rebalance sales territories. Interviews the user about their segments (default Enterprise + Commercial) and whether the segment line is a hard rule or should be calibrated from their data, pulls territory ownership from the CRM, and pulls per-rep×account activity (calendar meetings, Gong/Fireflies/Granola calls, Salesforce email) from whatever MCPs are connected. Generates a self-contained, zero-dependency Python + HTML/JS app at territory_planning/{company}/ with per-segment book-strength heatmaps (each rep's top 10/25/50/100/200 accounts by average in-segment rank, plus coverage), a granular account view, highlights for accounts that are not being worked / in the wrong segment / strong-but-unallocated / double-allocated / strong-but-idle (with a live top-N strong-account cutoff), and a suggest→accept/reject→export flow that writes an actions.csv of approved owner changes."
---

# Territory Planning

The companion to `sumble-account-scoring`. Scoring answers *which accounts are
strong*; this skill answers *are the right reps on them, and are the books
fair*.

It produces two things:

1. A zero-dependency Python **web app** (stdlib `http.server`) showing book
   balance per segment, per-rep coverage, every account with its flags, and a
   review queue of proposed owner changes you accept or reject.
2. **`territory-plan.json`** — a portable config (segments, the boundary rule,
   the rep roster, the activity window and sources, the balance/move policy)
   plus **`actions.csv`**, the CRM-ready list of approved owner changes.

Follow the stages closely — input (interview) and output should be consistent
between runs, more deterministic than most skills.

## When to use

Trigger on `/sumble-territory-planning`, or on any of: "plan my territories",
"balance my territories", "rebalance the books", "who should own which
accounts", "are my reps' books fair", "which accounts is nobody working",
"split enterprise and commercial".

If the user wants to know which accounts are *good* (not who owns them), that's
`/sumble-account-scoring`. This skill happily consumes that skill's output but
does not replace it.

## Required tools

- **An account-scoring run (preferred), or a Sumble API key.** Account strength
  comes from one of two places, decided at Q1:
  - **Path A — an existing `/sumble-account-scoring` run.** Read `score.csv`
    from `account_scoring/{company}/`. It already carries `org_id`, `score`,
    `account_category`, `employee_count_int`, per-persona headcounts and
    domains. Nothing is fetched, no credits are spent. **Always prefer this** —
    a score tuned to the user's ICP is a far better measure of book value than a
    generic one.
  - **Path B — no scoring run.** `fetch_light.py` resolves the CRM account list
    against `POST https://api.sumble.com/v6/organizations` and pulls
    **`sumble_score`** (Sumble's own account score) plus `employee_count` and
    firmographics. ~6 credits per matched org.

  **Check the API key before prompting — it is usually already set.** Run this
  one simple command and read the result:
  ```bash
  ls ~/.config/sumble/api_key
  ```
  If that file exists (or `SUMBLE_API_KEY` is exported), say so in one line and
  move on. Only when it comes up empty, tell the user their key is at
  **https://sumble.com/account (Account → API key)** and have them run the
  helper, which reads the key **without echoing** and saves it chmod 0600:
  ```bash
  ! python3 {skill_dir}/template/_build/set_api_key.py
  ```
  **Always `python3`, never bare `python`.** No Python at all?
  `! sh {skill_dir}/template/_build/set_api_key.sh` is an identical POSIX-shell
  twin. **Never ask the user to paste a key into chat** — it would be logged.
  Path A needs no key at all unless the boundary metric requires a supplemental
  job-function pull.

- **A CRM / ownership source** — Salesforce, HubSpot, a warehouse, or a CSV.
  Required: without owners there are no territories to plan.

- **Activity sources (optional but the point of the skill)** — Google Calendar,
  Gong, Fireflies, Granola, Salesforce email, Gmail. Whichever MCPs are
  connected. Without any of them the app still shows balance and segment fit,
  but every account reads "not worked" and the move suggestions become
  size-only. Say so plainly rather than letting the user think coverage is zero.

- **Sumble MCP** — only for `lookup.py`-adjacent name resolution and, on Path B,
  nothing at all. If it isn't available, install: https://docs.sumble.com/api/mcp.

## Shell-command discipline

This runs unattended AND is shipped to non-technical users — and it may run in
**Claude Code, Codex, Cursor, or any other coding agent**. They all gate shell
commands behind a command-approval / permission system that **interrupts the run
on anything complex** (compound, redirected, `cd`-prefixed, or
substitution-bearing commands). Each interruption stalls the run, in every
agent. Keeping commands trivially simple is the portable way to avoid that
everywhere. Follow these rules exactly:

- **One simple command per shell call.** No `&&` / `;` / `|` chains, no `cd`, no
  output redirection (`>`, `>>`, `2>&1`), no backgrounding (`&`, `nohup`), and no
  command substitution (`$(…)` or backticks).
- **Use absolute paths, never `cd`.** Every `_build/*` script takes its directory
  as an argument, so run e.g.
  `python3 {skill_dir}/template/_build/merge_territory.py --raw {output_root}/_raw`
  from anywhere.
- **Run the pipeline in the foreground.** The scripts stream progress to stdout
  and finish in seconds (minutes only for a Path B fetch). NEVER background a
  step and poll it — every poll is a fresh approval prompt.
- **No inline Python, no heredocs.** Any multi-line Python, JSON shaping, or
  counting → write a `.py` to `{output_root}/_raw/` with your agent's file tool
  and run it as a single `python3 {abs}.py`. Never `python3 -c "…{…}…"`.
- **Inspect with your agent's file tools, not the shell.** Use the native
  file-read / glob / grep tools — never `cat` / `tail` / `head` / `ls` / `wc`.

The only shell this skill needs is `mkdir -p {abs}`, `cp {abs} {abs}`, and
`python3 {abs}/script.py [args]` — each as one standalone command.

**Running a command in the user's own terminal.** The API-key helper and
`app.py` are best run by the user so they're interactive / stay up. In **Claude
Code** prefix with `!`. In **Codex / Cursor** just tell the user to paste the
same command (without the `!`) into a terminal.

## The deliverable is the app, not the analysis

**This skill exists to hand the user a tool they calibrate themselves.** The
interview settles the *shape* — what the segments are, what metric divides them,
who the reps are, where activity comes from. Everything after that is a dial in
the app.

So: **stop interviewing once the shape is settled, and ship.** The boundary
threshold and the per-rep capacity are the two things the Calibrate panel exists
to tune, so a first pass at both is enough — do not keep asking the user to
refine numbers in chat that they are about to drag in the UI. Likewise, when a
result looks wrong (a rep gets no moves, a segment routes nothing), **report it
and hand over the app**; do not spend turns proposing re-runs with different
constants. Explaining which dial fixes it beats running it for them.

Ship as soon as `territory.csv` exists and spot-checks pass. Refinement is what
the app is for.

## Output

```
territory_planning/{company}/
  app.py                  stdlib http.server (copied from template/, unchanged — no deps)
  territory_lib.py        shared helpers + the move engine, stdlib-only
                            (copied from template/_build/ — the app imports it,
                             so the app and the CLI run the SAME four phases)
  territory-plan.json     THE config — segments, boundary rule, rep roster,
                            activity window + sources, balance & move policy
  territory.csv           one row per Sumble org: identity, score, segment,
                            owner, every flag, per-rep activity counts, proposal
  actions.csv             written by the app: approved owner changes for the CRM
  static/                 UI: Calibrate panel, book-depth heatmaps, tables, move queue
  README.md
  _raw/                   agent-written inputs + fetch responses + audit
```

### `territory.csv` column schema

One row per Sumble `org_id` — **the org id is the join key, and that is what
makes double allocation detectable.** Two CRM records with different names and
different domains that resolve to the same organisation are two reps working one
company; no amount of name matching would have found it.

**Identity + strength**
- `org_id` (int) — Sumble organization id, primary key
- `name`, `domain`, `sumble_url`
- `crm_account_id` (str) — pipe-joined when several CRM records collapse into one org
- `account_category` (str) — `customer` / `allocated` / `unallocated` /
  `whitespace` / `whitespace_subsidiary`, same vocabulary as account-scoring
- `score` (float) + `score_source` (`custom` = the user's tuned account score,
  `sumble` = Sumble's own `sumble_score`)
- `size_metric` (float) + `size_metric_name` (str) — the value the segment
  boundary is applied to
- `account_segment` (str) — segment key implied by `size_metric`

**Ownership**
- `owner`, `owner_email`, `rep_segment` — the *canonical* owner when several
  reps own records for the same org: whoever has the most activity (ties
  alphabetical)
- `other_owners` (str, pipe-joined) — the other claimants

These 0/1 flag columns are the CSV baseline (computed at merge time against the
canonical owner). **The app recomputes the attention flags live against the
`effective owner`** (current owner + the user's accepted/manual allocations), so
assigning an account on the Accounts tab clears/sets its flags and updates the
Overview immediately — the CSV columns are the exported snapshot, the UI is the
working state.

**Flags (0/1, always present)** — each is a filter chip and a highlight card:
- `unallocated` — no active rep owns it: nobody, a queue, or someone who has
  left. **A departed rep's name in the owner field is not coverage**, and this is
  the single most common way a book looks covered but isn't. (Not shown as its own
  highlight card — the raw count is huge and mostly weak accounts; the app surfaces
  `strong_unallocated` instead.)
- `double_allocated` — ≥2 active reps own records resolving to the same org
- `segment_misfit` — the account's size segment ≠ its owner's segment
- `worked` — the owner has ≥1 meeting, call, or **outbound** email with the
  account in the window. Inbound email alone is the prospect doing the work, so
  it is counted and displayed but does not clear this flag on its own.
- `strong_idle` — one of the **top `strong_cutoff` accounts by ICP score**
  (global, default 500), owned, and not worked: the strongest accounts nobody is
  working. The app recomputes this live from a **Strong-account cutoff** control in
  the sidebar (the CSV column is the baseline at the default). The `strong_unallocated`
  highlight (strong + unallocated) is derived the same way, live in the app — it is
  not a CSV column.

`whitespace` is a valid `account_category` and is still routed by the mover, but it
is **not** shown as an attention highlight card — a territory review is about the
existing book, not browsing net-new accounts.

**Activity (per owning rep × this account only — never team-wide)**
- `meetings`, `calls`, `emails_out`, `emails_in` (int)
- `last_activity_date` (ISO date), `activity_sources` (pipe-joined)

**Proposals**
- `proposed_owner`, `proposal_reason`
  (`misfit` / `assign_unallocated` / `assign_whitespace` / `rebalance` / `manual`),
  `proposal_status` (`suggested` / `accepted` / `rejected` / `manual` / blank)

**Optional**
- `pipeline_value` (float) — open pipeline, when the user supplies it

### How balance is measured

Per segment, per rep: **total account score**, not account count. A rep with 40
weak accounts does not have a bigger book than a rep with 15 strong ones, and
counting rows says they do.

The balance index is the **coefficient of variation** of per-rep total score
(population stdev ÷ mean). CV is scale-free, so it reads the same for a 5-account
team and a 5,000-account one; a raw max/min ratio does not. Labels are policy
constants: **≤ 0.15 balanced, ≤ 0.35 uneven, above that imbalanced.**

**Customers are excluded from balance by default** (`balance.include_categories`
= `allocated` + `unallocated`). A rep is not overloaded because they own
renewals, and moving a customer breaks a live relationship. They are still shown
everywhere else.

**A rep can be excluded too** — set `in_balance=0` in `reps.csv`. This is the
**player-coach** case: a sales leader, a founder, or anyone who legitimately owns
accounts but whose book should not be judged for fairness. Their book stays fully
visible (bars, coverage %, per-account rows, activity) but is left out of the CV,
and the mover treats them as neither donor nor recipient — including in the
misfit phase, since a deliberately odd-shaped book is not evidence of a mistake.
Reach for this instead of `is_rep=0` when the accounts really are being worked:
`is_rep=0` would dump the whole book into `unallocated` and route it away.

### How moves are proposed

`suggest_moves.py`, four phases, least disruptive first — **take the free wins
before churning anyone's book:**

1. **Misfit** — an out-of-segment account its owner is not working moves to the
   right segment.
2. **Unallocated** — an account no active rep owns goes to the lightest book in
   its segment.
3. **Whitespace** — same, for net-new accounts from an account-scoring
   whitespace run.
4. **Rebalance** — only now are already-owned accounts moved between reps, most
   overloaded → most underloaded, choosing the account that most nearly halves
   the gap. Stops at CV < 0.10, or once moves reach 15% of the segment's book.

**The hard constraint, everywhere: an account with activity is NEVER proposed
for a move.** A rep who has met, called, or emailed a prospect has context the
balance maths cannot see, and taking it away to even out a spreadsheet is how
territory planning loses deals. Worked misfits are flagged for a human instead,
and the run reports how many it refused to touch. Double-allocated accounts are
also left alone until the duplicate is resolved — they'd otherwise be counted
against two books at once.

Deterministic: same `territory.csv` + same plan → byte-identical proposals. No
RNG; every tie breaks on `org_id`. Re-running after a review session **preserves
the user's decisions** (accepted and manual moves count as already applied,
rejected rows are never re-proposed) — use `--reset` to start over.

---

## Pipeline

Execute these stages in order. Surface progress between stages.

### Stage 1 — Interview

Goal: collect the input required to produce a first territory plan. Follow these
questions closely and do not go off script — a deterministic interview that is
the same between runs.

**Numbering rule:** the interview has **7 main questions**. Start every
interview message with a progress marker — `**Question N of 7**` — so the user
always knows how much remains. When you combine questions into one message,
label it with the range (e.g. `**Questions 5–7 of 7**`).

**Confirmation rule (applies to EVERY confirm step):** when you ask the user to
confirm something — the segment boundary, the rep roster, the activity sources —
the COMPLETE thing being confirmed MUST be rendered in full, as markdown, in the
SAME message as the question. Never ask "confirm the roster?" while the details
live only in an earlier message, in a tool result, or inside multiple-choice
option labels (interactive question widgets truncate labels — they are NOT a
substitute for printing the list). If anything changed since it was last shown,
re-print the whole updated list, not a diff.

---

**1. Company, and where the account strength comes from.**

Ask the company name + URL (prefill if you know it, ask them to confirm), and
where to store the output (default `./tmp/territory_planning/{company}`).

Then **look for an existing account-scoring run** before asking anything:
check `./tmp/account_scoring/{company}/score.csv` with your file tools. Report
what you found in one line, e.g. *"Found your account-scoring run (4,812 scored
accounts) — I'll use that tuned score as account strength."* If it's somewhere
else, ask for the path.

If there is no run, explain the tradeoff in plain language and let them choose:

> Territory balance needs a measure of how valuable each account is. Two options:
> **(a)** Run `/sumble-account-scoring` first — the score is tuned to *your* ICP,
> so "a big book" means what you mean by it. Best answer, takes longer.
> **(b)** Use Sumble's own account score — generic but instant, ~6 credits per
> account.

Record as `spec.score_source`: `{"kind": "custom", "path": "…/score.csv"}` or
`{"kind": "sumble"}`.

---

**2. Segments.**

"What sales segments do you have?" **Propose Enterprise + Commercial as the
default** — don't make them invent it. They may rename, add (SMB, Mid-Market,
Strategic), or drop to two. Store ordered **smallest → largest** via `order`.

---

**3. The segment boundary — branching.**

Ask ONE question: *"Do you have a hard-line rule that splits these segments, or
should I calibrate one from your data?"*

**3a — They have a hard line.** Ask for it verbatim and capture the metric plus
the threshold(s), e.g. "Enterprise is 1,000+ employees". The metric may be:
- total employee count → `"metric": "total_employees"`
- headcount in a job function → `"metric": "jf_people:{Function Name}"`
- a column they supply by CSV → `"metric": "custom:{column}"`

If they name something Sumble cannot supply (revenue, ARR, a named account
list), say so and offer: supply it as a CSV column, or fall back to employee
count. Do not silently substitute.

**3b — Calibrate it.** Propose exactly TWO candidate metrics and let them pick:

1. **Total employee count** — the safe default.
2. **Headcount under their ICP job function** — often the better line, because
   it sizes the *buying centre* rather than the company. Read the key persona
   from the account-scoring config (or ask), then **snap UP to a broad,
   top-level parent job function** and suggest that.

   > **Never suggest a granular child function.** "DevOps Engineer" or "SRE"
   > reads zero at most companies below a few thousand people, so the "boundary"
   > ends up sorting on whether Sumble has data, not on size. A broad parent —
   > `Engineer`, `Sales`, `Marketing` — is dense enough to size anyone. It will
   > sweep in adjacent roles (an electrical engineer lands under `Engineer`);
   > that is the correct trade, because density is what makes the line hold.
   >
   > Worked examples: for **Sumble** (sells to sales teams) suggest **`Sales`**.
   > For **Datadog** (sells to engineering) suggest **`Engineer`**. Not "Account
   > Executive", not "DevOps Engineer".

   Resolve the display name with `lookup.py --titles "{name}"` before using it —
   the endpoint takes the canonical **display name**, and a wrong one 400s with
   a "did you mean" list.

   On Path A, if the scoring run never fetched that function, pull just that one
   metric with `fetch_light.py --from-score … --only-jf "{Name}"`.

Then run `calibrate_split.py` and present the result. It picks its own method:
**supervised** (two segments and the reps' segments are already known) sweeps
thresholds and picks the one leaving the fewest reps working out-of-segment
accounts — the reps' actual behaviour defines the line; **k-means on log(size)**
otherwise. Either way the answer is snapped to a round, defensible number.

**Print the whole proposal in the message** — the method and why, the size
distribution (p10/median/p90), the proposed line, how many accounts land in each
segment, and any warning. **Always surface the density warning if it fires**
(">30% of accounts below the line read zero on this metric") and offer the
broader function or total employees instead. Then confirm.

---

**4. Where territory ownership lives.**

Inspect the session's MCPs and **surface relevant ones by name** (Salesforce,
HubSpot, Snowflake/BigQuery/Databricks/Postgres, Sheets/Drive); else ask for a
CSV path. Then run the source-confirmation flow — **never assume**:

list tables → hypothesise the source (Salesforce `Account` with
`Owner.Name`/`OwnerId`; HubSpot `companies` with `hubspot_owner_id`; a warehouse
`dim_accounts.account_owner`) → **confirm in one prompt** → sample-read
`LIMIT 10` and verify the join keys (account name, domain/website) → full pull.

Ask two things while you're there:
- Does the source encode **which segment each rep sells** (a role, team, or
  user-type field)? If yes, use it and skip the guessing in Q5.
- Does it mark **customers / closed-won**? Customers are excluded from balance,
  so this materially changes the numbers. Map it to `is_customer` in
  `ownership.csv`.

---

**5. The rep roster.**

Build the roster from the distinct owners in the ownership pull, then run
`calibrate_split.py` (already run in Q3 — reuse its `rep_segment_guesses`) to
guess each rep's segment from the median size of the accounts they own. A rep
with fewer than 3 matched accounts is `unknown` — ask, don't guess.

**Print the FULL roster table in the message** — rep, email, guessed segment,
#accounts, median account size — and flag anyone who looks like **not a real
seller**:

- queues and pools ("Unassigned", "House Accounts", "Inbound Queue")
- integration / system users
- **departed employees** — a name that owns accounts but is inactive in the CRM.
  Ask directly: *"Is anyone on this list no longer with the company?"* Their
  accounts should surface as unallocated, which is exactly what a territory
  review is for.

Set `is_rep=0` for each of those. Loop on the user's corrections until accepted.

**Watch for the player-coach — the third answer people don't know to ask for.**
A sales leader, founder, or CS lead who owns real accounts fits neither
`is_rep=1` (their book is odd-shaped, so it drags the segment CV and invites
pointless move proposals) nor `is_rep=0` (which would dump a genuinely-worked
book into `unallocated`). Set **`in_balance=0`** instead. The tell is a rep whose
median account size is wildly out of line with their stated segment, or who owns
a large book with almost no customers. Offer it explicitly rather than forcing a
binary — and if you spot the mismatch in the data, say so with the numbers before
asking.

**Collect rep emails — they are the join key for all activity.** Take them from
CRM user records where available; otherwise ask; as a last resort propose the
obvious pattern (`first.last@{company-domain}`) and **confirm it explicitly**. A
rep with no email will have every account read "not worked", so `build_plan.py`
warns about it — surface that warning to the user rather than letting the
coverage numbers lie.

---

**6. Activity sources + window.**

Inspect the session's MCPs and offer whichever actually exist, by name:

| Source | MCP | Event kind |
|---|---|---|
| Meetings | Google Calendar | `meeting` |
| Calls | Gong · Fireflies · Granola | `call` |
| Email | Salesforce (EmailMessage / Task) · Gmail | `email_out` / `email_in` |

Let them pick any subset. **Window default: 90 days**, configurable.

State the two things plainly, in the message:
> Activity is counted **between the owning rep and that account only** — not
> across the team. And only **counts and dates** are stored: no subjects, no
> transcripts, no message bodies.

**Activity matching rules (you apply these when writing the event CSVs):**
- Normalise every domain: lowercase, strip scheme, `www.`, path, port, leading `@`.
- **Drop free-mail domains and the seller's own domain.** A rep emailing their
  own colleagues, or their personal Gmail, is not account activity. (The
  canonical list is `territory_lib.FREEMAIL_DOMAINS`; `merge_territory.py`
  enforces it again as a backstop.)
- **Calendar** — an event in-window where the rep is organiser or attendee AND
  ≥1 other attendee's email domain matches an account domain → one `meeting`.
- **Call recorders** — a recorded meeting in-window where the rep is host or
  participant AND a participant domain matches an account → one `call`.
- **Salesforce email** — an EmailMessage (or Task with type Email) tied to the
  account or a contact at its domain. From = rep → `email_out`; rep in To/Cc →
  `email_in`.
- One row per event. Do not pre-aggregate — `merge_territory.py` does the
  roll-up, so the same event never counts twice.

---

**7. Optional extras.** Ask all three in ONE message:

- **(a) Open pipeline value per account.** Often the real reason a book *feels*
  unfair. A CSV of `domain,pipeline_value`, or a sum of open opportunities.
  Shown per rep; not used to propose moves.
- **(b) Capacity — ask for it per SEGMENT, not per rep.** "Enterprise reps carry
  50, commercial 150" is how sales leaders actually state a cap, so store it as
  `segments[].default_capacity` in `spec.json`; a rep's own `capacity` in
  `reps.csv` overrides their segment's default when someone is a genuine
  exception (ramping, part-time). `build_plan.py` resolves the two into
  `reps[].effective_capacity`, and both the mover and the app read that.

  **Ask this whenever the unallocated pile is large — it is not optional then.**
  Phase 2 assigns EVERY unowned account, so a book with thousands of unallocated
  rows and no cap produces an `actions.csv` of thousands of moves that no rep can
  act on. Say so plainly, with the arithmetic: *"there are N unallocated
  accounts and M reps in that segment — without a cap each gets about N/M new
  accounts."* If the caps leave accounts unrouted, `suggest_moves.py` reports
  which segments hit the ceiling rather than silently dropping them.
- **(c) Whitespace routing depth** — only if the scoring run produced whitespace:
  how many top net-new accounts to route to owners (**default 50**). The rest are
  dropped from the sheet; territory planning is not the place to browse 10,000
  whitespace rows.

---

### Stage 2 — Build the data

Write these into `{output_root}/_raw/` with your file tools:

- **`spec.json`** — everything confirmed above:
  ```json
  {
    "schema_version": 1,
    "company": {"name": "Acme", "url": "acme.com", "folder_slug": "acme"},
    "score_source": {"kind": "custom", "path": "/abs/…/score.csv"},
    "segments": [{"key": "commercial", "label": "Commercial", "order": 1,
                  "default_capacity": 150},
                 {"key": "enterprise", "label": "Enterprise", "order": 2,
                  "default_capacity": 50}],
    "boundary": {"metric": "total_employees", "label": "Total employees",
                 "thresholds": [{"segment": "enterprise", "min": 1000}]},
    "activity": {"window_days": 90, "sources": ["google_calendar", "fireflies"],
                 "company_domain": "acme.com"},
    "whitespace_top_n": 50,
    "strong_cutoff": 500
  }
  ```
- **`ownership.csv`** — `crm_account_id,name,domain,owner,owner_email,owner_is_queue,is_customer`
- **`reps.csv`** — `name,email,segment,is_rep,capacity,in_balance`
  - `capacity` — blank inherits the segment's `default_capacity`; set it only
    for a genuine exception.
  - `in_balance` — blank/`1` normally; `0` for a **player-coach** whose book
    should be visible but neither measured for fairness nor moved off.
- **`activity/{source}.csv`** — one file per source:
  `source,rep_email,account_domain,kind,ts` (`kind` ∈ `meeting|call|email_out|email_in`)
- **`accounts.csv`** (Path B only) — `crm_account_id,name,domain`
- **`pipeline.csv`** (optional) — `domain,pipeline_value`

Then run each as ONE command with absolute paths — no `cd`, no chaining:

```bash
# Path B only — resolve accounts + pull sumble_score / employee_count
python3 {skill_dir}/template/_build/fetch_light.py --raw {output_root}/_raw
# Path A supplement — only when the boundary needs a job function the scoring run lacks
python3 {skill_dir}/template/_build/fetch_light.py --raw {output_root}/_raw --only-jf "Engineer" --from-score {path}/score.csv
# Boundary proposal (Q3b) — prints JSON, writes nothing
python3 {skill_dir}/template/_build/calibrate_split.py --raw {output_root}/_raw
# After the boundary + roster are confirmed:
python3 {skill_dir}/template/_build/build_plan.py --raw {output_root}/_raw
python3 {skill_dir}/template/_build/merge_territory.py --raw {output_root}/_raw
python3 {skill_dir}/template/_build/suggest_moves.py --dir {output_root}
```

**Surface the merge summary to the user** — allocated / unallocated /
double-allocated / misfit / not-worked / strong-idle counts, and the per-segment
CV. That summary IS the finding; don't let it scroll past silently. Call out
these three explicitly if they fire:
- ownership rows that matched no org (unmatched by Sumble, or outside the scored set),
- **no activity events found at all** — the coverage numbers are then meaningless;
  check the rep emails and the activity pull before going further,
- whitespace trimmed to the routing depth.

**Path B credit cost** ≈ 6 credits per matched org; state the estimate before
running a large pull.

---

### Stage 3 — Generate the app

```bash
mkdir -p {output_root}/static
cp {skill_dir}/template/app.py                    {output_root}/app.py
cp {skill_dir}/template/_build/territory_lib.py   {output_root}/territory_lib.py
cp {skill_dir}/template/README.md                 {output_root}/README.md
cp {skill_dir}/template/Dockerfile                {output_root}/Dockerfile
cp {skill_dir}/template/.dockerignore             {output_root}/.dockerignore
cp {skill_dir}/template/static/index.html         {output_root}/static/index.html
cp {skill_dir}/template/static/app.js             {output_root}/static/app.js
cp {skill_dir}/template/static/style.css          {output_root}/static/style.css
cp {skill_dir}/template/static/logo.svg           {output_root}/static/logo.svg
cp {skill_dir}/template/static/favicon.svg        {output_root}/static/favicon.svg
```

`territory_lib.py` sits beside `app.py` as a sibling module (it is stdlib-only),
exactly like `score_sheet.py` in account-scoring. The `Dockerfile` +
`.dockerignore` make the app **fly-deploy-ready** (`/fly-deploy`) with no extra
steps; they're inert for a local run. HTTP Basic Auth is **env-gated** — it
activates only when `BASIC_AUTH_PASS` is set, so `python3 app.py` stays open
locally.

Write `{output_root}/.gitignore` via your file tool:
```
__pycache__/
*.csv
```

Before handing over, spot-check `territory.csv` with your file tools: the header
must match the schema above, and at least one row should carry a non-blank
`owner`. If every row is unallocated, the ownership join failed — fix it before
telling the user the app is ready.

---

### Stage 4 — Run instructions

Print this. Don't try to run the server yourself — let the user start it in a
terminal where it stays up.

```bash
cd ./tmp/territory_planning/{company}
python3 app.py
# open http://localhost:8002 in your browser
```

No `pip install`, no virtualenv — `app.py` is stdlib-only and runs on any
Python 3.10+. Override the port with `python3 app.py 9002` or `PORT=9002`.

Tell them how to work it, in this order:

1. **Overview** — a **rep × depth heatmap** (this is the home page; there is no
   separate Reps tab). There are always exactly **two tables** (strength +
   coverage); a **segment filter** at the top (`All segments` by default, plus one
   pill per segment) narrows the rows — every rep by default, or one segment's when
   filtered. With `All segments`, a **Segment column** labels each row. Rows are
   reps, columns are their **top 10 / 25 / 50 / 100 / 200** accounts (plus the whole
   book), and each cell is the **average rank** of those accounts *within that
   segment* (1 = best). Conditional formatting shades **green (strong) → pale (weak)
   down each whole column** (across all rows shown, both segments); a cell is blank
   when the rep owns fewer than N accounts *in that segment*. **Every header sorts**
   — click to sort, click again to flip. A second matrix below shows **coverage**
   (share of each band worked in the window). Below both are the "needs attention"
   flag cards.

   Each matrix leads with a **summary column** — the headline metric, and the
   default sort (descending). Both are weighted to the segment's best accounts, and
   the header carries a plain-language tooltip:
   - **Capture** (strength table, default sort) — the rep's share of the segment's
     *top-tier* account value, where a top-decile account (by score) counts double a
     top-quartile one and everything below the quartile counts zero. "Holds a lot of
     the best value" vs "holds a big pile of weak accounts."
   - **Activation** (coverage table, default sort) — of that top-tier value the rep
     *holds*, the share they're actually working. Book-size-independent (denominator
     is their own holdings), so `0%` is a rep sitting on strong accounts — the
     clearest read on a player-coach.
   The top-decile multiplier is the `tier_decile_weight` knob in `territory-plan.json`
   (default 2).

   Two things make the ranks trustworthy, both learned the hard way:
   - **Rank within a single segment only.** A rep's book mixes segment sizes — a
     marquee account below the size line still lives in Commercial — and a
     Commercial rank of 2 is not comparable to an Enterprise rank of 2. Averaging
     ranks from two universes produces impossible numbers (an average below the
     arithmetic floor of `(N+1)/2`). The matrix ranks each rep's accounts only
     against their own segment, and counts only their **in-segment** accounts.
   - **"In-seg" ≠ total book.** The count column is the rep's in-segment accounts,
     which is often far below what they own — an enterprise rep sitting on a pile
     of commercial-sized accounts (misfits to shed) is exactly what that gap
     reveals.

   (Book-balance itself — the coefficient-of-variation across reps — still drives
   the Moves tab and the mover, it's just no longer the Overview's headline.)
2. **Calibrate** (the left sidebar) — the two dials, each in its own box:
   - **where the line between segments sits**, on the boundary metric
   - **target accounts per rep, per segment**

   Both preview live as you type — how many accounts land each side of the line,
   and how many seats the capacity actually buys (`reps × cap`), including a
   blunt *"N cannot be held"* when the segment has more accounts than seats.
   **Committing a field** (leaving it or pressing Enter) re-runs the same four
   phases the CLI runs and rewrites `territory-plan.json`, so the plan file always
   matches what is on screen — there is no separate Apply button. The user's
   accept / reject / manual decisions are always preserved (only the pipeline's own
   suggestions are re-derived); a full reset is `suggest_moves.py --reset` from the
   CLI.

   A third box, **Strong-account cutoff**, sets how many top accounts (by ICP
   score) count as "strong" for the *strong-but-idle* and *strong-but-unallocated*
   attention flags. Unlike the two dials above it updates the flags **live** — it
   doesn't touch the mover, so there's no Apply.
3. **Fix the double-allocations first.** Two reps on one company distorts every
   other number.
4. **Accounts** — every account, sortable, with a **Rank** column (global rank by
   ICP score, 1 = best; ties to the strong-account cutoff). The last column,
   **Assign to**, is an owner dropdown on *every* row: allocate any account to
   anyone (or unassign), which records a manual move. Because the whole app groups
   by **effective owner** (current owner + your accepted/manual moves), an
   allocation here updates the **Overview** book heatmaps and attention flags
   immediately — assign a strong-but-unallocated account and it leaves that card
   and joins the new owner's book. When the balancer suggests a move, that owner
   sits at the top of the same dropdown marked "suggested" (picking it accepts,
   preserving the reason), the control is tinted, and a tiny **dismiss** link
   rejects it — one control, no separate accept/reject buttons or Moves tab. The
   **Suggested move** filter chip narrows to the pending suggestions. Nothing is
   written to a CRM — Export is the hand-off.
5. **Export** — every approved change (accepted suggestion or manual assignment),
   with a per-row **Dismiss** to drop one without leaving the tab (it reverts the
   account). `actions.csv` is the hand-off to the CRM. **This app never writes to
   your CRM.**

Point them at the Calibrate panel for anything that looks off: a segment routing
nothing usually means capacity, and a rep with implausible misfits usually means
the boundary. Re-running `suggest_moves.py` from the CLI does the same thing and
refines around decisions already made; `--reset` starts over.

**Close with the privacy note**: activity is counts and dates only, per owning
rep per account — no subjects, no transcripts, no bodies — and nothing leaves
the user's machine.
