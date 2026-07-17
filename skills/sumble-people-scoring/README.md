# Sumble People Scoring Skill

> 🚧 **Work in progress.** This skill is usable end-to-end but still being
> refined. The method and use cases are written up in
> [articles/](articles/01-people-scoring-use-cases.md); the step-by-step build
> guide is coming. The [sumble-account-scoring](../sumble-account-scoring)
> skill (account scoring + whitespace) is stable.

An **Agent Skill** that turns your ideal-buyer profile into a working
**people / lead-scoring web app**. It interviews you about your ICP (job
functions + skills, pre-filled from your Sumble profile), builds a small
calibration sample from ~5 companies you name — pulled through Sumble's
unified `POST /v6/people` REST endpoint — so the app is ready in minutes,
and generates a self-contained, **zero-dependency** Python + HTML/JS app you
run locally and tune with sliders. An optional gold set (contacts on
closed-won deals) drives an Evaluation tab and a conservative regularized
weight fit. It also emits a `score.csv` superset sheet and a production
`score_leads.py` that applies your calibrated weights to an entire enriched
CRM of people.

Where the [sumble-account-scoring](../sumble-account-scoring) skill ranks
*companies* (your accounts and net-new whitespace), this one ranks *people* —
the individual leads most worth contacting.

This skill follows the cross-tool [Agent Skills](https://agentskills.io)
standard, so the **same folder works in Claude Code, OpenAI Codex, and Cursor**.

## What you need

- One of: **Claude Code**, **OpenAI Codex CLI**, or **Cursor**.
- A **Sumble account + API key** — [sumble.com/account](https://sumble.com/account) — and the **Sumble MCP** connected ([docs.sumble.com/api/mcp](https://docs.sumble.com/api/mcp)).
- **Python 3.10+** to run the generated app (the app itself is zero-dependency).

## Install & run

Install the skill with `npx skills`; the CLI detects supported agents and
installs into the agent you choose.

```bash
npx skills add SumbleData/sumble-skills-public --skill people-scoring
```

To install globally for a specific agent without prompts:

```bash
npx skills add SumbleData/sumble-skills-public --skill people-scoring -g -a codex -y
npx skills add SumbleData/sumble-skills-public --skill people-scoring -g -a claude-code -y
```

Start a new agent session, then run `/people-scoring` in Claude Code or ask
Codex/Cursor to **"use the people-scoring skill."**

See the repo [README](../../README.md) for full per-tool setup.

## License

MIT.
