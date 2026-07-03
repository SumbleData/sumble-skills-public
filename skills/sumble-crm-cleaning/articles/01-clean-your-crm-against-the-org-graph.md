# Clean your CRM against an org graph, not a fuzzy-name matcher

Most CRM dedupe tools compare account names to each other and guess. The better approach: resolve every account to a real organization, then read the duplicates and the missing hierarchy straight off the org graph.

**Skill:** [`sumble-crm-cleaning`](../SKILL.md). Run it in Claude Code, Codex, or Cursor.

## TLDR
- Duplicate detection by name similarity is guesswork. Resolving both records to the same real-world organization is evidence.
- The same matching pass finds your hierarchy gaps: subsidiaries with no link to their parent, and parents your CRM doesn't know exist.
- Every finding ships with its evidence (the matched org, its alternate names and domains, the ancestor chain) so a human can adjudicate in seconds. Nothing changes in your CRM until a reviewer says so.
- We ran it on our own CRM: 1,236 accounts, about ten minutes of compute, 12 duplicate clusters, 17 missing or wrong parent links, and 27 parent companies we didn't have at all.

Every CRM accumulates the same two problems. Someone creates "Kong Inc." because "Kong" didn't autocomplete. An SDR imports a list with `linkedin.com` in the website column. A company you sell to gets acquired, and the CRM keeps treating parent and subsidiary as strangers. None of this is anyone's fault; it's entropy. The question is how you clean it up without a quarter-long data project.

## Why it's worth fixing

Duplicates are the visible nuisance: two reps work the same company without knowing, activity history splits across records, pipeline double-counts, and your routing rules, which dedupe on exact account match, assign the "new" lead to the wrong copy.

Hierarchy gaps cost more and show up less. If a subsidiary and its parent sit in your CRM as unrelated accounts, your account team can't see the whole relationship, a land-and-expand motion has no map to expand along, revenue rollups under-report the parent, and one rep cold-mails the subsidiary while another is mid-negotiation with the parent. The information existed. The CRM just didn't have the edge.

## Name matching is the wrong tool

The traditional dedupe pass compares names: normalize, strip "Inc.", compute a similarity score, flag anything above a threshold. It produces two failure modes at once: it floods you with false positives (similar names, different companies), and it misses the duplicates that matter most: the ones whose names aren't similar.

"Wordpress VIP" and "A8c" share no tokens. No fuzzy matcher flags them. They're both Automattic: one is the product line, the other is the company's own nickname for itself (a8c.com is their domain). "BlackDuck" and "Synopsys" look nothing alike either; one acquired the other.

The fix is to stop comparing your records to each other and start resolving each record to the real-world organization behind it. That's what the [CRM-cleaning skill](../SKILL.md) does: every account goes through Sumble's matcher (the same `POST /v6/organizations` endpoint behind the public API), which resolves names, domains, and known aliases to an organization in Sumble's graph. Two CRM accounts that land on the same organization are a duplicate candidate not because their strings look alike, but because they are the same company. That's the only duplicate evidence the skill uses, by design. No similarity thresholds to tune, no noise floor to wade through.

And because each matched organization carries its position in the org graph (its parent, its parent's parent), the hierarchy findings come from the same pass:

- **Missing parent link.** The account's Sumble parent (or grandparent) is another account in your CRM, but no CRM link exists.
- **Parent conflict.** Your CRM says the parent is X; the org graph says it's Y.
- **Parent not in CRM.** Several of your accounts share a parent company you don't have at all, grouped into one finding per missing parent, with all its children listed.

## Show the evidence, keep a human in the loop

An automated merge that's wrong is worse than the duplicate it removed. So the skill doesn't touch your CRM. It builds a small local review app (plain Python, no dependencies) where every finding is a card you accept, reject, or skip, and every card shows its work: the matched Sumble organization with the alternate names and domains that link the records (for the Automattic cluster above, the alias list is the explanation), the full ancestor chain behind every hierarchy suggestion, and deep links from each account name to its CRM record and each matched org to its Sumble page. Verifying a finding takes two clicks, not two browser searches.

For duplicate clusters, you mark one record the **primary** (the app suggests one: owned records beat orphans, customers beat prospects, the bigger CRM footprint beats the emptier one); the other records then default to **merge** into it, and you can switch any to **delete** outright, since a shell record with no history attached is often cleaner to delete than to merge. (A false match, where the matcher collapsed two different companies onto one org, is one click to dismiss as "not a duplicate.") Decisions save as you click. When you're done, one button exports `actions.csv`: a `merge` / `delete` / `set_parent` / `create_parent_and_link` row per resolved finding, keyed by CRM account id, ready for your admin, a Data Loader job, or a follow-up agent run.

There's also an **Unmatched** tab: accounts the matcher couldn't resolve to any organization. Don't skip it. In practice it's where the shell records, typo'd imports, and long-dead companies hide.

## What it found in ours

We ran the skill on Sumble's own Salesforce: 1,236 accounts, roughly ten minutes end to end, about 5 API credits per account.

- **12 duplicate clusters.** Some were the boring kind you'd hope any tool catches: "Kong" / "Kong Inc.". The interesting ones were invisible to name matching: Synopsys / BlackDuck, and the Wordpress VIP / A8c pair above.
- **17 hierarchy findings**, including subsidiaries we treat as separate motions (GitHub under Microsoft, Wiz under Google, HashiCorp under IBM) that had no parent link in the CRM.
- **27 parent companies not in the CRM at all**, each grouped with the child accounts we already had.
- **4 unmatched accounts**, all worth retiring.

The review step earned its keep immediately. Two of the suggested parent links (Boomi under Dell, Veracode under Broadcom) reflect ownership that has since been divested. The org graph is data, and data has lag; a reviewer with context rejects those in seconds, and the rejection is recorded.

**Want to see it live?** Explore the [CRM cleaning review demo](https://crm-cleaning-demo.sumble.com/): the findings from this run, with the per-finding evidence, the alternate-name popovers, and the pick-a-primary / merge-or-delete review. For demonstration purposes only.

## Run it on yours

You need a coding agent (**Claude Code**, **OpenAI Codex**, or **Cursor**), a **Sumble API key** ([sumble.com/account](https://sumble.com/account)), and your account list, pulled live from Salesforce or HubSpot if your agent can reach them, or any CSV export with an id, a name, and a website column.

```bash
npx skills add SumbleData/sumble-skills --skill sumble-crm-cleaning
```

Start a new agent session and run it (`/sumble-crm-cleaning` in Claude Code; "use the sumble-crm-cleaning skill" in Codex or Cursor). The interview is four questions: where the output goes, where your accounts live, which checks to run (duplicates, hierarchy, or both; both cost the same, since it's one matching pass), and a cost confirmation before anything is fetched (~5 credits per account; a 2,000-account CRM is ~10,000 credits). If your CRM has a parent-account field, hand it over. The skill suppresses links that are already correct and flags the ones that conflict. Then:

```bash
cd crm_cleaning/<your-company>
python3 app.py        # http://localhost:8002
```

Review, export, apply. When the next quarter's entropy accumulates, re-export your accounts and re-run the fetch. Decisions you've already made persist, and only new findings come up for review.

## The part that compounds

A dedupe is usually a one-off cleanup that starts rotting the day it finishes. Matching against an org graph is different, because the graph keeps moving: the next acquisition or rebrand shows up as new findings on the next run instead of silent drift. The cleanup stops being a project and becomes a habit with a queue.

Once every account is resolved to a real organization, you've done more than clean the CRM: you've keyed it to a universe of data about what those companies are doing. That's the foundation the [account-scoring skill](../../sumble-account-scoring/articles/01-account-score-should-tell-a-rep-what-to-do.md) builds on.
