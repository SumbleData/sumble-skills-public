# Sumble MCP Skill

Install the Sumble MCP skill into your agent. The `skills` CLI detects
supported agents and installs into the agent you choose:

```bash
npx skills add SumbleData/sumble-skills-public --skill sumble-mcp
```

To install globally for a specific agent without prompts:

```bash
npx skills add SumbleData/sumble-skills-public --skill sumble-mcp -g -a codex -y
npx skills add SumbleData/sumble-skills-public --skill sumble-mcp -g -a claude-code -y
```

After installation, use the skill with prompts like:

```text
Use $sumble-mcp to research target accounts in fintech.
Use $sumble-mcp to build a prospect list for design partners.
Use $sumble-mcp to map champions and hiring signals for Stripe.
```

## What It Does

`sumble-mcp` helps agents use Sumble MCP for:

- account research
- prospecting
- people, job, and technology searches
- organization and contact-list workflows
- account intelligence briefs
- prompt and documentation authoring for Sumble MCP

## Notes

- The skill lives under `skills/sumble-mcp` in the `SumbleData/sumble-skills-public` repo.
- The core skill files are [`SKILL.md`](./SKILL.md), [`agents/openai.yaml`](./agents/openai.yaml), and the documents in [`references/`](./references/).
