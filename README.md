# Sumble Skills

Open, self-contained **Agent Skills** that turn [Sumble](https://sumble.com)'s
account intelligence — org charts, tech stacks, hiring signals, funding — into
working GTM tools you build by talking to a coding agent.

## The bigger goal

Most GTM data sits in a dashboard nobody acts on. The goal of this repo is the
opposite: give RevOps, marketing, and sales teams **skills they can run inside
the coding agent they already use** (Claude Code, OpenAI Codex, or Cursor) to
build their *own* models — account scores, lead scores, whitespace lists —
calibrated to their ICP and their closed-won deals, in an afternoon.

The scoring skills produce a **self-contained, zero-dependency Python + HTML/JS
app** you run locally and tune with sliders, plus a **portable config + scorer**
you can lift into a warehouse or CRM to run at scale. No black box: every signal
deep-links back to the people, teams, and jobs behind it, and the scoring math
is fully documented so a data team can re-implement it anywhere.

These skills follow the cross-tool [Agent Skills](https://agentskills.io)
standard — the **same folder works in all three tools**; only where you put it
and how you trigger it differ.

## Skills available today

| Skill | What it does | Guide |
|---|---|---|
| [`sumble-mcp`](skills/sumble-mcp) | Use the **Sumble MCP** itself. Gives agents the tool sequencing, query rules, workflow patterns, and credit guardrails for account research, prospecting, and list-building. | [MCP docs](https://docs.sumble.com/api/mcp) |
| [`sumble-account-research`](skills/sumble-account-research) 🚧 | Deep-research and prospect **a specific account** (or a few). Loads your company profile, collects internal context (call notes, pipeline stage, existing business, goals), rebuilds the account's Sumble overview (tech, teams, people, headcount, hiring signals, ICP fit), then recommends teams to focus on for first land or expansion, who to get to, and drafted outreach. No list? It surfaces high-fit accounts or accounts with interesting recent signals. | — |
| [`sumble-account-scoring`](skills/sumble-account-scoring) | Score **your own accounts** *and* find **net-new whitespace** — one skill, pick the objective. Interviews you about your ICP, calibrates weights against your closed-won customers, builds a tunable scoring app + portable scorer, and in whitespace mode ranks Sumble's universe by your ICP minus the accounts you already own (subsidiaries of existing accounts flagged land-and-expand). | [Part 1 — the method](skills/sumble-account-scoring/articles/01-account-score-should-tell-a-rep-what-to-do.md) · [Part 2 — build it](skills/sumble-account-scoring/articles/02-build-an-account-score-you-can-prospect-from.md) |
| [`sumble-crm-cleaning`](skills/sumble-crm-cleaning) | Clean **your CRM** against Sumble's org graph. Matches every account to a Sumble organization, surfaces duplicate accounts (same org, two records) and missing or conflicting parent/subsidiary links, and builds a review app where you accept/reject each finding and export the change list. | [The article](skills/sumble-crm-cleaning/articles/01-clean-your-crm-against-the-org-graph.md) |
| [`sumble-people-scoring`](skills/sumble-people-scoring) 🚧 | Score **people / leads** — both the contacts already in your CRM and the people you've never met at your target accounts. One ranked list per account drives outbound, lead routing, lead prioritization, and campaign audiences; emits a production scorer for an enriched CRM. | [The method & use cases](skills/sumble-people-scoring/articles/01-people-scoring-use-cases.md) |
| [`sumble-territory-planning`](skills/sumble-territory-planning) 🚧 | Plan and rebalance **territories**. Companion to account scoring: takes your account strength, your CRM ownership, and per-rep×account activity (calendar, call recorders, CRM email) and shows how evenly the books are split, which accounts nobody is working, which sit in the wrong segment, which are unallocated or owned twice — then proposes owner changes you accept or reject and export as an `actions.csv`. | — |

A common workflow: tune a model on your accounts with **sumble-account-scoring**,
run it in whitespace mode to surface net-new companies, prioritize the
individual contacts with **sumble-people-scoring**, and use
**sumble-territory-planning** to check the right reps are actually on the
accounts that scored well.

> 🚧 **`sumble-people-scoring` is still being refined** — the method article is
> written and the skill is usable end-to-end; the step-by-step build guide is
> coming. **`sumble-territory-planning` is new** — usable end-to-end, with no
> worked example or method article yet. `sumble-account-scoring` is stable.

### See it in action

Each skill ships a real, runnable example next to it, under
`skills/<skill>/example/`.

**▶ Account scoring — live demo: https://account-scoring-demo.sumble.com/**

[`skills/sumble-account-scoring/example`](skills/sumble-account-scoring/example)
is a real, runnable app the account-scoring skill produced — `python app.py`,
drag sliders, click through. The account universe is real public companies; the
"gold" (customer) flags in it are **fictitious and illustrative**, not anyone's
real customer list.

**▶ CRM cleaning — live demo: https://crm-cleaning-demo.sumble.com/**

[`skills/sumble-crm-cleaning/example`](skills/sumble-crm-cleaning/example) is the
CRM-cleaning skill run against Sumble's own Salesforce — `python3 app.py`, then
review real duplicate clusters and hierarchy gaps (owner names and customer
flags are fictitious, opportunity counts removed).

## What you need

- One of: **Claude Code**, **OpenAI Codex CLI**, or **Cursor**.
- A **Sumble account with API access** — sign up at [sumble.com](https://sumble.com), then grab your key at [sumble.com/account](https://sumble.com/account).
- The **Sumble MCP server** connected in your agent — [docs.sumble.com/api/mcp](https://docs.sumble.com/api/mcp).
- **Python 3.10+** to run the generated app (the app itself needs nothing else — no `pip install`).

## Install

### `npx skills`

Run one command for the skill you want. The `skills` CLI detects supported
agents and installs into the agent you choose.

```bash
npx skills add SumbleData/sumble-skills-public --skill sumble-mcp
npx skills add SumbleData/sumble-skills-public --skill sumble-account-scoring
npx skills add SumbleData/sumble-skills-public --skill sumble-people-scoring
npx skills add SumbleData/sumble-skills-public --skill sumble-territory-planning
```

To install globally for a specific agent without prompts, add `-g -a <agent>
-y`:

```bash
npx skills add SumbleData/sumble-skills-public --skill sumble-mcp -g -a codex -y
npx skills add SumbleData/sumble-skills-public --skill sumble-account-scoring -g -a claude-code -y
```

List or install the whole repo:

```bash
npx skills add SumbleData/sumble-skills-public --list
npx skills add SumbleData/sumble-skills-public --skill '*'
```

Direct GitHub path installs also work if you want each skill to have its own
URL-shaped command:

```bash
npx skills add https://github.com/SumbleData/sumble-skills-public/tree/main/skills/sumble-mcp
npx skills add https://github.com/SumbleData/sumble-skills-public/tree/main/skills/sumble-account-scoring
npx skills add https://github.com/SumbleData/sumble-skills-public/tree/main/skills/sumble-people-scoring
```

Start a new agent session after installing. In Codex, ask it to *"use the
sumble-account-scoring skill"* or *"use the sumble-mcp skill."* In Claude Code,
run `/sumble-account-scoring`, `/sumble-people-scoring`, or `/sumble-mcp`.

> Connect the Sumble MCP once per tool — see [docs.sumble.com/api/mcp](https://docs.sumble.com/api/mcp).
> Each skill's own `README.md` has a step-by-step, no-experience-needed walkthrough.

### Direct zip download

`sumble-account-research` is also published as a standalone zip, rebuilt
automatically on every push to `main` (see
`.github/workflows/build-skill-zips.yml`):

- [sumble-account-research.zip](https://github.com/SumbleData/sumble-skills-public/releases/download/skill-zips/sumble-account-research.zip)

## How a skill runs

The agent walks you through a short, scripted interview (your company, your ICP,
your account list), pulls the right Sumble data, calibrates against your
closed-won accounts, and writes the app at `account_scoring/<your-company>/`
(or `people_scoring/…`). Then:

```bash
cd account_scoring/<your-company>
python app.py        # open http://localhost:8001 — drag sliders, rankings update live
```

To score a much larger list once weights are tuned, hand the generated
`*-weights.json` to the included portable scorer (`score_accounts.py` /
`score_leads.py`) — it runs anywhere with Python and a Sumble API key.

## Learn the method

Each skill's written guide lives in an `articles/` folder next to the skill
itself.

The thinking behind the account-scoring skill (whitespace included) is a
two-part series in
[`skills/sumble-account-scoring/articles/`](skills/sumble-account-scoring/articles):

1. [An account score should tell a rep what to do — not just rank accounts](skills/sumble-account-scoring/articles/01-account-score-should-tell-a-rep-what-to-do.md)
2. [Build an account score you can prospect from — in an afternoon](skills/sumble-account-scoring/articles/02-build-an-account-score-you-can-prospect-from.md) *(includes the full scoring math and whitespace)*

The CRM-cleaning method is written up in
[`skills/sumble-crm-cleaning/articles/`](skills/sumble-crm-cleaning/articles):

1. [Clean your CRM against an org graph](skills/sumble-crm-cleaning/articles/01-clean-your-crm-against-the-org-graph.md)

The people-scoring method and its use cases live in
[`skills/sumble-people-scoring/articles/`](skills/sumble-people-scoring/articles):

1. [Your lead score only ranks people who already found you](skills/sumble-people-scoring/articles/01-people-scoring-use-cases.md) *(the method, plus the use-case catalog: outbound, routing, prioritization, campaigns, multi-threading, events, job-change plays)*

## License

MIT — see [LICENSE](LICENSE).
