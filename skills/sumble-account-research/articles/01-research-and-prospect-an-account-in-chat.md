# Research and prospect an account without leaving the chat

The scoring and CRM skills build apps you run in a coding agent. This one is different: a **skill you install in your AI chat** that takes a single account from a name to who to reach, why now, and a drafted email, one conversation and one account at a time.

**Skill:** [`sumble-account-research`](../SKILL.md). Upload it to Claude, ChatGPT, or Gemini.

*Account scoring tells you [which companies](../../sumble-account-scoring/articles/01-account-score-should-tell-a-rep-what-to-do.md). People scoring tells you [who inside them](../../sumble-people-scoring/articles/01-people-scoring-use-cases.md). This skill is the motion that works one of those accounts end to end.*

## TLDR
- It's a chat skill rather than a coding-agent skill: a single `SKILL.md` you upload to Claude (and adapt into a Custom GPT or a Gemini Gem). No local app, no terminal.
- It runs the whole motion in conversation: deep dive one account, or prioritize across the accounts in your CRM territory; pull your internal context, rebuild Sumble's external view, then recommend teams, people, and a drafted email, ending in contact reveals and a push to your sequencer.
- **It asks one question, then runs.** Deep dive on a specific account, or prioritize across your accounts — asked before it touches a single tool, with the account name collected in the same message. Then it goes quiet and works to a finished deliverable, so you can start it and walk away.
- To do anything real it needs the Sumble MCP connected. Without it you get a good plan; with it you get real people, signals, and emails.
- It builds a reusable profile of your company and sales plays once, then loads it on every later run, so setup happens once.

## What it does

Open a chat, name an account, and the skill walks the play a good rep runs but rarely has time for:

1. **Scopes with a single question**: *deep dive on a specific account*, or *help me prioritize across my accounts* — plus the account name if you're deep diving. That's the only time it interrupts you; everything else is prescribed, not asked. The deliverable defaults to an account plan as an interactive HTML brief (say "outreach sequences", "a deck", or "prep me for my call" when you invoke it and it honors that instead), and your internal context is pulled automatically from whatever's connected. If you're prioritizing, it pulls your CRM-synced account list from Sumble (the one that refreshes on its own) and ranks the accounts on two axes: fit, and whether something just happened — with a reason each is compelling: a sales play, a tech match, a dated hiring signal.
2. **Loads your context**: it pulls the account's state from whatever you have connected — call summaries (Gong, Fireflies), notes (Granola), CRM stage (Salesforce, HubSpot), marketing engagement — rather than interviewing you about it. Internal context outranks anything external, so it drives everything downstream.
3. **Rebuilds the account's Sumble overview**: tech, teams, people, headcount, hiring signals, and ICP fit, assembled from the Sumble API and read through your sales plays.
4. **Recommends and delivers**: the team to land or expand into, why now, and the buying group to reach (economic buyer, champion, multi-thread) — each name checked as currently at the company, carrying both a LinkedIn and a Sumble link and a confidence-scored reporting line. That group then gets rendered into whichever deliverable you picked. Only at the end does it offer to reveal emails and phone numbers and push the contacts and drafts into your sequencer (Salesforce/Outreach/Salesloft, Apollo, SmartLead, HeyReach, Nooks).

It narrates each phase, and it never spends a credit or sends anything without you in the loop.

## It's a web-app skill, not a coding-agent skill

The account-scoring, people-scoring, and CRM-cleaning skills run inside a coding agent (Claude Code, Codex, Cursor) and generate a local Python app you tune with sliders. This one has no app to build; the work is the conversation. So it lives where you chat: Claude, ChatGPT, or Gemini.

Two consequences worth knowing up front:

- **It's a single Markdown file.** The entire skill is one `SKILL.md`. That makes it easy to upload as a skill, or to paste straight in as custom instructions on platforms without a skills feature.
- **It's only as capable as its tool access.** The skill is instructions; the data comes from the Sumble MCP. Where the chat can reach Sumble, it runs the real motion; where it can't, it falls back to drafting the plan and the emails from whatever you paste in. The question to ask on any platform is whether the chat can call the Sumble MCP.

## Install it

You'll need a **Sumble API key** ([sumble.com/account](https://sumble.com/account)) and the `SKILL.md` from the [`sumble-account-research`](../SKILL.md) skill.

**Claude (claude.ai or desktop): the most complete path.**
1. **Settings → Capabilities → Skills → Upload skill**, and select the skill folder (or a zip of it) containing `SKILL.md`. *(Skills require a Pro, Team, or Enterprise plan; on Team/Enterprise an admin may need to enable them.)*
2. **Settings → Connectors → add the Sumble MCP** (its URL plus your API key). This is what lets the skill pull real data.
3. In any chat, just ask: *"Use account research on Vanta"* or *"Help me pick which accounts in my territory to work."* Skills trigger on intent. It works in both chat and Cowork.

**OpenAI ChatGPT: replicate it as a Custom GPT.**
ChatGPT has no upload-a-skill feature, so recreate the skill as a saved assistant: **Explore GPTs → Create**, and paste the `SKILL.md` text into the GPT's **Instructions**. Then connect Sumble as a **connector / action** (supported on Plus, Pro, Business, and Enterprise) so the GPT can call the Sumble MCP. Chat with that GPT to run the motion; without the connection it still drafts the plan and emails from context you provide.

**Google Gemini: build a Gem.**
Gemini's closest concept is a **Gem** (a saved custom assistant): create one and paste `SKILL.md` into its instructions. Gemini's connector access is more limited, so unless you can wire Sumble in, treat the Gem as a guided researcher that structures the play and drafts outreach from data you paste, and connect Sumble the moment the platform allows it.

If your platform can't reach Sumble at all yet, the skill is still useful as the method; it just can't fetch on its own.

## Operate it

A few things make it feel fast and keep it honest:

- **First run builds your profile; every run after is instant.** Paste your sales enablement (plays, persona profiles, battlecards from Seismic / Saleshood / Highspot) alongside your answer and it combines that with your company profile from Sumble into a reusable **Sumble profile** and caches it. On later runs it loads that profile, auto-picks the play that fits the account's signals, and offers the swap at the end.
- **The most durable cache is a companion skill.** Because chats are ephemeral, the skill can emit your profile as its own tiny `sumble-profile-<company>` skill that you upload once. Then it's available in every conversation, on every surface, with nothing to re-attach. (On Claude Code or a connected folder, a plain file works too.)
- **Skipping the question doesn't stall it.** Skip and it takes the default — deep dive if you named a company, prioritize otherwise — tells you which one it took, and keeps going. Every decision it doesn't ask about has a documented prescription.
- **Prioritizing rolls straight into the work.** Rank your book and it deep-dives the top three and builds the deliverable, rather than stopping to ask which one you meant.
- **Nothing leaves without your say-so.** The two confirmations it does ask for — revealing contact details and pushing into a live sequence — both come after the deliverable already exists.

## The part that compounds

Most account research dies in a graveyard of browser tabs: you find the signal, you mean to write the email, the day moves on. This skill collapses finding, deciding, drafting, and sending into one conversation, and it remembers your ICP so the second account is faster than the first and the tenth is faster than the second.

Point it at the accounts your [account score](../../sumble-account-scoring/articles/01-account-score-should-tell-a-rep-what-to-do.md) flagged and the people your [people score](../../sumble-people-scoring/articles/01-people-scoring-use-cases.md) ranked, and the loop is closed: the model tells you where the revenue is, and this skill walks you to the first conversation that goes after it.
