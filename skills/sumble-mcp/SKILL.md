---
name: sumble-mcp
description: "Use Sumble MCP for account research, prospecting, people/job/technology searches, organization/contact list workflows, and Sumble MCP prompt or docs authoring. Use when Codex should follow Sumble MCP tool sequencing, query rules, and credit-management guardrails."
---

# Sumble MCP

Use this skill when the task is about the Sumble MCP server itself: running
Sumble MCP workflows, drafting prompts for it, writing docs about it, or
planning/demoing account-research motions built on its tools.

## Read this first

- Read `references/tool-reference.md` for the full tool inventory, costs, query
  DSL, workflows, and credit guardrails.
- Read `references/product-context.md` only when you need setup steps,
  marketplace-facing positioning, or end-user examples.

## Core operating rules

- Start with `GetMyCompanyProfile` unless the task is only checking account
  info or the user already supplied complete targeting criteria in the current
  session.
- When a Sumble tool exposes a `reason` parameter, make it meaningful and
  specific to the action.
- Use `SearchTechnologies` before any call that takes a `technologies`
  parameter.
- Prefer structured tools over `RunSqlQuery`; use raw SQL only as a last resort
  and warn the user that it is less curated.
- Use `FindMatchAndEnrichOrganizations` for organization search, matching, and
  enrichment. Request only the attributes and entity metrics needed for the
  task, because matched orgs, paid attributes, and per-entity metrics all bill.
- Treat `GetIntelligenceBrief` and `EnrichPerson` as high-cost tools. Use them
  only for selected accounts or top 2-3 people unless the user explicitly wants
  broader spend.
- When the user says "my accounts" or "my territory", prefer organization lists
  with `type = group`.
- Always surface URLs returned by the tools.

## Workflow chooser

- Book or territory prioritization: follow `P1: Book of business
  prioritization` in the prompt reference.
- Live demo or one-account game plan: follow `P2: Live demo - one account
  end-to-end`.
- Inbound lead triage: follow `P3: Inbound MQL response`.
- For tech-based prospecting, champion mapping, job-signal outreach, external
  list import, or single-company deep dives, use the `Additional workflow
  patterns` section in the prompt reference.

## Codex translation

- If the current environment does not actually expose the Sumble MCP tools, do
  not pretend it does. Use the reference to draft prompts, docs, demos, or
  implementation guidance instead.
- Keep recommendations concrete and credit-aware. Call out when a higher-cost
  path such as paid organization attributes, per-entity metrics, phone reveals,
  `GetIntelligenceBrief`, or raw SQL deserves explicit user confirmation.
- If repo or runtime instructions conflict with the launch prompt, follow the
  newer repo/runtime instructions and use the prompt reference for Sumble
  domain specifics.
