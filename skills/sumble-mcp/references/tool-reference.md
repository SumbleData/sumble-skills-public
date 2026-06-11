# Sumble MCP Tool Reference

This reference is the standalone operating guide for the Sumble MCP skill.

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

### Free account tools

| Tool | Purpose |
|---|---|
| `GetMyCompanyProfile` | Pull ICP, competitive landscape, key personas, and project signals. Usually call first. |
| `GetAccountInformation` | Check API key validity, credits, and plan information. |

### Organization search and enrichment

| Tool | Purpose | Cost |
|---|---|---|
| `FindMatchAndEnrichOrganizations` | Find, match, and enrich organizations in one call. Use advanced query filters or resolve supplied names, URLs, or IDs; request only the attributes and technology/job/team/people metrics needed for the task. | 1 credit per matched org + 1 per paid attribute + per-entity metric costs |
| `GetIntelligenceBrief` | Generate an LLM sales intelligence brief for one target account from Sumble structured data. Use only after narrowing to a high-priority account. | 50 credits per completed brief |

### Jobs

| Tool | Purpose | Cost |
|---|---|---|
| `FindMatchAndEnrichJobs` | Find, look up, and enrich job postings in one call. Search with advanced query filters (including org-list scoping) or enrich a list of `job_id`s; request only the attributes needed (the full `description` is a paid attribute). Optional `related_people` returns hiring managers and adjacent team members per job. | 1 credit per job + 1 per paid attribute (title is free) + 1 per related person returned |

### People

| Tool | Purpose | Cost |
|---|---|---|
| `FindMatchAndEnrichPeople` | Find, match, and enrich people in one call. Resolve person IDs, LinkedIn URLs, or emails, or search within organizations with advanced query filters; request only the attributes needed. Optional `related_people` (inferred managers and direct reports) and `email`/`phone` contact reveals. | 1 credit per person + 1 per paid attribute (name is free) + 1 per related person; 10 credits per first email reveal, 80 credits per first phone reveal, free on repeat reveals of the same type or if unavailable |

### Organization lists

| Tool | Purpose | Cost |
|---|---|---|
| `ListOrganizationLists` | List org lists. Prefer `type = group` when the user says "my accounts" or "my territory". | 1 credit per list |
| `GetOrganizationList` | Fetch contents of one org list. | 1 credit per org |
| `CreateOrganizationList` | Create an empty org list. | Free |
| `AddOrganizationsToList` | Add organizations by IDs or slugs. | Free |

### Contact lists

| Tool | Purpose | Cost |
|---|---|---|
| `ListContactLists` | List contact lists and metadata. | 1 credit per list |
| `GetContactList` | Fetch people in a contact list. | 1 credit per person |
| `CreateContactList` | Create an empty contact list. | Free |
| `AddContactsToList` | Add people by Sumble person IDs. | Free |

### Technology reference

| Tool | Purpose | Cost |
|---|---|---|
| `SearchTechnologies` | Resolve free-text technology names to Sumble slugs. Use before any `technologies` parameter. | 1 credit per search |

### Database

| Tool | Purpose | Cost |
|---|---|---|
| `RunSqlQuery` | Read-only DuckDB SQL. Last resort only. Warn the user when using it. | 1 credit per 100 bytes of response |
| `ListTables` | List available DuckDB tables and columns before writing raw SQL. | Free |

## Query DSL notes

### Common organization filters

- `technology`: `EQ`, `IN`, `NOT IN`
- `technology_category`: `EQ`, `IN`, `NOT IN`
- `organization`: `EQ`
- `industry`: `EQ`, `IN`, `NOT IN`
- `employee_count`: `EQ`, `IN`, range strings like `'100-1000'`, `'1000-'`, `'-500'`
- `hq_location`: `EQ`, `IN`, `NEQ`, hierarchical values like `'US:Texas:Austin'`
- `tag`: `EQ`, `IN`
- `sic_code`: `EQ`
- `naics_code`: `EQ`

### Common job filters

- `organizations_list`: `EQ`, `IN`
- `project`: `EQ`, `IN`
- `job_function`: `EQ`, `IN`, `NOT IN`
- `job_level`: `EQ`, `IN`, `NOT IN`
- `country`: `EQ`, `IN`, `NOT IN`
- `hiring_period`: `EQ` only, one of `'1mo'`, `'3mo'`, `'6mo'`, `'1yr'`, `'18mo'`, `'2yr'`

### Common people filters

- `job_function`: `EQ`, `IN`, `NOT IN`
- `job_level`: `EQ`, `IN`, `NOT IN`
- `country`: `EQ`, `IN`, `NOT IN`
- `technology`: `EQ`, `IN`, `NOT IN`
- `hiring_period`: `EQ` only
- `since`: `EQ` only, `YYYY-MM-DD`
- `person_name`: `EQ`

### Guardrails

- Use `SearchTechnologies` before passing `technologies`.
- Do not combine org filters with job filters using `OR`.
- Use full state names in country/location filters.
- `job_title` and `job_description` are not filterable. Use function and level.
- Prefer structured tools over `RunSqlQuery`.

## Technology category slugs

Use these exact slugs with `technology_category` or `technology_categories`:

`crm`, `business-intelligence`, `cloud-data-warehouse`, `data-catalog`, `gen-ai`, `mlops`, `ml-training`, `cybersecurity`, `cloud-security`, `ci-cd`, `ipaas`, `event-streaming`, `data-pipeline-orchestration`, `etl`, `logging-observability-monitoring`, `data-quality-and-observability`, `customer-data-platform`, `feature-flagging-and-a-b-testing`, `vector-database`, `oss-data-science`, `commercial-data-science`, `infrastructure-as-code-tools`, `design`, `javascript`, `siem`, `edr`, `headless-cms`, `ccaas`, `endpoint-management`, `ecommerce-platform`, `vibe-coding`, `marketing-automation-platforms`, `frontier-ai-models`, `processing-units-and-chips`, `cloud-and-container-orchestration-platforms`, `identity-and-access-management`

## Priority workflows

### P1: Book of business prioritization

Trigger: "here's my book, how do I prioritize it"

1. Call `GetMyCompanyProfile` and hold key tier categories, job functions, and projects in memory.
2. Call `ListOrganizationLists` and prefer a `group` list. If the user pasted raw names instead, use `FindMatchAndEnrichOrganizations` to resolve them, then `CreateOrganizationList` and `AddOrganizationsToList`.
3. Call `GetOrganizationList` for the chosen list.
4. Run one cheap signal pass with `FindMatchAndEnrichJobs` scoped to the list:

```text
organizations_list EQ '<list_id>'
AND (project IN (<key_projects>) OR technology_category IN (<key_categories>))
AND hiring_period EQ '3mo'
```

5. Tier accounts:
   A. hiring signal on key projects or key categories
   B. weaker or older signals
   C. no recent signal
6. Present ranked evidence and stop before deeper enrich spend. Ask which A-tier accounts to deep-dive.

Budget: roughly 300 credits for a 100-account list. The key cost saver is using
one `FindMatchAndEnrichJobs` pass with few attributes and only requesting
expensive organization attributes or entity metrics after the list is narrowed.

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

Budget: roughly 100 credits.

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

Budget: roughly 60-80 credits.

## Additional workflow patterns

### Tech-based prospecting

1. `GetMyCompanyProfile`
2. `SearchTechnologies`
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

- Free tools can be used liberally.
- Tighten organization filters before `FindMatchAndEnrichOrganizations`, then request only needed paid attributes and entity metrics.
- `GetIntelligenceBrief` is 50 credits per completed brief. Use it after narrowing to a high-priority account.
- Phone reveals in `FindMatchAndEnrichPeople` are expensive (80 credits). Prefer email-only when email is enough; keep contact reveals to the top 2-3 targets.
- `RunSqlQuery` bills by response size. Always use `LIMIT` and select only the columns you need.
- On a 402 response, direct the user to purchase more credits.
- Always surface URLs returned by the tools.
