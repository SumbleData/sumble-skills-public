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

The skill is one folder (`sumble-account-scoring/`) containing `SKILL.md`
and `template/`. Unzip it, drop it in the right place for your tool, then
trigger it.

### Claude Code

```bash
# personal (all projects):
mkdir -p ~/.claude/skills
cp -r sumble-account-scoring ~/.claude/skills/
```

Start a new Claude Code session, then type:

```
/sumble-account-scoring
```

### OpenAI Codex CLI

```bash
# personal (all projects):
mkdir -p ~/.codex/skills
cp -r sumble-account-scoring ~/.codex/skills/
```

Start Codex and ask it to **"use the sumble-account-scoring skill"** (Codex
loads skills on demand when they're relevant).

### Cursor

```bash
# project-scoped, from your project root:
mkdir -p .cursor/skills
cp -r sumble-account-scoring .cursor/skills/
```

In Cursor's Agent (chat) panel, ask it to **"follow the sumble-account-scoring
skill"**. If your Cursor build doesn't pick it up automatically, open the
`sumble-account-scoring` folder in Cursor and tell the Agent:
*"Read SKILL.md in this folder and follow it to build a Sumble account score."*

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
