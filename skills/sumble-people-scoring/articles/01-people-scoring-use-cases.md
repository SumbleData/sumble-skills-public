# Your lead score only ranks people who already found you

Most lead scoring re-sorts the contacts you happen to have. The best people scoring covers everyone who matters at the accounts you care about, met or not, and keeps that list alive every day.

**Skill:** [`sumble-people-scoring`](../SKILL.md). Run it in Claude Code, Codex, or Cursor.

*If you've read [Account Scoring Should Explain, Not Just Rank](../../sumble-account-scoring/articles/01-account-score-should-tell-a-rep-what-to-do.md),
this is the layer underneath: the people. It stands on its own if you haven't.*


## TLDR
- Score the whole buying committee at your target accounts: the people you've met and the people you haven't.
- The output worth having is a defined, ranked list of the people you'd like to meet inside every campaign account.
- Keep it as a persistent table in your warehouse or CRM, refreshed daily, so a job change shows up tomorrow, not at renewal.
- One people score becomes shared infrastructure for marketing, sales, and RevOps: routing, prioritization, campaign audiences, badge scans, event dinners.
- Calibrate against the contacts on your closed-won deals, show a rank instead of a raw score, and keep every row clickable to the why.


An account score answers "which companies." The question a rep faces at 9am is "who." Who at this account do I write to? Who gets
the event invite? Who does this inbound lead route to, and ahead of whom in
the queue?

Most lead scoring can't answer that, because it only scores people who already
found you. Form fills, badge scans, webinar registrations: your CRM contacts.
That's a ranking of your existing funnel, and your funnel is a thin,
self-selected slice of the people who matter. The director who'd sponsor the
deal has never downloaded your whitepaper. She doesn't have a score, so to
your systems she doesn't exist.

Comprehensive people scoring fixes the denominator: score everyone relevant at
the accounts you care about, whether or not you've ever spoken to them.

## Why it's worth getting right

Done well, a people score becomes one table the whole go-to-market motion
keys off:

- **Cold outbound**: the send list becomes the top N people per account by
  score, instead of whoever's email you happen to have or a purchased 3,000.
- **Campaign audiences**: a campaign aimed at your top 200 accounts is really
  aimed at the ~2,000 people inside them who can move a deal; the score picks
  who sees the ads and emails, and who to suppress so spend stops leaking.
- **Lead routing and prioritization**: an inbound lead's score answers "AE now, nurture, or nowhere" in one lookup, and orders the SDR queue by fit and engagement instead of recency of form fill.
- **Events**: who to invite, whose badge scan gets the first follow-up, and
  who makes the cut for the eight seats at the executive dinner: the
  top-scored people at attending accounts, including the ones you've never met, who are precisely the reason to go.
- **Multi-threading open deals**: every opportunity's missing people (the
  exec sponsor, the adjacent function, the backup champion) are a lookup, not
  a research project.
- **Coverage gaps at owned accounts**: the met/unmet split across a rep's
  book is a map of relationship debt: accounts one relationship deep, renewals
  where the champion left and nobody scored their replacement.
- **Job-change plays**: when a scored person or past champion lands somewhere
  new, that account just acquired a warm path, and the play writes itself.
- **Account planning**: the buying committee per account, written down and
  ranked, instead of reconstructed from memory in every QBR.

Each of these usually runs on its own ad-hoc people logic: a title filter here, a bought list there, a routing rule somebody wrote in 2023. One
calibrated score replaces them with a single answer to "who's next," and when
you tune it, every motion improves at once.

## Score the whole buying committee, not just your funnel

Two populations, one score:

**People you've touched.** Your CRM contacts. You know something about their
engagement with you. What you usually don't know is who they are now: current title, function, seniority, whether they still work there. Scoring
starts by re-enriching them against live data.

**People you've never met.** Everyone else in your target functions at the
accounts you're working: the platform leads, the RevOps directors, the VPs
whose names aren't in any of your systems. They can't be scored on engagement,
because there is none. They can be scored on fit: function, seniority, skills, and the strength of the account around them.

Both populations get the same score on the same scale, in one list. A rep opening an account sees the whole picture: touchpoints with three of the eleven people who matter, and the top two are people they've never spoken to. A funnel-only lead score can only re-sort the three.

**Want to see it live?** Explore the [people scoring demo](https://people-scoring-demo.sumble.com/): Sumble's own ICP across our top accounts, with met and unmet people on one ranked scale, with sliders to retune and every row clickable to the why. For demonstration purposes only.

## What goes into the number

The same discipline as the account score: observable attributes, normalized,
calibrated, and clickable.

- **Function fit.** Is this person in a role you sell to, and how senior?
  The two interact: if you sell to RevOps, a RevOps analyst and a VP of RevOps
  are different conversations. The score interpolates by seniority within each function, so your true buyer's function outranks an adjacent one at
  every level.
- **Seniority.** On its own, too: a CXO at a fit account is worth a look even
  when the function mapping is fuzzy.
- **Skills.** The tools on a person's profile, normalized against a technology
  catalog. Someone listing your competitor's product is telling you they run
  it, evaluate it, or built their workflow around it. No form fill tells you that.
- **Account context.** A person inherits the strength of their account. Your
  account score flows in as a factor, so a director at your #4 account
  outranks the same title at account #400.
- **Engagement, where it exists.** First-party engagement (event attendance, product usage, email response) joins as a weighted factor for the people
  who have it, and contributes zero for the people who don't. Engagement
  raises a person's score; its absence doesn't hide them.

## Keep it as a persistent table, not a campaign export

Most teams skip this piece. A people list built for one campaign is stale the day the campaign ends. The version that compounds is a persistent table in your data warehouse or CRM: every person you could want to target or know, scored, refreshed daily.

Daily matters because people move. Champions change jobs, buyers get promoted
into budget, the VP you've been sequencing leaves the account mid-deal. A
quarterly-rebuilt list misses all of it; a daily-refreshed table surfaces each
move the morning after it happens, and you're the first vendor to know instead of the fifth.

Persistence is also what makes the score shared infrastructure: the router,
the campaign tool, the event team, the SDR queue, and account planning all
read the same table, so marketing, sales, and RevOps stop maintaining three
contradictory definitions of "who matters." Set it up once, let it recompute
every morning, and the only time you touch it again is when your ICP changes.

## The practice notes

Short, because the method carries over from account scoring almost untouched:

- **Rank, don't score.** "Your #2 person at this account" beats "score: 71."
  Rank within the account for deal work, within territory for queues.
- **Calibrate on closed-won contacts.** The buying committees of your won
  deals already encode who the real committee was. Fit the weights to them,
  and only keep the fit when it holds up out of sample.
- **One model.** Resist building one per persona, segment, and campaign. The interactions
  live in the features (the function and seniority interaction handles most of what per-persona models pretend to do); the variations live in how you slice the ranking.
- **Keep it clickable.** Every scored person should link to who they are and
  why they scored: profile, function, the skills that matched. A rep who can
  see the why writes the first line of the email from it.

## The list is the strategy

Account scoring tells you where the revenue is. People scoring tells you who to meet to go get it, especially the people who have never heard of you. Teams that do this stop asking "who should we reach out to?" in a meeting every quarter. The answer sits in a column that was updated this morning.
