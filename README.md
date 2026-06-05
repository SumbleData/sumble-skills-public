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
| [`sumble-account-scoring`](skills/sumble-account-scoring) | Score **your own accounts** *and* find **net-new whitespace** — one skill, pick the objective. Interviews you about your ICP, calibrates weights against your closed-won customers, builds a tunable scoring app + portable scorer, and in whitespace mode ranks Sumble's universe by your ICP minus the accounts you already own (subsidiaries of existing accounts flagged land-and-expand). | [Part 1 — the method](articles/01-account-score-should-tell-a-rep-what-to-do.md) · [Part 2 — build it](articles/02-build-an-account-score-you-can-prospect-from.md) |
| [`sumble-people-scoring`](skills/sumble-people-scoring) 🚧 | Score **people / leads**. Ranks the individual contacts most worth reaching out to, and emits a production scorer for an enriched CRM. | *(work in progress)* |

A common workflow: tune a model on your accounts with **sumble-account-scoring**,
run it in whitespace mode to surface net-new companies, then prioritize the
individual contacts with **sumble-people-scoring**.

> 🚧 **`sumble-people-scoring` is a work in progress** — it's usable but still
> being refined, and doesn't have a written guide yet. `sumble-account-scoring`
> is stable.

### See it in action

**▶ Live demo: https://sumble-account-scoring-demo-878803865730.us-west1.run.app**

[`examples/account-scoring-sumble`](examples/account-scoring-sumble) is a real,
runnable app the account-scoring skill produced — `python app.py`, drag sliders,
click through. The account universe is real public companies; the "gold"
(customer) flags in it are **fictitious and illustrative**, not anyone's real
customer list.

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
npx skills add SumbleData/sumble-skills --skill sumble-mcp
npx skills add SumbleData/sumble-skills --skill sumble-account-scoring
npx skills add SumbleData/sumble-skills --skill sumble-people-scoring
```

To install globally for a specific agent without prompts, add `-g -a <agent>
-y`:

```bash
npx skills add SumbleData/sumble-skills --skill sumble-mcp -g -a codex -y
npx skills add SumbleData/sumble-skills --skill sumble-account-scoring -g -a claude-code -y
```

List or install the whole repo:

```bash
npx skills add SumbleData/sumble-skills --list
npx skills add SumbleData/sumble-skills --skill '*'
```

Direct GitHub path installs also work if you want each skill to have its own
URL-shaped command:

```bash
npx skills add https://github.com/SumbleData/sumble-skills/tree/main/skills/sumble-mcp
npx skills add https://github.com/SumbleData/sumble-skills/tree/main/skills/sumble-account-scoring
npx skills add https://github.com/SumbleData/sumble-skills/tree/main/skills/sumble-people-scoring
```

Start a new agent session after installing. In Codex, ask it to *"use the
sumble-account-scoring skill"* or *"use the sumble-mcp skill."* In Claude Code,
run `/sumble-account-scoring`, `/sumble-people-scoring`, or `/sumble-mcp`.

> Connect the Sumble MCP once per tool — see [docs.sumble.com/api/mcp](https://docs.sumble.com/api/mcp).
> Each skill's own `README.md` has a step-by-step, no-experience-needed walkthrough.

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

The thinking behind the account-scoring skill (whitespace included) is written up
as a two-part series in [`articles/`](articles):

1. [An account score should tell a rep what to do — not just rank accounts](articles/01-account-score-should-tell-a-rep-what-to-do.md)
2. [Build an account score you can prospect from — in an afternoon](articles/02-build-an-account-score-you-can-prospect-from.md) *(includes the full scoring math and whitespace)*

## License

MIT — see [LICENSE](LICENSE).
