# Sumble MCP tools (costs, DSL, guardrails)

Source of truth for tool names, costs, filters. (Full version: docs.sumble.com/api/mcp.)
Give every `reason: str` a specific value ("Finding data eng leaders at Stripe"),
not a placeholder.

**Free:** `GetMyCompanyProfile` (ICP: sales plays, key vs other-tier tech / functions
/ projects — call first), `GetAccountInformation` (key/credits/plan),
`CreateOrganizationList`/`AddOrganizationsToList`, `CreateContactList`/`AddContactsToList`,
`ListTables`.

| Tool | Purpose | Cost |
|---|---|---|
| `FindMatchAndEnrichOrganizations` | Find/match/enrich orgs — query filters or resolve names/URLs/IDs; request only needed attrs + tech/team/people/job metrics. | 1 cr/org + 1/paid attr + entity-metric costs |
| `SearchSignals` | Search signals **across many accounts at once** — filters (AND-combined): `account_list_ids`, `organization_ids`, `person_ids`, `technology_slugs`, `job_functions`, `priorities`. Same signal payload as below; job-post signals add `suggested_contacts` (relevance-scored 1–10). Use for territory sweeps (Step 2) and per-person checks. | 1 cr/signal returned (free when none) |
| `GetOrganizationSignals` | Recent sales triggers for one org `id` — champion/leadership moves, new hires on tracked tech, hiring/tech-adoption trends; each with `priority`, `date`, `sales_angle`, `sumble_url` (+ `person_id`/`job_post_id` to drill in). Optional `technology_slugs` filter. The "why now" when you already have one org id. | 1 cr/signal returned (free when none) |
| `GetIntelligenceBrief` | LLM sales brief for one narrowed account. | **50 cr** |
| `FindMatchAndEnrichJobs` | Find/enrich jobs — filters (incl. org-list scoping) or `job_id`s. `description` paid; optional `related_people`. | 1 cr/job + 1/paid attr (title free) + 1/related person |
| `FindMatchAndEnrichPeople` | Find/match/enrich people — resolve IDs/LinkedIn/email or search orgs. Optional `related_people`, `email`/`phone` reveals. | 1 cr/person + 1/paid attr (name free) + 1/related; **email 10 cr, phone 80 cr** (first reveal; free on repeat/unavailable) |
| `ListOrganizationLists` | List org lists (prefer `type = group` for "my accounts"). | 1 cr/list |
| `GetOrganizationList` | Fetch one list's contents. | 1 cr/org |
| `ListContactLists` / `GetContactList` | List / fetch contact lists. | 1 cr/list or /person |
| `SearchTechnologies` | Resolve tech names → slugs. Use before any `technologies` param. | 1 cr/search |
| `RunSqlQuery` | Read-only DuckDB SQL — last resort; warn the user. | 1 cr/100 bytes |

**Query DSL.** *Orgs:* `technology`, `technology_category` (EQ/IN/NOT IN),
`organization` (EQ), `industry`, `employee_count` (EQ/IN or ranges `'100-1000'`,
`'1000-'`, `'-500'`), `hq_location` (hierarchical `'US:Texas:Austin'`), `tag`,
`sic_code`, `naics_code`. *Jobs:* `organizations_list`, `project`, `job_function`,
`job_level`, `country`, `hiring_period` (EQ only: `1mo`/`3mo`/`6mo`/`1yr`/`18mo`/`2yr`).
*People:* `job_function`, `job_level`, `country`, `technology`, `hiring_period`,
`since` (`YYYY-MM-DD`), `person_name`.

**Guardrails:** `SearchTechnologies` before `technologies`; don't OR org filters
with job filters; full state names; `job_title`/`job_description` aren't filterable
(use function + level); prefer structured tools over `RunSqlQuery` (always `LIMIT`).

**Tech-category slugs:** `crm`, `business-intelligence`, `cloud-data-warehouse`,
`data-catalog`, `gen-ai`, `mlops`, `ml-training`, `cybersecurity`, `cloud-security`,
`ci-cd`, `ipaas`, `event-streaming`, `data-pipeline-orchestration`, `etl`,
`logging-observability-monitoring`, `data-quality-and-observability`,
`customer-data-platform`, `feature-flagging-and-a-b-testing`, `vector-database`,
`oss-data-science`, `commercial-data-science`, `infrastructure-as-code-tools`,
`design`, `javascript`, `siem`, `edr`, `headless-cms`, `ccaas`, `endpoint-management`,
`ecommerce-platform`, `vibe-coding`, `coding-agents`, `marketing-automation-platforms`,
`frontier-ai-models`, `processing-units-and-chips`,
`cloud-and-container-orchestration-platforms`, `identity-and-access-management`.

**Attribute validation traps.** These are hard 4xx errors, not warnings, and each costs a
round trip:
- `FindMatchAndEnrichPeople` **match mode**: `confidence` is valid only inside
  `related_people`, and `person_score` is filter-mode only, so neither belongs in the
  top-level `attributes`. Omitting the inner `related_people.attributes` returns bare ids
  with no names and no scores.
- `technology_category` entities accept only `job_post_count`,
  `job_post_count_growth_1y`, `people_count`, `team_count`. `job_post_used_count` is
  valid on a `technology` entity but not on a category.
- `order_by_column: "people_concentration"` and `"people_count_growth_1y"` both require
  `order_by_job_function`.

**Cost discipline.** Free tools liberally; tighten org filters before enriching;
one cheap jobs pass to find the why-now, then full `description` + `related_people`
on the strongest only; email for top 2–3, phone (80 cr) for one and confirm;
`GetIntelligenceBrief` (50 cr) only post-narrowing; on a 402, they're out of credits.
**Resolve each org once** and capture `id`, `slug` and `sumble_url`, requesting the
entity metrics (tech / teams / people / jobs) you need in that same call rather than
re-matching later; every re-match is another credit per org.

**Book-of-business pass** (pick a starting account from a big list): `GetMyCompanyProfile`
→ `ListOrganizationLists`/`GetOrganizationList` (or resolve pasted names) → one
`FindMatchAndEnrichJobs` pass scoped to the list `AND (project IN (...) OR
technology_category IN (...)) AND hiring_period EQ '3mo'` → tier A (hiring on key
projects/categories) / B (weaker) / C (none) → then one `SearchSignals` sweep with
`account_list_ids` over the whole list (**not just tier A** — a fresh high-`priority`
signal promotes a low-fit account; free when nothing matches; add a `priorities`
filter on a huge list) → user picks the top.
~300 cr per 100 accounts for the jobs pass, plus 1 cr per signal surfaced.
