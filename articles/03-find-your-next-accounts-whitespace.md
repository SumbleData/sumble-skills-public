# Find your next accounts with the score you already built

*Part 3 of 3.* Part 1 — [An account score should tell a rep what to do](01-account-score-should-tell-a-rep-what-to-do.md) — lays out the method; Part 2 — [Build an account score you can prospect from](02-build-an-account-score-you-can-prospect-from.md) — builds it against your CRM. This part points the same model at the companies you're not selling to yet.

Parts 1 and 2 ended with a tuned account score and a ranked CRM. But the most valuable thing you built isn't the ranking — it's the *model*: a calibrated description of what your best customers look like. And nothing about that description says it can only be aimed at accounts you already have. Turn it around and the same weights surface the companies that look exactly like your customers but aren't in your CRM yet. That's whitespace — and you get it almost for free once the score exists.

## The same model, minus what only your customers have

Your account score has two kinds of inputs: Sumble's observable signals (personas, tech teams, active projects, growth) and your **first-party** signals (webinar attendance, free-tier usage, email response). For a company you've never engaged, every first-party signal is zero — they've never touched you, so there's nothing to join. Whitespace simply runs the Sumble-only half of your model.

Concretely, the whitespace tool imports the `account-scoring-weights.json` you saved in Part 2, **drops the first-party categories, and re-normalizes** the remaining weights so they still sum to 100. Everything else carries over untouched: the same p99 normalization, the same calibration multipliers, the same fit-vs-intent split. You're not building a second model — you're running the one you already tuned, with the columns a stranger can't have removed.

This is a feature, not a compromise. The Sumble signals are exactly the *in-motion* signals from Part 1, and they exist for every company in Sumble's universe whether or not you've ever heard of them. First-party data was always the part you could only have for accounts you'd already touched. Whitespace is about the accounts you haven't.

## Bring your CRM — to subtract it

Whitespace ranks all of Sumble's universe by your ICP, then **removes everything already in your CRM**. So the one upload that matters here is your full CRM account list: you don't want a net-new ranking cluttered with accounts a rep already owns. What's left is genuinely net-new.

One useful wrinkle: candidates whose **parent** company is already a CRM account get split into a separate **Subsidiaries** tab. Those aren't cold whitespace — they're land-and-expand into an account where you already have a foot in the door.

And if you bring your closed-won list too, it calibrates exactly as it did in Part 2: the tag-lift multipliers that reward digital-native, penalize IT-services partners, and so on are learned from your wins and applied straight to the whitespace pool.

## Set the universe

A few filters keep the ranking aligned with how you actually sell:

- **HQ country** — restrict to the geos you cover, or leave it global.
- **Minimum headcount** — defaults to >50 to drop micro-companies.
- **Hard excludes** — org types you never sell to. Schools, universities, hospitals, and government default out for most B2B sellers. IT-services and professional-services firms are worth excluding too: they pile to the top of any competitor-tech ranking as *partners* implementing the tools, not buyers of them.

## Rank, tune, click through — into companies you've never contacted

It's the same app as Part 2: drag the sliders, the ranking re-sorts instantly, open any account for a per-signal breakdown. The difference is what sits behind each row. Instead of a familiar account, it's a company you've never spoken to — and **every Sumble signal still deep-links into the people, teams, and jobs behind it**. So your #1 whitespace account doesn't arrive as a name to go research; it arrives with its recruiters, its teams running your competitor's tool, and its active project all one click away.

Start with a pool of ~1,000 candidates — fast to eyeball and cheap to iterate on while you sanity-check the ICP — before committing to a larger run. The tool shows a credit estimate before any pull.

## Score the long tail, hand reps the rank

Just like Part 2, **Save** writes your weights plus a ranked `data.csv`, and the portable `score_accounts.py` re-runs the same model against the public API on a much larger candidate list — anywhere with Python, no internal access. What you hand reps is the **rank**, segmented by territory or size band so every rep has a clear top of their own net-new book.

The math is identical to Part 2's — see [that appendix](02-build-an-account-score-you-can-prospect-from.md#appendix-the-scoring-mathematics) for the formula. Whitespace just runs it with the first-party signals removed and the weights re-normalized across what's left.

## Why this beats buying a list

A bought "lookalike" list is built on firmographics — the same company-at-rest description Part 1 warned against. Whitespace is built on your own won deals and on what companies are *doing right now*. And because it's the same model you already trust on your CRM, you don't have to take it on faith: you watched it sort your known customers to the top in the Evaluation tab. The accounts it surfaces are the ones that model says come next — and each one lands with the people and the reasons to reach out already attached.

---

*Build this with the [`sumble-account-whitespace`](../skills/sumble-account-whitespace) skill — install instructions are in the [repo README](../README.md).*
