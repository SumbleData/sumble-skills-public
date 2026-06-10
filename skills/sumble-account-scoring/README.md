# Sumble Account Scoring Skill

An **Agent Skill** that turns your ICP and GTM motion into a working
**account-scoring web app**. It interviews you about your ideal customer,
pulls signal data from Sumble (via the [Sumble MCP server](https://docs.sumble.com/api/mcp)
and the public API), optionally folds in your own first-party data
(CRM intent, product usage, engagement), and generates a self-contained,
**zero-dependency** Python + HTML/JS app you run locally and tune with sliders.

The slider-driven workflow mirrors the
[approach Sumble uses internally](https://blog.sumble.com/how-sumble-scores-your-accounts)
to build customer scoring models — generalised so any account team can
onboard their own.

This skill follows the cross-tool [Agent Skills](https://agentskills.io)
standard, so the **same folder works in Claude Code, OpenAI Codex, and Cursor** —
only the install location and how you trigger it differ (see
[Install & run](#install--run)).

## What you get

After running the skill you'll have, at `account_scoring/<your-company>/`:

```
app.py                          stdlib http.server — NO pip install, NO deps
account-scoring-weights.json    signals, weights, p99s, data-source metadata
data.csv                        the scored calibration sample (Sumble + 1P)
score.csv                       ranked, per-signal contribution view
score_accounts.py               portable scorer to run the model on any list
static/                         the UI: sliders, table, per-row breakdown
README.md                       how to run this specific app
```

Start the server, open `http://localhost:8001`, drag sliders, watch the
ranking re-sort in real time. Click any row to see exactly which signals
drive its score — and each signal deep-links into Sumble.

## What you need (all three tools)

- One of: **Claude Code**, **OpenAI Codex CLI**, or **Cursor**.
- A **Sumble account with API access** — sign up at https://sumble.com,
  then grab your API key at https://sumble.com/account.
- The **Sumble MCP server** connected in your agent — https://docs.sumble.com/api/mcp.
- **Python 3.10+** (only to run the generated app — the app itself needs nothing else).

## Install & run

### With `npx` (recommended)

Install the skill with `npx skills` (ships with [Node.js](https://nodejs.org));
the CLI detects supported agents and installs into the agent you choose.

```bash
npx skills add SumbleData/sumble-skills --skill sumble-account-scoring
```

To install globally for a specific agent without prompts:

```bash
npx skills add SumbleData/sumble-skills --skill sumble-account-scoring -g -a codex -y
npx skills add SumbleData/sumble-skills --skill sumble-account-scoring -g -a claude-code -y
```

### Without `npx` (no Node, no git needed)

A skill is just a folder — you can install it by hand:

1. Download this repo as a ZIP:
   [github.com/SumbleData/sumble-skills → Code → Download ZIP](https://github.com/SumbleData/sumble-skills/archive/refs/heads/main.zip),
   then unzip it.
2. Copy the `skills/sumble-account-scoring` folder into your agent's skills
   directory (`~` is your home folder; create the directory if it doesn't exist):
   - **Claude Code:** `~/.claude/skills/sumble-account-scoring`
   - **OpenAI Codex:** `~/.codex/skills/sumble-account-scoring`
   - **Cursor:** `~/.cursor/skills/sumble-account-scoring`

### Run it

Start a new agent session, then run `/sumble-account-scoring` in Claude Code or
ask Codex/Cursor to **"use the sumble-account-scoring skill."**

## How it works

The agent walks you through a short, scripted interview (your company, your
ICP, your CRM list and customers), pulls the right Sumble data, calibrates
weights against your closed-won accounts, and writes the app. Everything is
deterministic — the same answers and the same data produce the same app.

The generated `app.py` is identical across companies; all the
per-company customisation lives in `account-scoring-weights.json` and
`data.csv`. To score a much larger list once weights are tuned, hand
`account-scoring-weights.json` to `score_accounts.py` (runs anywhere with
Python and a Sumble API key).

## License

MIT.
