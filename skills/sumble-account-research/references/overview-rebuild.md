# Rebuilding the overview page

Maps each card of `sumble.com/orgs/<slug>/overview` to the MCP calls that reproduce
it (Step 5b). Tools/costs in `references/mcp-tools.md`. Cheapest/broadest first.

**0. Resolve the org** — `FindMatchAndEnrichOrganizations` on the domain/name;
confirm by name + domain; capture `slug`, `id`, URL. Request the **entity metrics**
(tech/teams/people/jobs) you need in this same call rather than re-matching.

**1. ICP + account score** — no public score tool; compare the org to the Step 3
profile (runs key tech? has teams in key functions? hiring on key projects?
employee-count/industry in band?). If they keep a score or a `group` list with
scores, use it; else give a qualitative "strong/partial/weak fit, because …".

**2. People** — `FindMatchAndEnrichPeople` in key functions at senior levels
(VP/Director/Head); name is free, hold reveals for Step 5e; `related_people` maps
buyers ↔ implementers.

**3. Teams** — team entity metrics from step 0: which teams, size, growth; focus on
teams matching key functions + the stated goal.

**4. Tech** — org technology metrics: key categories (fit + play), competitor/
displacement tech (the angle), complementary tech. `SearchTechnologies` to resolve names.

**5. Headcount** — `employee_count` + headcount/team-growth trend; a rising team is a why-now.

**6. Signals** — recent on-thesis hiring (no separate signals tool):
`FindMatchAndEnrichJobs` scoped to the org `AND (project IN (...) OR
technology_category IN (...)) AND hiring_period EQ '3mo'` (`1mo` freshest, `6mo`
wider). Rank by volume + recency; then pull `description` + `related_people` for the
single strongest — that's the why-now language and the hiring manager.

One org enrich + one jobs pass covers most of this cheaply; spend more only on
accounts that survive the first look. Always surface URLs.
