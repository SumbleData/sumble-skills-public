# Account Scoring Should Explain, Not Just Rank

Most account scores spit out a number. The best ones explain why an account matters and what the first move should be.

*Part 1 of 2.* Part 2 — [A step by step guide to world class account scoring in under two hours](02-build-an-account-score-you-can-prospect-from.md).


## TLDR
- Show reps the rank and the linked evidence, not just the raw score.
- Break the score into segments you can read (e.g. size and growth/momentum).
- Avoid large accounts winning by default by using growth and concentration as attributes.
- Calibrate your scores against closed-won accounts (or a subset of accounts that are a strong ICP fit).
- Use the same model to find whitespace accounts — strong-fit companies not yet in your CRM.


Most account scores get ignored. They're either a proxy for company size or a black-box number. Reps tune out the first because it says nothing new, and the second because they can't see why an account got an 82.

A score earns its place only if a rep can read it, trust it, and *act on it*. A good score doesn't hand a rep a grade — it points them at their first move. Every number Sumble provides is backed by the people, teams, and projects behind it.

## Why it's worth getting right

Done well, an account score becomes load-bearing infrastructure for the whole go-to-market motion — the thing a surprising number of decisions quietly key off:

- **Account allocation** — make sure your best accounts are actually assigned to a rep, not stranded unowned in the CRM.
- **Territory planning** — carve balanced books from a ranked, scored universe instead of by gut or geography alone.
- **Rep guidance** — tell each rep which of their accounts show the most promise *right now*, and why.
- **Whitespace** — point the same model at the accounts you *don't* have to find the net-new ones worth pursuing.
- **Account-based marketing** — focus ABM spend and air cover on the accounts the model says matter.
- **Lead routing** — when a lead comes in, its account score helps decide who works it and how fast.
- **Disqualification** - Filter out accounts that aren't an ICP fit

Get the score right once and it lifts the rest of your GTM engine. That's the payoff that justifies meaningful attention.

Here's the method, as we've encoded it into a skill that builds this for you.

## No black-box scores — reps should be able to inspect and act on attribute

Firmographics describe a company at rest. The signals that predict deals describe a company in motion.

Same account ([Walmart](https://sumble.com/orgs/walmart)) scored with 2 different approaches.

**Non-actionable score: 51** — looks precise, but it doesn't tell the rep where to click first:

| Signal | Detected value | Pts |
| --- | --- | --- |
| Employee size | 10,074 | +8 |
| Engineering headcount | 2,840 | +8 |
| LangChain | 287/365 | +11 |
| Pinecone | 96/365 | +4 |
| Qwen | 88/365 | +4 |
| Buying stage | Decision · 6QA | +9 |
| Account intent score | 88/100 | +7 |

**Actionable score: 86 — rank #5 of 22,450 in CRM** — the same account scored on real Sumble signals, broken into segments, with every line a deep link into the people, teams, and jobs behind it:

| Segment | Signal | Value |
| --- | --- | --- |
| Size | LangChain | 38 teams |
| Size | Software Engineer | 18,322 people |
| Size | Pinecone | 22 teams |
| Size | AI Engineer | 208 people |
| Size | Qwen | 14 teams |
| Growth & momentum | GenAI projects (last 3mo) | 22 |
| Growth & momentum | AI Engineer | +27% YoY |
| Growth & momentum | Software Engineer | +2% YoY |
| Concentration | LangChain | 0.5% of teams |
| Concentration | Software Engineer | 6.2% of staff |
| Concentration | AI Engineer | 0.07% of staff |

Bias towards attributes that reps can understand and take action on. Some examples: 

- **People** — how many of your target personas work there, what share of the company they make up, and whether that function is *growing*.
- **Technology** — how many of their *teams* use competitive and complementary technologies.
- **Active projects** — relevant migration or transformation work that signals an open buying window.

When Sumble provides these attributes we also offer a **deep link**, so the score component can lead directly to outreach. An attribute that reads "55 teams at Walmart are using Langchain"? [Click through](https://sumble.com/orgs/walmart/teams?as=%7B%22operator%22%3A%22AND%22%2C%22children%22%3A%5B%7B%22operator%22%3A%22OR%22%2C%22fields%22%3A%7B%22technology%22%3A%7B%22include%22%3A%5B%22langchain%22%5D%7D%7D%2C%22children%22%3A%5B%5D%7D%5D%7D) to those teams (as well as the key leaders on those teams). "200 AI Engineers at Walmart"? [Click through](https://sumble.com/orgs/walmart/people?as=%7B%22operator%22%3A%22AND%22%2C%22children%22%3A%5B%7B%22operator%22%3A%22OR%22%2C%22fields%22%3A%7B%22job_function%22%3A%7B%22include%22%3A%5B%22ai-engineer%22%5D%7D%7D%2C%22children%22%3A%5B%5D%7D%5D%7D) and drop them straight into a sequence. The rep never asks "why an 84?"; they click, get context and named contacts and a reason to reach out.

## Avoid having your model purely proxy company size

Enterprises have more of everything, so raw counts are just a headcount ranking in disguise. The best models avoid being a proxy for company size. A few fixes keep size from dominating. 

If your sweet spot is small but **fast-growing**, weight the growth signals heavily — above all, growth in your ICP personas. Fast-growing companies cross new scale points often, and each scale point is a moment they outgrow a tool and go looking for a new one, which makes them fertile ground for a modern solution. Lean on growth metrics here and the right accounts pop to the top: a company like Anthropic (~4K employees) can be every bit as compelling as a Walmart (2MM employees). On the flip side, a company that isn't growing often isn't in pain, because it isn't hitting the limits that trigger a change — so a big, static account can be a worse bet than a smaller one accelerating into your category.

If what matters is that **your solution is central** to the business, weight concentration — a high share of your ICP persona, or of teams running the relevant technologies. If you sell to DevOps engineers, a company where 5% of headcount is a DevOps engineer is a far better fit than one where it's 0.05%: your product sits at the core of how they operate, not off in a corner.

We also recommend a formula that keeps large outlier numbers from dominating the score — more on that in [part 2](02-build-an-account-score-you-can-prospect-from.md).


## Break the score into segments you can read


"Is this a good account?" hides several different questions, and the score is far more legible when its top level breaks them apart. We default to three **segments** — orthogonal lenses that each answer one question, blended into a single number that stays fully decomposable:

- **Size** — how big is the opportunity? Persona headcount, number of teams using competitive or complementary tech, recent project + technology hiring, total funding raised.
- **Growth & momentum** — is now the time? ICP-persona growth and funding momentum (a recent, large round).
- **Concentration** — how strong is the fit? The size-neutral ratios: what share of the company is your ICP persona, what share of teams run your tech.

Reps get one number to act on; anyone who asks can see the three lenses behind it, weighted ~50/30/20 (size / growth & momentum / concentration) — a default starting point the model then calibrates to your won deals, and fully adjustable.

And the segments are yours to redefine. Rename them, reweight them, or cut them a different way entirely — the most useful alternative being a **business-unit breakdown**: if you sell distinct product lines, give each its own segment (for Oracle, an OCI-fit segment and an Apps-fit segment, each with its own personas and technologies) and read a per-line score inside the same model. 


## Calibrate against the deals you've won

Weight factors so that your scoring does a good job of fitting to your closed-won accounts. Do you tend to do better with fast-growing companies? Give growth in key personas a bigger weight. Do you typically sell to AI-native or digitally-native companies? Give those companies a boost. Are IT-services shops partners, not buyers? Give that category a penalty. The same gold set powers an evaluation view: tune the weights and watch whether your known customers actually rise to the top.

## Start with one model, not a model per market

It's tempting to build separate *scores* for SMB, mid-market, and enterprise. Resist it. One model across all accounts is far easier to reason about and maintain, and it puts all your effort into getting a single thing right instead of keeping five things in sync. With the right features — especially size-neutral ones like concentration and growth — a single model that holds across the whole range is more often achievable than not. (This is different from the *segments* above: those are lenses inside one model — even a per-product-line breakdown is still a single score — not separate models you have to keep in sync.) Reach for genuinely separate models only once you've proven one can't do the job.

## Show a rank, not a raw score — and rank within territories

A score is hard to make mean anything. Is 82 good? A **rank** is instantly legible: *this is your #3 account.* So treat the score as the engine and the rank as the interface — compute the score, then hand reps an ordered list.

One catch: a single global ranking can feel unfair and demotivating — a handful of reps own all the top accounts and everyone else feels stuck with leftovers. The fix is to **rank within territories** — SMB, Enterprise, Strategic, or by geography. Note this groups the *ranking*, not the model: the one model still scores every account; you just order the results within each territory or size band.

## Re-run your scoring daily

Most accounts barely move from week to week. But periodically there are big funding events and new migration projects that can have a dramatic impact on individual accounts. If you see these movements before your competitors, that can make you the front-runner.

Also, if scoring is a daily job, it becomes **one less thing to worry about**. A score you rebuild by hand every quarter is a recurring chore that quietly rots between runs: someone has to remember to do it, the data drifts in the meantime, and you're never quite sure the list a rep is working is current.

## Use the same model to finds whitespace accounts

The model you calibrate against your CRM is really a description of what your best customers look like — and nothing about that description says it can only be aimed at accounts you already have. Turn it around and the same weights surface the companies that look like your customers but *aren't* in your CRM yet. That's whitespace, and it comes almost for free: a company you've never engaged has no first-party signals to join, so whitespace just runs the Sumble-only half of your model — same normalization, same calibration multipliers, the weights re-normalized over what's left — across Sumble's whole universe, then subtracts the accounts you already own. 

This is why it beats a bought "lookalike" list. A purchased list is firmographics — the company-at-rest description this method warns against. Whitespace is built on your own won deals and on what companies are *doing right now*, and it's the same model you already watched sort your known customers to the top. The accounts it surfaces are the ones the model says come next — each landing with the people and the reasons to reach out already attached.


## The score is the start, not the end

Observable signals, split into how-big and how-now, normalized so size doesn't dominate, calibrated against your wins — and every component clickable through to the people, teams, and jobs a rep can act on today. The number says where to start; the links say what to say. That's the difference between a score that sits in a dashboard and one that drives outreach.

**[Part 2 — How to build exactly this against your own ICP, in an afternoon →](02-build-an-account-score-you-can-prospect-from.md)**
