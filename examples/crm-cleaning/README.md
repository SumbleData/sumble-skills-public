# Example: CRM cleaning (Sumble's own CRM)

A real, runnable example of what the [`sumble-crm-cleaning`](../../skills/sumble-crm-cleaning) skill produces
— run against Sumble's own Salesforce (1,236 accounts, ~10 minutes, ~5 Sumble
API credits per account). Review duplicate clusters and hierarchy gaps, pick a
primary per duplicate, and export the change list.

**▶ Live demo: https://crm-cleaning-demo.sumble.com/**

> ## ⚠️ The owner names and customer flags here are FICTITIOUS
>
> The **accounts, duplicate clusters, hierarchy findings, and Sumble matches are
> real** output from the run. But the **owner names and `is_customer` flags are
> fabricated** (regenerated deterministically by `sanitize_findings.py`), the
> **opportunity counts have been removed**, and the CRM record links point into
> a private Salesforce — so they won't resolve for you. **Do not read any
> account, owner, or footprint number here as a real Sumble sales fact.**

## Run it

```bash
python3 app.py        # then open http://localhost:8002
```

Stdlib only — no `pip install`, no virtualenv. Needs Python 3.10+. Override the
port with `python3 app.py 9002` or `PORT=9002 python3 app.py`.

## What you're looking at

- **Duplicates** — 12 clusters of CRM accounts that resolve to the *same* Sumble
  organization (the only duplicate evidence the skill uses — no fuzzy name
  matching). Includes pairs no name matcher would catch: Synopsys + BlackDuck
  (acquisition), Wordpress VIP + A8c (both Automattic — hover the "+N" chip on
  the match line to see the alternate names/domains that explain it). The tab
  splits into three sub-tabs by how hard each cluster is to resolve:
  **Multiple owners** (different reps own the records — needs manual review),
  **Split activity** (one owner, history on more than one record — likely merge
  candidates), and **Concentrated** (one owner, history on at most one record —
  the obvious delete case). Each record shows its CRM footprint (contacts and
  activities); pick one **Primary** and the others default to **Merge**, or
  flip any to **Delete**.
- **Hierarchy gaps** — 17 missing parent links the org graph knows about
  (GitHub → Microsoft, Wiz → Google, HashiCorp → IBM, …) with the ancestor chain
  shown. A couple (Boomi → Dell) reflect since-divested ownership — exactly what
  the accept/reject review is for.
- **Parents not in CRM** — 26 parent companies missing entirely, grouped with
  the child accounts already present, in two sub-tabs: **Parent/sub roll-ups**
  (19 conventional corporate parents) and **PE roll-ups** (7 private-equity
  firms — Thoma Bravo, Francisco Partners, Vista, … — kept separate because a
  buyout firm is rarely a sellable parent account). Skill runs *exclude* PE
  parents by default; this demo opts in so you can see the sub-tab.
- **Unmatched** — 4 accounts Sumble couldn't resolve; usually shells or typos.

Then **Export actions.csv** for the change list (`merge` / `delete` /
`set_parent` / `create_parent_and_link` rows keyed by CRM account id).

## What's here

| File | What it is |
|---|---|
| `app.py` | The zero-dependency review app (stdlib `http.server`). |
| `findings.json` | Everything the app renders — real findings, sanitized owners/flags, opps removed. |
| `sanitize_findings.py` | Regenerates `findings.json` from a real run with the fabricated owners/flags. |
| `static/` | The UI. |

`decisions.json` and `actions.csv` are written as you review (gitignored).

## Build this against your own CRM

Install the skill and run it — the interview takes a few minutes:

```bash
npx skills add SumbleData/sumble-skills-public --skill sumble-crm-cleaning
```

The method is written up in
[Clean your CRM against an org graph](../../skills/sumble-crm-cleaning/articles/01-clean-your-crm-against-the-org-graph.md).
