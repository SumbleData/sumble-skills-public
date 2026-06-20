# CRM Cleaning — review app

Findings from matching your CRM account list against Sumble's organization
graph. Two kinds of problems are surfaced:

1. **Duplicates** — CRM accounts that look like the same company (same Sumble
   org, same domain, same/similar name).
2. **Hierarchy gaps** — accounts whose Sumble parent (or grandparent) is
   another CRM account, but the CRM has no parent link (or a conflicting one);
   plus parent companies missing from the CRM entirely.

## Run the app

```bash
python3 app.py
# open http://localhost:8002
```

No pip install, no venv — stdlib only, Python 3.10+. Custom port:
`python3 app.py 9002` or `PORT=9002 python3 app.py`.

## Reviewing

- For **hierarchy** and **parents-not-in-CRM** findings: **Accept** when the
  suggested change is right, **Reject** when it isn't, **Skip** to defer.
- For a **duplicate cluster** there is no accept/reject/skip — the per-record
  actions are the decision. Mark one record **Primary** (the survivor); the
  others then default to **Merge** (fold into the primary), and you switch any
  to **Delete** to remove it instead. Until a primary is picked only "Primary"
  is available (the suggested primary is hinted: owned > customer > biggest
  CRM footprint > most complete > oldest). **Not a duplicate** dismisses a
  false match. Every click saves to `decisions.json` immediately.
- Each duplicate cluster carries a **resolution bucket** (badge on the card +
  filter chips on the Duplicates tab), ordered hardest first:
  - **Multiple owners** — two or more reps own records in the cluster; decide
    who keeps the account before merging (the hard case).
  - **Split activity** — one owner, but CRM history (contacts/opps/activities)
    sits on more than one record; merge into the primary so none is lost.
  - **Concentrated** — one owner with history on a single record; keep it and
    drop the empty shells (the easy case).
  Work the easy buckets first and reserve the owner conflicts for last.
- **Export actions.csv** writes one row per CRM change implied by your
  accepted findings:
  - `merge` — fold `account_id` into `target_account_id`
  - `delete` — delete `account_id` (a duplicate flagged for removal)
  - `set_parent` — set `target_account_id` as the parent of `account_id`
  - `create_parent_and_link` — create the suggested parent account, then
    parent `account_id` under it

## Files

| File | What it is |
|---|---|
| `findings.json` | Everything the app shows (read-only; regenerate via `_build/analyze.py`) |
| `findings.csv` | Flat spreadsheet export of all findings (decision-independent) |
| `decisions.json` | Your accept/reject/skip choices, survivor picks, notes |
| `actions.csv` | The change list for your CRM admin, from accepted findings |
| `_raw/` | Inputs + raw API responses (accounts.csv, config.json, responses/) |

## Re-running

Data refresh (new CRM export → new findings; decisions for unchanged finding
ids are kept):

```bash
python3 _build/fetch_orgs.py --raw _raw
python3 _build/analyze.py  --raw _raw
```
