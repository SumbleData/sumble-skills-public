# Account Scoring Should Explain, Not Just Rank

Most account scores spit out a number. The best ones explain why an account matters and what the first move should be.

**Skill:** [`sumble-account-scoring`](../SKILL.md). Run it in Claude Code, Codex, or Cursor.

*Part 1 of 2.* Part 2 — [A step by step guide to world class account scoring in under two hours](02-build-an-account-score-you-can-prospect-from.md).


## TLDR
- Show reps the rank and the linked evidence, not just the raw score.
- Break the score into segments you can read (e.g. size and growth/momentum).
- Avoid large accounts winning by default by using growth and concentration as attributes.
- Be wary of attributes that don't cover the whole corpus: funding data only exists for venture-backed companies, so scoring it artificially boosts startups.
- Calibrate your scores against closed-won accounts (or a subset of accounts that are a strong ICP fit).
- Use the same model to find whitespace accounts: strong-fit companies not yet in your CRM.


Most account scores get ignored. They're either a proxy for company size or a black-box number. Reps tune out the first because it says nothing new, and the second because they can't see why an account got an 82.

A score earns its place when a rep can read it, trust it, and act on it. A good score points the rep at a first move, not a grade. Every number Sumble provides is backed by the people, teams, and projects behind it.

## Why it's worth getting right

Done well, an account score ends up underneath a surprising number of go-to-market decisions:

- **Account allocation**: check that your best accounts are assigned to a rep instead of sitting unowned in the CRM.
- **Territory planning**: carve balanced books from a ranked, scored universe instead of by gut or geography alone.
- **Rep guidance**: tell each rep which of their accounts show the most promise right now, and why.
- **Whitespace**: point the same model at the accounts you don't have to find the net-new ones worth pursuing.
- **Account-based marketing**: focus ABM spend and air cover on the accounts the model says matter.
- **Lead routing**: when a lead comes in, its account score helps decide who works it and how fast.
- **Disqualification**: filter out accounts that aren't an ICP fit.

Get the score right once and it lifts the rest of your GTM engine.

The rest of this guide is the method, which we've also encoded into a skill that builds it for you.

## No black-box scores: reps should be able to inspect and act on the attributes

Firmographics describe a company at rest. The attributes that predict deals describe a company in motion.

Same account ([Walmart](https://sumble.com/orgs/walmart)) scored with 2 different approaches.

**Non-actionable score: 51.** Looks precise, but it doesn't tell the rep where to click first:

| Attribute | Detected value | Pts |
| --- | --- | --- |
| Employee size | 10,074 | +8 |
| Engineering headcount | 2,840 | +8 |
| LangChain | 287/365 | +11 |
| Pinecone | 96/365 | +4 |
| Qwen | 88/365 | +4 |
| Buying stage | Decision · 6QA | +9 |
| Account intent score | 88/100 | +7 |

**Actionable score: 86, rank #5 of 22,450 in CRM.** The same account scored on real Sumble attributes, broken into segments, with every line a deep link into the people, teams, and jobs behind it:

| Segment | Attribute | Value |
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

- **People**: how many of your target personas work there, what share of the company they make up, and whether that function is growing.
- **Technology**: how many of their teams use competitive and complementary technologies.
- **Active projects**: relevant migration or transformation work that indicates an open buying window.

When Sumble provides these attributes we also offer a **deep link**, so the score component can lead directly to outreach. If an attribute reads "55 teams at Walmart are using Langchain", the rep can [click through](https://sumble.com/orgs/walmart/teams?as=%7B%22operator%22%3A%22AND%22%2C%22children%22%3A%5B%7B%22operator%22%3A%22OR%22%2C%22fields%22%3A%7B%22technology%22%3A%7B%22include%22%3A%5B%22langchain%22%5D%7D%7D%2C%22children%22%3A%5B%5D%7D%5D%7D) to those teams and their key leaders. If it reads "200 AI Engineers at Walmart", they can [click through](https://sumble.com/orgs/walmart/people?as=%7B%22operator%22%3A%22AND%22%2C%22children%22%3A%5B%7B%22operator%22%3A%22OR%22%2C%22fields%22%3A%7B%22job_function%22%3A%7B%22include%22%3A%5B%22ai-engineer%22%5D%7D%7D%2C%22children%22%3A%5B%5D%7D%5D%7D) and drop those people straight into a sequence. Nobody has to ask why an account got an 84; the answer is a click away, with named contacts and a reason to reach out.

## Avoid having your model purely proxy company size

Enterprises have more of everything, so a model built on raw counts is a headcount ranking in disguise. A few fixes keep size from dominating. 

If your sweet spot is small but fast-growing, weight the growth attributes heavily, above all growth in your ICP personas. Fast-growing companies cross new scale points often, and each scale point is a moment they outgrow a tool and go looking for a new one, which makes them likely buyers of a modern solution. Lean on growth metrics here and the right accounts pop to the top: a company like Anthropic (~4K employees) can be every bit as compelling as a Walmart (2MM employees). On the flip side, a company that isn't growing often isn't in pain, because it isn't hitting the limits that trigger a change, so a big, static account can be a worse bet than a smaller one accelerating into your category.

If what matters is that your solution is central to the business, weight concentration: a high share of your ICP persona, or of teams running the relevant technologies. If you sell to DevOps engineers, a company where 5% of headcount is a DevOps engineer is a far better fit than one where it's 0.05%: your product sits at the core of how they operate, not off in a corner.

We also recommend a formula that keeps large outlier numbers from dominating the score; more on that in [part 2](02-build-an-account-score-you-can-prospect-from.md).

## Be wary of attributes that don't cover the whole corpus

The best attributes are ones every account could have a value for. If an attribute only exists for one slice of your universe, the model may end up overweighting membership in that slice.

Funding is the classic example. Funding data only exists for venture-backed companies: bootstrapped businesses, PE-owned companies, subsidiaries, and public companies all read as zero. Score "total raised" and every venture-backed startup gets an artificial boost, while everyone else is penalized for a data gap, not a fit gap. And what funding is meant to indicate (fresh budget, an imminent hiring ramp) often shows up in attributes that do cover everyone, such as headcount growth.


## Break the score into segments you can read


"Is this a good account?" hides several different questions, and the score is far more legible when its top level breaks them apart. We default to three **segments**, each answering one question, blended into a single number you can still take apart:

- **Size**: how big is the opportunity? Persona headcount, number of teams using competitive or complementary tech, recent project + technology hiring.
- **Growth & momentum**: is now the time? Growth in your ICP personas.
- **Concentration**: how strong is the fit? The size-neutral ratios: what share of the company is your ICP persona, what share of teams run your tech.

Reps get one number to act on; anyone who asks can see the three lenses behind it, weighted ~50/30/20 (size / growth & momentum / concentration). That's a default starting point; the model calibrates it to your won deals, and you can adjust it yourself.

The segments are yours to redefine: rename them, reweight them, or cut them a different way entirely. The most useful alternative is a business-unit breakdown: if you sell distinct product lines, give each its own segment (for Oracle, an OCI-fit segment and an Apps-fit segment, each with its own personas and technologies) and read a per-line score inside the same model. 


## Calibrate against the deals you've won

Weight factors so the scoring fits your closed-won accounts. If you do better with fast-growing companies, give growth in key personas a bigger weight. If you sell mostly to AI-native or digitally-native companies, boost them. If IT-services shops are partners rather than buyers, penalize that category. The same gold set powers an evaluation view: tune the weights and watch whether your known customers rise to the top.

## Start with one model, not a model per market

It's tempting to build separate scores for SMB, mid-market, and enterprise. Resist it. One model across all accounts is far easier to reason about and maintain, and it puts all your effort into getting a single thing right instead of keeping five things in sync. With the right features, especially size-neutral ones like concentration and growth, a single model that holds across the whole range is usually achievable. (Segments are different: those are lenses inside one model, and even a per-product-line breakdown is still a single score.) Build separate models only once you've proven one can't do the job.

## Show a rank, not a raw score, and rank within territories

A raw score is hard to interpret. Is 82 good? A rank is instantly legible: this is your #3 account. Treat the score as the engine and the rank as the interface: compute the score, then hand reps an ordered list.

One catch: a single global ranking can feel unfair, because a handful of reps own all the top accounts and everyone else feels stuck with leftovers. The fix is to rank within territories: SMB, Enterprise, Strategic, or by geography. This groups the ranking, not the model. One model still scores every account; you just order the results within each territory or size band.

## Re-run your scoring daily

Most accounts barely move from week to week. But periodically a new migration project kicks off or hiring surges in a key persona, and an individual account moves dramatically. If you see these movements before your competitors, that can make you the front-runner.

And if scoring is a daily job, it becomes one less thing to worry about. A score you rebuild by hand every quarter is a chore that rots between runs: someone has to remember to do it, the data drifts in the meantime, and you're never quite sure the list a rep is working is current.

## Use the same model to find whitespace accounts

The model you calibrate against your CRM is really a description of what your best customers look like, and nothing about that description limits it to accounts you already have. Turn it around and the same weights surface the companies that look like your customers but aren't in your CRM yet. That's whitespace, and it comes almost for free. A company you've never engaged has no first-party attributes to join, so whitespace runs the Sumble-only half of your model (same normalization, same calibration multipliers, weights re-normalized over what's left) across Sumble's whole universe, then subtracts the accounts you already own. 

This is why it beats a bought "lookalike" list. A purchased list is firmographics, the company-at-rest description this method warns against. Whitespace is built on your own won deals and on what companies are doing right now, and it's the same model you already watched sort your known customers to the top. Each account it surfaces lands with the people and the reasons to reach out already attached.


## The score is the start, not the end

To recap: observable attributes, normalized so size doesn't dominate, calibrated against your wins, and every component clickable through to the people, teams, and jobs a rep can act on today. That's the difference between a score that sits in a dashboard and one that drives outreach.

**[Part 2 — How to build exactly this against your own ICP, in an afternoon →](02-build-an-account-score-you-can-prospect-from.md)**
