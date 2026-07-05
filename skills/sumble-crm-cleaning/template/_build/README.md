# `_build/` — CRM-cleaning pipeline internals

Three scripts, run in order, all taking `--raw <output_root>/_raw`:

1. `fetch_orgs.py` — match `accounts.csv` to Sumble orgs via
   `POST /v6/organizations` (attributes only, no entity selections), then
   resolve non-CRM ancestor orgs by Sumble id (`MAX_PARENT_HOPS = 3`).
2. `analyze.py` — pure, deterministic detection. Writes
   `<output_root>/findings.json` + `findings.csv`.

(`set_api_key.py` / `set_api_key.sh` save the Sumble API key to
`~/.config/sumble/api_key`, chmod 0600 — shared with the other Sumble skills.)

## `_raw/accounts.csv` (the input the agent writes in Stage 1)

| column | required | notes |
|---|---|---|
| `crm_account_id` | yes | CRM/Salesforce account id — the join key for every finding |
| `name` | yes | account name (used for Sumble matching) |
| `domain` | yes* | website domain/URL (*strongly recommended — the strongest Sumble-match signal) |
| `parent_crm_id` | no | the CRM's OWN parent link (SF `ParentId`); enables conflict detection and suppresses already-correct links |
| `owner` | no | rep/owner name or id; drives the survivor suggestion |
| `is_customer` | no | 1/true for customers; drives the survivor suggestion |
| `created_date` | no | ISO date; tiebreak for the survivor suggestion (older wins) |
| `contact_count` | no | CRM contacts on the account; drives the survivor suggestion + shown on duplicate cards |
| `opportunity_count` | no | CRM opportunities on the account; same |
| `activity_count` | no | CRM activities (tasks + events + calls); same |

The three `*_count` columns are read at **analyze time** (keyed by
`crm_account_id`), so adding or refreshing them only requires re-running
`analyze.py` — no re-fetch, no credits.

## `_raw/accounts_meta.csv` (optional display-only sidecar)

Extra CRM metadata for the review UI, keyed by `crm_account_id`. Never used
as detection evidence — `analyze.py` merges it into each account payload as
`crm_city` / `crm_state` / `crm_country` / `crm_linkedin_url` /
`crm_last_modified`, and the app shows a CRM-location column, a LinkedIn
link, and the last-modified date. All columns optional:
`crm_account_id, city, state, country, linkedin_url, last_modified`.
Adding or editing it only requires re-running `analyze.py` (no re-fetch,
no credits).

## `_raw/config.json`

```json
{
  "company": "Acme",
  "checks": ["duplicates", "parent_sub"],
  "crm_url_template": "https://acme.lightning.force.com/lightning/r/Account/{id}/view",
  "crm_source": "salesforce Account export, 2026-06-11",
  "include_pe_parents": false
}
```

`crm_url_template` (optional): the CRM's record URL pattern; `{id}` is
replaced with each account's CRM id to produce a `crm_url` per account
(linked from every account name in the UI, plus a `crm_url` column in
`findings.csv`). Omit → names render unlinked.

`include_pe_parents` (optional, default `false`): private-equity firms (org
tag `is_private_equity_firm`) are NOT suggested as parents by default — see
"Parent/subsidiary findings" below. `true` surfaces them, flagged
`parent_org.is_pe_firm` so the UI splits them into a "PE roll-ups"
sub-tab of the Parents-not-in-CRM tab.

## `_raw/org_alternates.json` (optional display-only sidecar)

Alternate names/domains Sumble knows for matched orgs, keyed by Sumble org
id: `{"<org_id>": {"name_alternates": [...], "url_alternates": [...]}}`.
`analyze.py` merges them into account payloads
(`sumble_name_alternates` / `sumble_url_alternates`) and the UI shows them on
each finding's "Sumble match:" line — clarifying WHY accounts resolved to the
same org. Never used as detection evidence. The public `/v6/organizations`
endpoint does not expose alternates yet, so this file is populated
out-of-band (e.g. from Sumble-internal data); absent → no-op. Adding or
editing it only requires re-running `analyze.py` (no re-fetch, no credits).

## Policy constants (in the scripts, not per-run choices)

| constant | value | where |
|---|---|---|
| `BATCH` | 250 orgs/call | fetch_orgs.py |
| `MAX_PARENT_HOPS` | 3 ancestor levels resolved above the CRM's orgs | fetch_orgs.py |
| `MAX_ANCESTOR_DEPTH` | 6 — hierarchy-walk cycle guard | analyze.py |

## Duplicate evidence → confidence

| evidence | meaning | tier |
|---|---|---|
| `same_sumble_org` | both accounts resolve to one Sumble org | high |

`same_sumble_org` is the ONLY duplicate evidence: Sumble's matcher
(`POST /v6/organizations`) mapping two CRM accounts to the same org id. No
domain or name-similarity matching. Pairs already linked parent↔child in the
CRM are never duplicate evidence.
Survivor suggestion order: has owner > is customer > biggest CRM footprint
(`contact_count + opportunity_count + activity_count`) > most non-empty
fields > oldest `created_date` > lowest id.

### Duplicate resolution buckets (`category`)

Every duplicate cluster is tagged with a `category` (in `findings.json`, the
`dup_category` column of `findings.csv`, and per-bucket counts in
`meta.duplicate_categories`) so the reviewer can triage hard conflicts away
from trivial shell-merges. `categorize_cluster` (in `analyze.py`):

| category | rule | difficulty |
|---|---|---|
| `multi_owner` | ≥2 distinct (non-empty) `owner` values in the cluster | hard — decide who keeps the account before merging |
| `split_activity` | one owner (or none) **and** CRM footprint on >1 record | easy-ish — merge so no relationship history is lost |
| `concentrated` | one owner (or none) **and** footprint on ≤1 record | easy — keep the populated record, drop the shells |

Owner matching is case-insensitive; empty owners are ignored. Footprint per
record = `contact_count + opportunity_count + activity_count`. Priority:
`multi_owner` wins over the activity split. **Without the `*_count` columns,
footprint is 0 everywhere, so single-owner clusters all fall to
`concentrated`** — pull the count columns to separate `split_activity`.
Findings are ordered hardest bucket first (`multi_owner` → `split_activity`
→ `concentrated`), then by cluster size, then by first CRM id.

## Parent/subsidiary findings

For each matched account, walk its Sumble `parent_id` chain (nearest first):

- First ancestor that is another CRM account →
  - CRM parent unset → `missing_parent_link` (high if direct parent, medium
    beyond one hop)
  - CRM parent set but NOT in the Sumble chain → `parent_conflict` (medium)
  - CRM parent already in the chain → consistent, no finding
- No ancestor in the CRM but a Sumble parent exists → `parent_not_in_crm`
  (info), grouped one finding per missing parent org with all its CRM children.

### PE-firm parents (excluded by default)

A parent that is a private-equity firm (org tag `is_private_equity_firm`,
fetched on parent lookups) is rarely a sellable parent account — portfolio
companies run as independent businesses. So by default `analyze.py` skips PE
ancestors when picking the `parent_not_in_crm` group parent: the child groups
under the highest **non-PE** resolvable ancestor instead, and a child whose
only resolvable ancestors are PE firms is dropped (distinct PE orgs skipped
as parents are counted in `meta.pe_parents_excluded`, noted in the analyze
summary). With
`"include_pe_parents": true`, PE parents are kept and flagged
(`parent_org.is_pe_firm`, `meta.pe_parents`); the review UI then shows them
under a "PE roll-ups" sub-tab, separate from conventional roll-ups.

## Credit cost

`fetch_orgs.py` requests 4 paid attributes (`employee_count`,
`headquarters_country`, `parent_id`, `subsidiary_ids`) →
**~5 credits per matched account** (1 base + 4), plus ~6 per resolved
ancestor org (the same set + `tags`, for the PE-firm check — ancestors are
usually a small fraction of the account count).
