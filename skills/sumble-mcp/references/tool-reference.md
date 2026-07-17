# Sumble MCP Tool Reference

This reference is the standalone operating guide for the Sumble MCP skill. It
is deliberately opinionated about HOW to sequence tools and manage spend, not
a catalog of tool facts. Exact parameters, query syntax, valid slugs, and
current credit costs live in each tool's own description — always trust the
live tool description over this file.

## Required first step for most sessions

Before running any other Sumble tool, call `GetMyCompanyProfile` first.

Use it to pull:

- company summary and sales plays
- key and other-tier technologies
- key and other-tier tech concepts
- key and other-tier job functions
- key and other-tier projects

Exceptions:

- checking credits with `GetAccountInformation`
- the user already supplied complete targeting criteria in the current session

## `reason` parameter

When a Sumble tool exposes a `reason: str` parameter, make it specific and tied
to the actual action, not a generic placeholder.

Good:

- `Checking AI hiring signals in my territory`
- `Resolving Snowflake to Sumble technology slugs`
- `Finding data engineering leaders at Stripe`

Bad:

- `user asked`
- `research`

## Tool inventory

### Account tools (free — use liberally)

| Tool | When to use |
|---|---|
| `GetMyCompanyProfile` | Pull ICP, competitive landscape, key personas, and project signals. Usually call first. |
| `GetAccountInformation` | Check API key validity, credits, and plan information. |
| `ReportDataQualityIssue` | Report incorrect, missing, or stale Sumble data. Routed to the Sumble data team. |
| `SubmitSupportRequest` | Submit a general account, billing, or product support request. Routed to the Sumble support team. |

### Organization search and enrichment

| Tool | When to use |
|---|---|
| `FindMatchAndEnrichOrganizations` | The primary organizations tool: find, match, and enrich in one call. Use advanced query filters or resolve supplied names, URLs, or IDs. Bills per matched org and per selected attribute and entity metric, so request only what the task needs. |
| `GetIntelligenceBrief` | LLM sales intelligence brief for ONE target account. One of the most expensive tools — use only after narrowing to a high-priority account, and confirm with the user first. |

### Jobs

| Tool | When to use |
|---|---|
| `FindMatchAndEnrichJobs` | The primary jobs tool: search with advanced query filters or enrich a list of `job_id`s. Request only the attributes needed — the full `description` is a paid attribute. To scope to companies, resolve them to IDs first and pass the `organization_ids` param; for saved lists pass the `organization_list_id` param (prefer both over the query language's fuzzy `organization` / `organizations_list` nodes). Optional `related_people` returns hiring managers and adjacent team members per job. |

### People

| Tool | When to use |
|---|---|
| `FindMatchAndEnrichPeople` | The primary people tool. Match mode resolves person IDs, LinkedIn URLs, or emails; filter mode searches within organizations and REQUIRES an organization scope (`organization_ids` and/or `organization_list_id`). Request only the attributes needed. The `person_score` attribute ranks people against the account's ICP (filter mode, single org only). Optional `related_people` (inferred managers and direct reports). Contact reveals (`email`, and especially `phone`) are the most expensive attributes — keep them to the top 2-3 targets. |

### Signals

| Tool | When to use |
|---|---|
| `SearchSignals` | Cross-account signal feed (champion moves, hires and promotions, technology/product mentions, projects, hiring trends). Filter by organization lists, org IDs, person IDs, technology slugs, job functions, or priorities. Job-post signals include ranked `suggested_contacts`. |
| `SearchPrioritySignals` | The user's Priority Signals digest items, by source signal or entity IDs. |
| `GetOrganizationSignals` | Recent sales signals for ONE target account by Sumble organization ID (resolve names/domains with `FindMatchAndEnrichOrganizations` first). Use for "what changed at X" and why-reach-out-now angles. |

Signals bill per signal returned — filter tightly rather than pulling an
unfiltered feed. Signals return `sumble_url` deep links plus `person_id` /
`job_post_id` fields you can feed into `FindMatchAndEnrichPeople` /
`FindMatchAndEnrichJobs` for follow-up research.

### Organization lists

| Tool | When to use |
|---|---|
| `ListOrganizationLists` | List org lists with IDs, URLs, counts, and settings. Prefer `type = group` when the user says "my accounts" or "my territory". |
| `GetOrganizationList` | Fetch contents of one org list. Bills per org in the list. |
| `CreateOrganizationList` | Create an empty org list. |
| `AddOrganizationsToList` | Add organizations by IDs or slugs. |
| `SetOrganizationListDeleted` | Soft-delete an org list, or restore a deleted one. |
| `SetOrganizationListSignals` | Include or exclude a list's accounts from future Signals delivery (lists are included by default). |

### Contact lists

| Tool | When to use |
|---|---|
| `ListContactLists` | List contact lists and metadata. |
| `GetContactList` | Fetch people in a contact list. Bills per person in the list. |
| `CreateContactList` | Create an empty contact list. |
| `AddContactsToList` | Add people by Sumble person IDs. |

### Reference lookups

| Tool | When to use |
|---|---|
| `SearchTechnologies` | Fuzzy free-text technology discovery ("what does Sumble call X?"). |
| `LookupTechnologies` | Resolve a batch of technology names, slugs, or aliases to canonical IDs, slugs, names, and categories. Prefer this over repeated `SearchTechnologies` calls when you already know the names. |
| `LookupTechnologyCategories` | Resolve technology category slugs or names to canonical categories and their constituent technologies. This is the source of truth for valid category slugs — never guess category slugs from memory. |
| `LookupJobTitles` | Resolve raw job titles to canonical job function and level for use in filters. |
| `LookupProjects` | Resolve project names or slugs to canonical IDs, slugs, and names. |

### Database

| Tool | When to use |
|---|---|
| `RunSqlQuery` | Read-only DuckDB SQL. Last resort only. Warn the user when using it. Bills by response size — always use `LIMIT` and select only needed columns. |
| `ListTables` | List available DuckDB tables and columns before writing raw SQL. Free. |

## Query guardrails

The full query syntax (fields, operators, valid values) is documented in each
search tool's own description — read it there. The rules below are the
non-obvious ones:

- Resolve identifiers before filtering on them; do not guess slugs or names
  from memory:
  - technologies: `LookupTechnologies` for known names, `SearchTechnologies`
    for fuzzy discovery
  - technology categories: `LookupTechnologyCategories`
  - job titles to functions/levels: `LookupJobTitles`
  - projects: `LookupProjects`
- Scope jobs/people to companies via the `organization_ids` /
  `organization_list_id` parameters, not the query language's fuzzy
  `organization EQ '<name>'` or `organizations_list` nodes.
- People filter mode requires an organization scope
  (`organization_ids` and/or `organization_list_id`).
- Do not combine org filters with job filters using `OR`.
- Use full state names in country/location filters.
- `job_title` and `job_description` are not filterable. Use function and level.
- Prefer structured tools over `RunSqlQuery`.

## Priority workflows

### P1: Book of business prioritization

Trigger: "here's my book, how do I prioritize it"

1. Call `GetMyCompanyProfile` and hold key tier categories, job functions, and projects in memory.
2. Call `ListOrganizationLists` and prefer a `group` list. If the user pasted raw names instead, use `FindMatchAndEnrichOrganizations` to resolve them, then `CreateOrganizationList` and `AddOrganizationsToList`.
3. Call `GetOrganizationList` for the chosen list.
4. Run one cheap signal pass with `FindMatchAndEnrichJobs`, passing the
   `organization_list_id` parameter for the chosen list plus the query:

```text
(project IN (<key_projects>) OR technology_category IN (<key_categories>))
AND hiring_period EQ '3mo'
```

   Optionally also call `SearchSignals` filtered to the list
   (`account_list_ids`) for champion moves and other non-hiring triggers.
5. Tier accounts:
   A. hiring signal on key projects or key categories
   B. weaker or older signals
   C. no recent signal
6. Present ranked evidence and stop before deeper enrich spend. Ask which A-tier accounts to deep-dive.

The key cost saver is using one `FindMatchAndEnrichJobs` pass with few
attributes, and only requesting expensive organization attributes or entity
metrics after the list is narrowed.

### P2: Live demo, one account end to end

Trigger: demo flow, deep research to outreach in under 3 minutes

1. `GetMyCompanyProfile`
2. Get the target account from the user. Prefer domain.
3. `FindMatchAndEnrichOrganizations` for the target domain with only the key organization attributes and entity metrics needed for the demo.
4. `FindMatchAndEnrichJobs` for key projects in the last 6 months. Fallback to key job functions in the last 3 months.
5. `FindMatchAndEnrichJobs` again with the strongest signal's `job_id`, requesting the `description` attribute and `related_people` for the hiring manager.
6. Build the account brief inline.
7. `FindMatchAndEnrichPeople` for VP, Director, Senior Director, and Head roles in key functions.
8. `FindMatchAndEnrichPeople` with the `email` attribute for only 2-3 priority targets.
10. `CreateContactList` and `AddContactsToList` for everyone you want saved.
11. Draft two outreach variants:
    A. signal-led, using language from the job description
    B. reference-customer-led, using the company profile

### P3: Inbound MQL response

Trigger: "got this inbound, help me work it"

1. Extract person, company, and trigger.
2. `GetMyCompanyProfile`
3. `FindMatchAndEnrichOrganizations` first to match the account and check fit.
4. Stop if the account is a weak fit. Do not keep spending credits on a bad lead.
5. `FindMatchAndEnrichJobs` to identify the why-now initiative.
6. Decide whether the MQL is the buyer, a researcher, or a referrer.
7. If needed, `FindMatchAndEnrichPeople` for the real buyer.
8. If needed, `FindMatchAndEnrichJobs` with the active initiative's `job_id` and `related_people` for the hiring manager.
9. `FindMatchAndEnrichPeople` with contact-reveal attributes for at most two people.
10. Save the relevant people to a contact list.
11. Draft response and multithread outreach.

## Additional workflow patterns

### Tech-based prospecting

1. `GetMyCompanyProfile`
2. `LookupTechnologies` (or `SearchTechnologies` for fuzzy discovery)
3. `FindMatchAndEnrichOrganizations`
4. `CreateOrganizationList`
5. `AddOrganizationsToList`
6. Optionally request deeper attributes or entity metrics only for the top few accounts

### Champion org mapping

1. `GetMyCompanyProfile`
2. Start from a known `person_id`
3. `FindMatchAndEnrichPeople` with `related_people` for that person
4. Prioritize `managers` for buyers and `direct_reports` for implementers
5. `FindMatchAndEnrichPeople` with the `email` attribute for 2-3 people
6. Save to a contact list

### Job-signal outreach

1. `GetMyCompanyProfile`
2. `ListOrganizationLists`
3. `FindMatchAndEnrichJobs` scoped to a territory list and project slug
4. `FindMatchAndEnrichJobs` for the top job's `job_id` with the `description` attribute and `related_people`
5. `FindMatchAndEnrichPeople` with contact-reveal attributes on only the top few targets

### External list import

1. `GetMyCompanyProfile`
2. `FindMatchAndEnrichOrganizations`
3. `CreateOrganizationList`
4. `AddOrganizationsToList`
5. Optional selective attributes, entity metrics, or `GetIntelligenceBrief`

### Single-company deep dive

1. `GetMyCompanyProfile`
2. `FindMatchAndEnrichOrganizations`
3. `FindMatchAndEnrichPeople`
4. `FindMatchAndEnrichJobs`
5. Save targets to a contact list

## Cost management

Current credit prices are stated in each tool's description — quote those, not
remembered numbers. The durable rules:

- Free tools can be used liberally.
- Billed search/enrich tools charge per returned row and per selected
  attribute or entity metric. Tighten filters first, then request only the
  attributes and metrics the task needs.
- The most expensive operations are `GetIntelligenceBrief`, phone reveals,
  and broad unfiltered pulls (signal feeds, large `RunSqlQuery` responses).
  Narrow to selected accounts or the top 2-3 people first, and get explicit
  user confirmation before high-spend paths.
- Prefer email-only reveals when email is enough; phone is far more expensive.
- On a 402 response, direct the user to purchase more credits.
- Always surface URLs returned by the tools.
