# Sumble Account Whitespace Skill

An **Agent Skill** that ranks **net-new prospects** — the organizations in
Sumble's universe that match your ICP but are **not** in your CRM. It pulls
signal data from Sumble (via the [Sumble MCP server](https://docs.sumble.com/api/mcp)
and the public API), uses your uploaded CRM list to exclude accounts you
already have, and generates a self-contained, **zero-dependency** Python +
HTML/JS app you run locally and tune with sliders.

It's the companion to `/sumble-account-scoring`: build a tuned model on your
own accounts there, then point the same kind of model at the companies you're
*not* selling to yet. This skill is standalone — it doesn't require or share
state with the scoring skill. The main view is the whitespace pool; if you
upload a CRM, subsidiaries of your CRM accounts get their own **Subsidiaries**
tab. There's no evaluation tab and no first-party signal columns (you have no
1P data for accounts you've never engaged).

This skill follows the cross-tool [Agent Skills](https://agentskills.io)
standard, so the **same folder works in Claude Code, OpenAI Codex, and Cursor** —
only the install location and how you trigger it differ (see
[Install & run](#install--run)).

## What you get

After running the skill you'll have, at `account_whitespace/<your-company>/`:

```
app.py                            stdlib http.server — NO pip install, NO deps
account-whitespace-weights.json   signals, weights, p99s, data-source metadata
data.csv                          one row per Sumble org_id in the whitespace pool
score_accounts.py                 portable public-API scorer for larger lists
static/                           the UI: sliders, table, per-row breakdown
README.md                         how to run this specific app
```

Start the server, open `http://localhost:8001`, drag sliders, watch the
ranking re-sort in real time. Click any row to see which signals drive its
score — and each signal deep-links into Sumble.

## What you need (all three tools)

- One of: **Claude Code**, **OpenAI Codex CLI**, or **Cursor**.
- A **Sumble account with API access** — sign up at https://sumble.com,
  then grab your API key at https://sumble.com/account.
- The **Sumble MCP server** connected in your agent — https://docs.sumble.com/api/mcp.
- **Python 3.10+** (only to run the generated app — the app itself needs nothing else).
- A **CRM account list** (CSV with `name` and `domain`) to subtract your
  existing accounts from the net-new pool.

## Install & run

The skill is one folder (`sumble-account-whitespace/`) containing `SKILL.md`
and `template/`. Unzip it, drop it in the right place for your tool, then
trigger it.

### Claude Code

```bash
mkdir -p ~/.claude/skills
cp -r sumble-account-whitespace ~/.claude/skills/
```

Start a new Claude Code session, then type:

```
/sumble-account-whitespace
```

### OpenAI Codex CLI

```bash
mkdir -p ~/.codex/skills
cp -r sumble-account-whitespace ~/.codex/skills/
```

Start Codex and ask it to **"use the sumble-account-whitespace skill"**.

### Cursor

```bash
# from your project root:
mkdir -p .cursor/skills
cp -r sumble-account-whitespace .cursor/skills/
```

In Cursor's Agent (chat) panel, ask it to **"follow the sumble-account-whitespace
skill"**. If it isn't picked up automatically, tell the Agent:
*"Read .cursor/skills/sumble-account-whitespace/SKILL.md and follow it."*

## How it works

The agent walks you through a short interview (company URL, ICP confirmation,
CRM upload, universe filters, pool size), ranks Sumble's universe by your ICP,
removes the accounts already in your CRM, and writes the app. The generated
`app.py` is identical across companies; all customisation lives in
`account-whitespace-weights.json` and `data.csv`. To score a larger candidate
list, hand the weights JSON to `score_accounts.py` (runs anywhere with Python
and a Sumble API key).

## License

MIT.
