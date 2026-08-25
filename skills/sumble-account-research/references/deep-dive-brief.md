# Building a single-account deep dive

One account, one page, one argument. Template: `assets/deep-dive-template.html`. Fill the
`{{TOKENS}}` and duplicate the repeating blocks. Build from research you already ran in
Step 2; no new queries. Hold every line to `references/writing-rules.md`.

Use this when the seller is working one named account. For a book of accounts, use
`references/prioritization-brief.md` instead. The two are a matched pair and share a
visual system, so a rep can carry both into the same meeting.

**Sumble-branded by design.** This is an internal research artifact, not a prospect-facing
deck, so it skips `references/branding.md`. The template already carries the brand: one
emerald accent (`#16a34a`) on slate and white, the Sumble mark, Inter with JetBrains Mono
for data. Don't recolor it to the prospect or the seller.

## The spine

Keep this order. It is the argument, not a layout, and every section answers the question
the one above it raises.

| Section | What it has to do | Fed by |
|---|---|---|
| Thesis + stat tiles | State the consequence and back it with 3-4 numbers | What's the Angle |
| Verdict | Work it or don't, and the one reason | What's the Angle |
| Signal footprint | Show the footprint as bars, so scale is visible not asserted | The Intel |
| Their stack | Separate confirmed adoption from postings-only mentions | The Intel |
| Three doors | Three ways in, each a named team with its lead and an entry point | Which Teams Are The Best Fit |
| Why now | Dated triggers, newest first | Recent Changes |
| The plays | One card per play: evidence, the call, what to test | your own sales plays |
| Who to contact first | Ranked live people, role-tagged, CRM status, fit score, scored reporting lines | Who To Contact First |
| Messaging | One copy-ready message per door | none |
| Evidence receipts | Every number, with the link that proves it | none |
| Limits & method | The query, and what this brief cannot see | none |

## Where the content comes from

`GetIntelligenceBrief` (50 credits, async, 422 when the org is too thin) returns a single
markdown `body` under five headings: **What's the Angle**, **Who To Contact First**, **The
Intel**, **Which Teams Are The Best Fit**, **Recent Changes**. The "Fed by" column above maps
each onto a section here, so the page and the product speak one vocabulary. The API brief is
a good first draft of the content and a poor final artifact: it is prose with no layout, no
verdict, no method, and no separation of confirmed adoption from mentions. Reps who receive
one unrendered describe it as a wall of text and put it down.

Two fields in the API brief have no hand-built equivalent, so carry them through rather than
re-deriving them:

- **CRM status per contact** — the brief marks each person `(CRM Status: Contact)`,
  `(CRM Status: Lead)`, or `(No matching CRM record)`. Render it as the `.crm` chip, and use
  `class="crm white"` for no match: an unknown name at a live account is whitespace the rep
  should see, not a blank.
- **Fit score per contact** — render as the `.fit` chip. Omit the chip rather than guess a
  number.

The last three sections have no API source at all. They are the reason a rendered brief beats
the raw one, so don't skip them because the API didn't hand them to you.

Two sections carry more weight than their size suggests. **Verdict** is what a busy rep
reads instead of the page, so it has to survive alone. **Limits & method** is what makes the
rest credible; a brief with no stated method reads as a black box, and the first number a
rep can't trace kills the whole document.

## Rules that decide whether it lands

**The `<h1>` is an argument, never a label.** "IBM already owns the tools Salesforce builds
on." Not "Account overview: Salesforce". The reader should know your conclusion before
they scroll. If you can't write that sentence, you don't have a brief yet, you have a data
dump.

**Numbers arrive in the first 200 words, each with a direction.** Not "Salesforce uses
Terraform" but "Terraform in 1,283 job posts across 370 teams, up 54.8% year over year".
A count with no trend and no denominator tells a rep nothing they can act on. The stat
tiles repeat those same figures; they are not a second set.

**Three doors, not one.** A single contact is a single point of failure, and a rep who gets
ignored once has nothing left. Each door needs **a real team, named, with its lead**, plus its
own wedge and its own entry point with their reports rolled up ("5 directors + 5 sr managers").
The API brief's best-fit teams are the natural source: one team becomes one door, and its
leader goes on the door. A door with no named team is a guess, so cut it rather than ship it.
Two doors is acceptable when the account genuinely has two. One is not a door.

**Every claim traces to a Sumble field, a pulled internal record, or a cited web source.**
No invented numbers, names, or quotes. Round numbers you didn't measure are the fastest way
to lose a rep's trust. Always include the deep link.

**Tech `used` is adoption; tech `mentioned` is a mention.** A person's listed technology is
their experience, not proof the company runs it. Tag postings-only tools `um-weak` and say
so in the estate section.

### The call line

One quoted sentence per play, in the seller's voice, and it **names the product**.

- **Open on their situation, land on the product.** Their evidence earns the sentence; the
  product answers it. "You're running Splunk at real scale and paying for every gigabyte you
  index, and that's what our tiered storage is for" works. "Have you considered our tiered
  storage?" does not. Same content, different order, completely different call.
- **Name the specific module, not the company.** Add a reference customer with a concrete
  outcome as a trailing `.proof` span only when you actually have one. Take it from whatever
  the seller uploaded at Step 1c first, because `GetMyCompanyProfile` does not reliably return
  reference customers or outreach examples. If neither has one, drop the span rather than
  inventing an outcome.
- **Use their words.** Where the seller uploaded plays, battlecards or emails that worked, the
  play names, the product naming and the sentence rhythm all come from those, not from your
  own phrasing or from the profile's summary.
- **The product must match the card's play badge**, or the badge is decoration.
- **Never Sumble vocabulary.** No "used/mentioned", no "N postings", no "Sumble sees", no
  raw counts. The prospect has never heard of Sumble. Counts live in the evidence box and
  the estate tags, which are the analyst's voice for the rep's eyes.

**What to test** goes back to listening: the rep's curiosity, not a second pitch. The call
already named the product. Bold the one key qualifier and write natural sentences, not
`**Label:** sentence` bullets.

## Who to contact first, and the reporting fan-out

The section is named for the question a rep asks first, but the buying-group structure stays:
role chips for economic buyer, champion and multithread, and a scored reporting line per
person. Order the rows, don't just list them, and say in each row's why-line what puts that
person above the one below.

**Freshness gate first.** Only people currently at the company. Verify each name against the
web or a current LinkedIn role before it goes on the page. Departed means drop: don't list
them, don't anchor a door on them, don't reveal their contact details. Active but with a
stale Sumble record (wrong title, mislabeled, zero reports) means keep, but show the
**verified current title** and note the record is stale. A departed champion on the page
discredits every other line.

**One call gets the scores and both links.** `FindMatchAndEnrichPeople` in match mode,
batching every contact by `person_id` / `linkedin_url`, with the reporting line requested
*inside* `related_people`:

```
attributes:      ["name","job_title","job_level","linkedin_url","location","current_employer"]
related_people:  { direction: ["direct_reports"],
                   attributes: ["name","job_title","job_level","linkedin_url","confidence"] }
```

Three things about that call, each of which is a hard validation error rather than a warning:
`confidence` is valid **only** inside `related_people`; `person_score` is filter-mode only,
so it cannot appear in match mode at all; and omitting the inner `attributes` returns bare
ids with no names and no scores.

**Both links per person.** LinkedIn *and* the `sumble_url` the API returns, on anchor rows
and fan rows alike. The Sumble page is where the rep sees the full confidence-scored roll-up.

**The score.** `.fan-rank` is each related person's `confidence.score`, a 0-1 float at the
**top level** of the report object, not under `attributes`. Convert to the web app's 1-10
exactly: `ceil(score*100)/10`, so `0.3865` becomes `3.9` and `0.4654` becomes `4.7`. Rank
each contact's reports by score and show the top five.

**Direction.** Use `direct_reports` only. The `managers` direction is near-empty for senior
contacts, because a CXO rarely has an inferred manager, so never render an empty upward fan.
Express the path to the buyer in the `.bg-path` prose instead.

**Every listed contact gets a block, no silent omissions.** For each contact render either
their own `.fan` with rows, or a `.fan-none` note saying why there isn't one: no reports
mapped in Sumble, shown as a report under someone above, or the line is already on another
card. A noisy or off-target line (common for CXOs) gets a `.fan-none` too. Never pad a fan
with people who don't belong in it. **Self-check before delivering: per card, the count of
`.contact-row` blocks must equal the count of `.fan` blocks.**

**Anchoring the team.** Use a real, navigable Sumble team, taken from the team that recurs
across your contacts' `confidence.matched_features` with `match_type:"team"`. Roster link is
slug form: `https://sumble.com/orgs/<org-slug>/teams/<team-slug>/people`, text "See who's on
this team →". **Expect no curated team.** Below roughly 250 employees, and often above it,
no `match_type:"team"` feature comes back at all; the org-level cluster whose slug is just
the company name is not a team. When that happens, name the group by the function you're
selling into and point the roster at `https://sumble.com/orgs/<org-slug>/people` with text
"See who Sumble links to this org →", noting it in `.bg-path`.

**Load-bearing honesty.** The fan-out is an inferred map from shared signals, the same figure
shown on each person's Sumble page. It is a suggested map, not a confirmed org chart, and the
score is confidence-the-person-sits-in-that-line, not confidence-the-play-lands. Keep that
wording in Limits & method.

## Evidence receipts

One row per number you used: the claim, the figure, and the link. This is the section that
lets a rep put the brief on screen in front of the customer, and it's the cheapest section to
build because you already have every link. If a number can't get a row, cut the number.

## Deliver

Write the `.html` and hand it back. In Claude Code or a connected folder that means to disk;
in ephemeral chat, as a downloadable file. Reveal email or phone only for the top two or
three contacts, and only if the user wants to act; the brief stands on its own without
reveals.

**Publishing it as a hosted page needs one change.** The template references the Sumble mark
as `sumble-eyes-logo-512.png` next to it, which resolves on disk but not once the page is
hosted, and a strict artifact CSP blocks remote images outright. Base64-encode
`assets/sumble-eyes-logo-512.png` into a `data:image/png;base64,` URI in both the nav and the
footer before publishing. Use the official bundled asset only: never redraw, recolor, or
substitute an inline SVG for the Sumble logo. If the asset isn't available, omit the mark and
tell the user.
