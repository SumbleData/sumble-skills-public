# Sumble MCP Product Context

Use this reference when the task is user-facing or marketing-facing rather than
pure tool operation.

## Product summary

Sumble MCP connects AI clients to Sumble's account intelligence data. It lets a
user research companies, technologies, people, jobs, and saved account lists
through conversation instead of manual UI clicks.

Core themes:

- technology intelligence across millions of organizations
- people search and enrichment
- hiring signal detection from job posts
- account and contact list building
- LLM-generated account intelligence briefs for selected target accounts
- company profile and competitive-intelligence guidance

## Good use cases

- research a target account's tech stack and relevant teams
- build a prospecting list from technology and hiring signals
- identify hiring managers and senior leaders behind open roles
- enrich high-priority people with contact information
- create account and contact lists from a conversational workflow

## Setup outline

Sumble MCP currently requires a custom MCP connection.

| Platform | Availability | Notes |
|---|---|---|
| Claude | Paid plans | Enterprise users may need an admin to allow custom connectors. Use custom connector name `Sumble` and URL `https://mcp.sumble.com`. |
| Cursor | All plans | Add an HTTP MCP server named `sumblemcp` with URL `https://mcp.sumble.com`. |
| Claude Code | All plans | Run `claude mcp add --transport http sumble https://mcp.sumble.com --scope user`, then authenticate from `/mcp`. |
| ChatGPT | Paid plans | Requires dev-mode/custom app access. Create an app named `Sumble` with MCP server URL `https://mcp.sumble.com`. |
| Gemini | Not available | Do not claim Sumble MCP is available in Gemini. |

After setup, complete the Sumble auth flow and start with company, technology,
people, or hiring questions.

## Example user prompts

- `I sell observability tools. Tell me the full tech stack at Stripe, which teams I should approach, and who the key people are.`
- `Find mid-market US companies using both Snowflake and dbt but not Databricks. Create an account list called Snowflake+dbt prospects.`
- `Which of my accounts are hiring for machine learning roles in the last 3 months? For the top 3, find the hiring managers.`
- `Find enterprise companies in EMEA that use Hadoop and may be ready to modernize their data stack.`
- `Find VPs and Directors of Data Engineering at my top 10 accounts, get their emails, and add them to a contact list called Data Eng Leaders Q2.`

## Positioning notes

- The main value is compressing multi-tab account research into one guided flow.
- The strongest demos show one account researched end-to-end, not a broad sweep with many enrich calls.
- Messaging should emphasize better prospecting, faster account understanding, and concrete next steps.
