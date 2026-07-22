# `_build/` — deterministic pipeline scripts (territory planning)

Same `spec.json` + same inputs → byte-identical `territory.csv` and proposals.
No RNG anywhere; every tie breaks on `org_id`. Policy constants live at the top
of `territory_lib.py`, not in the agent's judgment.

## Files

- **`territory_lib.py`** — the shared contract. Domain normalisation, the
  boundary-column resolver, size→segment mapping, activity roll-up, book-balance
  maths, and `TERRITORY_COLUMNS`. Every other script imports it, so the threshold
  the user confirms, the segments written to the sheet, and the moves proposed
  against them cannot drift. **It is also copied next to `app.py`** at generation
  time (it is stdlib-only), so the server and the pipeline share one definition
  of balance — the same role `score_sheet.py` plays in account-scoring.
- **`fetch_light.py`** — Path B pull: resolve CRM accounts against
  `POST /v6/organizations` and take `sumble_score`, `employee_count`, and
  firmographics. Also the Path A supplement (`--only-jf`) when the boundary needs
  a job function the scoring run never fetched. ≤200 orgs per batch, adaptively
  halved on failure down to a 20-org floor.
- **`calibrate_split.py`** — proposes the segment boundary and guesses each rep's
  segment. **Writes nothing**; prints JSON for the agent to render and confirm.
- **`build_plan.py`** — the confirmed answers → `territory-plan.json`. Validates
  the roster (every active rep needs a known segment) and warns about reps with
  no email, since those reps' accounts would all read "not worked".
- **`merge_territory.py`** — joins everything → `territory.csv` +
  `_raw/_territory_audit.json`.
- **`suggest_moves.py`** — writes `proposed_owner` / `proposal_reason` /
  `proposal_status` back into `territory.csv`.
- **`lookup.py`**, **`set_api_key.py`**, **`set_api_key.sh`**, **`sumble_v6.py`** —
  copied verbatim from `sumble-account-scoring`. Same key resolution, same
  endpoint helpers.

## Pipeline order

1. **Interview** — agent writes `_raw/spec.json`, `ownership.csv`, `reps.csv`,
   `activity/*.csv`, optionally `accounts.csv` + `pipeline.csv`.
2. **Fetch** (Path B, or a Path A job-function supplement) —
   `python3 fetch_light.py --raw _raw` → `_raw/sumble_light.csv`.
3. **Calibrate** (only when the user has no hard-line rule) —
   `python3 calibrate_split.py --raw _raw`, confirm, write the result into
   `spec.boundary.thresholds`.
4. **Plan** — `python3 build_plan.py --raw _raw` → `territory-plan.json`.
5. **Merge** — `python3 merge_territory.py --raw _raw` → `territory.csv`.
6. **Moves** — `python3 suggest_moves.py --dir <root>`.

## `spec.json` schema

```json
{
  "schema_version": 1,
  "company": {"name": "Acme", "url": "acme.com", "folder_slug": "acme"},
  "score_source": {"kind": "custom", "path": "/abs/path/to/score.csv"},
  "segments": [{"key": "commercial", "label": "Commercial", "order": 1},
               {"key": "enterprise", "label": "Enterprise", "order": 2}],
  "boundary": {
    "metric": "total_employees",
    "column": null,
    "label": "Total employees",
    "thresholds": [{"segment": "enterprise", "min": 1000}]
  },
  "activity": {"window_days": 90,
               "sources": ["google_calendar", "fireflies", "salesforce_email"],
               "company_domain": "acme.com"},
  "balance_categories": ["allocated", "unallocated"],
  "whitespace_top_n": 50
}
```

`score_source.kind` is `custom` (an account-scoring `score.csv`, read from
`path`) or `sumble` (read `_raw/sumble_light.csv`).

### `boundary.metric` — three forms

| Form | Column resolved to | Notes |
|---|---|---|
| `total_employees` | `employee_count_int` | the safe default |
| `jf_people:<Display Name>` | `jf_people`, else `<slug>_people` | must be a **broad parent** function (`Engineer`, `Sales`), never a granular child — see the density guard |
| `custom:<column>` | that column verbatim | a value the user supplied by CSV |

`thresholds` is a list of `{segment, min}`, **inclusive and applied
highest-first**: an account exactly on the line lands in the LARGER segment,
which is what "enterprise is 1,000+" means. Anything below every threshold falls
to the lowest-`order` segment.

## Input CSV schemas (agent-written, under `_raw/`)

| File | Columns |
|---|---|
| `ownership.csv` | `crm_account_id,name,domain,owner,owner_email,owner_is_queue,is_customer` |
| `reps.csv` | `name,email,segment,is_rep,capacity` |
| `activity/<source>.csv` | `source,rep_email,account_domain,kind,ts` — `kind` ∈ `meeting`, `call`, `email_out`, `email_in`; one row per event, never pre-aggregated |
| `accounts.csv` (Path B) | `crm_account_id,name,domain` |
| `pipeline.csv` (optional) | `domain,pipeline_value` |

## Policy constants (`territory_lib.py`)

- **Balance labels** — CV ≤ `0.15` balanced, ≤ `0.35` uneven, else imbalanced.
  Measured on **total account score** per rep, not account count; a rep with 40
  weak accounts does not have a bigger book than one with 15 strong ones. CV is
  scale-free so the same thresholds hold for any team size.
- **Balance categories** — `allocated` + `unallocated`. Customers are excluded:
  a renewal book is not a workload to rebalance.
- **Move policy** — stop at CV `< 0.10`; never move more than `15%` of a
  segment's accounts; whitespace routing depth `50`.
- **Customers and moves** — customers are eligible for a **misfit** move but not
  for **rebalancing**. A misfit move is a correctness fix (an enterprise account
  sitting with a commercial rep belongs with the enterprise team, customer or
  not); rebalancing is an optimisation, and churning a customer to even out a
  spreadsheet is the move that costs a renewal. The no-activity constraint
  applies to both.
- **`MIN_ACCOUNTS_FOR_SEGMENT_GUESS = 3`** — below this, a rep's median account
  size is not evidence of which segment they sell, so the guess is `unknown`.
- **`MAX_ZERO_FRACTION_BELOW = 0.30`** — the density guard. If more than 30% of
  accounts below a proposed job-function boundary read **zero**, the metric is
  too granular: it is sorting on whether Sumble has data, not on company size.
  `calibrate_split.py` emits a warning telling the agent to offer a broader
  parent function or total employee count.
- **`HUMAN_THRESHOLDS`** — `50 … 50,000`. Boundaries snap to these so the rule
  is one a sales leader can state out loud. A 40-account sample does not support
  "1,043 employees".
- **`FREEMAIL_DOMAINS`** — dropped before activity matching, along with the
  seller's own domain, so internal meetings and personal mail never mark an
  account "worked".
- **`OUTBOUND_KINDS`** — `meeting`, `call`, `email_out`. Inbound email is
  counted and displayed but does not clear the "not worked" flag on its own:
  that is the prospect doing the work.

## Boundary calibration

`calibrate_split.py` picks its own method:

- **Supervised** — two segments AND the reps' segments are already known AND ≥10
  owned accounts match. Sweeps every observed size and picks the threshold
  leaving the fewest accounts owned by a rep from the other segment. *The reps'
  actual behaviour defines the line.*
- **k-means on log(size)** — otherwise (segments unknown, or >2 segments).
  Company sizes are log-distributed, so clustering in log space finds the real
  market gap instead of being dragged by one huge account. Deterministic seeding
  at evenly spaced quantiles; thresholds sit at the geometric midpoint between
  adjacent centres.

**Snapping is misfit-aware on the supervised path.** Rounding 4,252 to the
*nearest* human number (5,000) would reclassify every account in between, so
each round candidate is scored on the same misfit count the sweep used and the
best one wins, ties broken by closeness to the optimum. The unsupervised path has
no error signal, so it snaps to nearest.

## Double allocation

Grouped by Sumble `org_id` — which is the whole point. Two CRM records with
different names and different domains that resolve to the same organisation are
two reps working one company, and no name- or domain-matching would have found
it. The canonical owner is whoever has the most activity (ties alphabetical);
the rest land in `other_owners`. These accounts are **excluded from rebalancing**
until the duplicate is resolved, since otherwise they'd be counted against two
books at once.

## Re-run semantics

`suggest_moves.py` preserves the user's decisions. `accepted` and `manual`
moves are treated as **already applied** when measuring balance; `rejected`
rows are never re-proposed; only stale `suggested` rows are cleared and
recomputed. So re-running after a review session refines the plan instead of
undoing it. `--reset` discards everything, including user decisions.
