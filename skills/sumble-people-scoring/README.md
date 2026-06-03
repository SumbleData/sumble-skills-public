# Sumble People Scoring Skill

> 🚧 **Work in progress.** This skill is usable but still being refined, and
> doesn't have a written guide yet. The [account-scoring](../sumble-account-scoring)
> and [whitespace](../sumble-account-whitespace) skills are stable.

An **Agent Skill** that turns your ideal-buyer profile into a working
**people / lead-scoring web app**. It interviews you about your ICP (job
functions + skills, pre-filled from your Sumble profile), builds a small
calibration sample from ~5 companies you name so the app is ready in minutes,
and generates a self-contained, **zero-dependency** Python + HTML/JS app you
run locally and tune with sliders. It also emits a production `score_leads.py`
that applies your calibrated weights to an entire enriched CRM of people.

Where the [account-scoring](../sumble-account-scoring) and
[whitespace](../sumble-account-whitespace) skills rank *companies*, this one
ranks *people* — the individual leads most worth contacting.

This skill follows the cross-tool [Agent Skills](https://agentskills.io)
standard, so the **same folder works in Claude Code, OpenAI Codex, and Cursor**.

## What you need

- One of: **Claude Code**, **OpenAI Codex CLI**, or **Cursor**.
- A **Sumble account + API key** — [sumble.com/account](https://sumble.com/account) — and the **Sumble MCP** connected ([docs.sumble.com/api/mcp](https://docs.sumble.com/api/mcp)).
- **Python 3.10+** to run the generated app (the app itself is zero-dependency).

## Install & run

Copy this `sumble-people-scoring` folder into your agent's skills directory,
then trigger it:

- **Claude Code** — `cp -r sumble-people-scoring ~/.claude/skills/`, then `/sumble-people-scoring`.
- **OpenAI Codex** — `cp -r sumble-people-scoring ~/.codex/skills/`, then "use the sumble-people-scoring skill".
- **Cursor** — `cp -r sumble-people-scoring .cursor/skills/`, then "follow the sumble-people-scoring skill".

See the repo [README](../../README.md) for full per-tool setup.

## License

MIT.
