# An account score should tell a rep what to do — not just rank accounts

*Part 1 of 3.* Part 2 — [Build an account score you can prospect from](02-build-an-account-score-you-can-prospect-from.md). Part 3 — [Find your next accounts (whitespace)](03-find-your-next-accounts-whitespace.md).

Most account scores get ignored. They're either firmographics dressed up as a model, or a black-box number from a vendor. Reps tune out the first because it says nothing new, and the second because they can't see why an account got an 82.

A score earns its place only if a rep can read it, trust it, and *act on it*. A good score doesn't hand a rep a grade; it points them at their first move. Every number Sumble provides is backed by the people and teams behind it, which a rep can see and act on.

Here's the method, as we've encoded it into a tool that builds this for you.

## Score what a company does — and link straight to the action

Firmographics describe a company at rest. The signals that predict deals describe a company in motion — and **Sumble provides all four of these out of the box**, mapped to every company:

- **People** — how many of your target personas work there, what share of the company they make up, and whether that function is *growing*.
- **Technology** — how many of their *teams* run the tools in your competitive and complementary set.
- **Active projects** — recent job posts pairing an initiative you care about with one of your tools or personas: an open buying window.
- **Funding** — total raised, last round size, and how recently it closed.

The part that makes it live: each Sumble signal is a **deep link** — and that's more than showing your work, it's the action itself. A signal reads "20 teams using your legacy competitor"? Click through and see exactly who those teams are and what they do — your displacement targets, named. "20 people in your ICP job function"? Click through, see who they are, and drop them into a sequence. The score component *is* the prospecting list. The rep never asks "why an 84?" — they click, get named contacts and a reason to reach out, and start the conversation. Not a lifeless number; a queue of next moves.

Then layer in what only *you* know. The same model takes your **first-party signals** alongside Sumble's: marketing engagement (webinar and event attendance, whitepaper downloads, ad and email response) and PLG activity (who's on your free product, and how heavily they use it). Join them by account and they become weighted factors like any other — so a company that fits your ICP *and* showed up to your webinar *and* has ten active free-tier users floats to the top, with each of those reasons spelled out in the breakdown.

## Blend "how big" and "are they ready to buy now?"

Two questions hide inside "is this a good account?": *how large could the deal be* (fit and size) and *are they in a buying window right now* (intent). We blend them into one number but also allow them to be decomposed into two visible halves — fit/size and intent — weighted ~60/40 by default, both adjustable.

## Normalize so size doesn't win by default

Enterprises have more of everything, so raw counts are just a headcount ranking in disguise. Two fixes: compress counts and squash them against the 99th percentile (the gap between 2 and 20 matters more than 200 vs 400, and one outlier can't peg the scale), and score *concentration* — "what share of the company is my ICP persona" — which is size-neutral. Recency gets inverted on purpose: fewer days since a fundraise means a higher score as you move further from a funding event.

## Tilt the model toward the companies you can win

Normalizing stops size from winning *by accident*. The next move is to decide, on purpose, which kind of company you want at the top — because that depends on what you sell, and the size-neutral signals are the levers.

If your sweet spot is **small but fast-growing**, weight the *growth* signals heavily — above all, growth in your ICP personas. Fast-growing companies cross new scale points often, and each scale point is a moment they outgrow a tool and go looking for a new one, which makes them fertile ground for a modern solution. The flip side is just as useful: a company that *isn't* growing usually isn't in pain, because it isn't hitting the limits that trigger a change — so a big, static account can be a worse bet than a smaller one accelerating into your category.

If what matters is that **your solution is central** to the business, weight *concentration* instead — a high share of your ICP persona, or of teams running the relevant technologies. A company where your buyer is 8% of headcount rather than 0.3% is one where your product sits at the core of how they operate, not in a corner of it.

## Calibrate against the deals you've won

Weight factors so that your scoring does a good job of fitting to your closed-won accounts. Do you tend to do better with fast-growing companies? Give growth a bigger weight. Do you typically sell to AI-native or digitally-native companies? Give those companies a boost. Are IT-services shops partners, not buyers? Give that category a penalty. The same gold set powers an evaluation view: tune the weights and watch whether your known customers actually rise to the top.

## Start with one model, not a model per segment

It's tempting to build separate scores for SMB, mid-market, and enterprise — or a different model per product line. Resist it. One model across all accounts is far easier to reason about and maintain, and it puts all your effort into getting a single thing right instead of keeping five things in sync. With the right features — especially size-neutral ones like concentration and growth — a single model that holds across the whole range is more often achievable than not. Reach for per-segment models only once you've proven one genuinely can't do the job.

## Show a rank, not a raw score — and rank within segments

A score is hard to make mean anything. Is 82 good? A **rank** is instantly legible: *this is your #3 account.* So treat the score as the engine and the rank as the interface — compute the score, then hand reps an ordered list.

One catch: a single global ranking can feel unfair and demotivating — a handful of reps own all the top accounts and everyone else feels stuck with leftovers. The fix is to **rank within segments** — SMB, Enterprise, Strategic, or by territory. Note this segments the *ranking*, not the model: the one model still scores every account; you just order the results within each segment.

## Re-run your scoring daily

The case for scoring daily isn't that accounts change wildly overnight — most accounts barely move from week to week. But periodically there are big funding events and new migration projects that can have a dramatic impact on individual accounts. If you see these movements before your competitors, that can make you the front-runner.

Also, if scoring is a daily job, it becomes **one less thing to worry about**. A score you rebuild by hand every quarter is a recurring chore that quietly rots between runs: someone has to remember to do it, the data drifts in the meantime, and you're never quite sure the list a rep is working is current.

## The score is the start, not the end

Observable signals, split into how-big and how-now, normalized so size doesn't dominate, calibrated against your wins — and every component clickable through to the people, teams, and jobs a rep can act on today. The number says where to start; the links say what to say. That's the difference between a score that sits in a dashboard and one that drives outreach.

**[Part 2 — How to build exactly this against your own ICP, in an afternoon →](02-build-an-account-score-you-can-prospect-from.md)**
