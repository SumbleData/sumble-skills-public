# Building an account prioritization brief

A book of accounts, ranked, on one page. Template: `assets/prioritization-template.html`.
Fill the `{{TOKENS}}`, put the accounts in the `ACCOUNTS` array, and duplicate the repeating
blocks. Hold every line to `references/writing-rules.md`.

Use this for a territory, a segment, a target list, or a pile of event leads. For one named
account, use `references/deep-dive-brief.md` instead. The two share a visual system on
purpose: the usual sequence is a prioritization brief for the book, then a deep dive on the
top few, and a rep should recognise the second as the same family as the first.

**Sumble-branded by design**, like the deep dive. One emerald accent (`#16a34a`) on slate
and white, the Sumble mark, Inter with JetBrains Mono for data. Skip
`references/branding.md`; that file is for prospect-facing decks and plans.

## The spine

| Section | What it has to do |
|---|---|
| Thesis + ranking basis | State the finding, then the method, in the first screen |
| Stat tiles | 3-4 numbers describing the board as a whole |
| Funnel | TAM to SAM to ICP, so "top 20" has a denominator |
| Why this list is different | The one thing their CRM could not have told them |
| Ranked board | One row per account, each with a reason; the top 3-5 expand in place |
| Scoring model | The weights, published |
| Traps & dead zone | What not to work, and why |
| Limits & method | The exact query, and anything truncated |

## Rules that decide whether it lands

**The ranking basis goes in the subtitle, never buried.** "Ranked by SDR headcount, global,
excluding IN/PK/CO/PH/BR/AE, ICP filter 3+ SDRs and 2 GTM tools." A rep has to be able to
argue with the method in the first five seconds. A ranked list whose ranking rule is
invisible is a black box, and reps do not work black boxes; they work the two names they
already recognise and ignore the rest.

**Give the list a denominator.** "Top 20" means nothing without the pool it came from. The
funnel does that work in three numbers: the total addressable population, the slice that
matches the shape you sell to, and the set that clears the ICP bar. Then the board shows the
top N of the last one.

**Every row earns its place with a reason, never a bare score.** The `why` field is a play,
a tech match, or a dated trigger: "new VP Data started May 2026", "runs the competitor you
displace across three teams". "Score: 92" is not a reason, and a column of scores with no
reasons trains reps to distrust the ranking.

**Rank on fit and on triggers, and keep them distinct.** An account is worth working now for
either of two independent reasons: it is a great account in the abstract, or something just
happened. Sweep the whole list for signals, never just the high-fit rows. Pre-filtering by
score drops exactly the low-score, hot-signal accounts this format exists to surface. Tag
each row so a rep can see which reason put it there.

**Say what not to work.** The Traps and dead zone section is the part a rep cannot get from
their CRM, their own notes, or a competitor's tool, and it is the part that makes them trust
everything above it. Name the account that scores well and still isn't worth the call, and
name the segment you excluded so nobody re-litigates it.

**Publish the weights.** The scoring model section exists so a rep can tell you which factor
is wrong. Weights should sum to 100 and each factor should say where its number comes from.
A model nobody can inspect gets overridden by gut feel on the first disagreement.

**No silent caps.** If the brief bounds coverage anywhere, a top-N cut, a sampled pool, a
rank-offset ceiling, a dropped region, say so in Limits & method. Silent truncation reads as
full coverage, and the first rep who notices a missing account stops trusting the list.

## The data goes in the ACCOUNTS array

One object per account, rendered client-side. Keep it the single source of truth for the
board: don't also hand-write `<tr>` rows, or the two drift and the filter counts lie.

```js
{
  rank: 1,
  name: "Acme",
  meta: "US · 4,200 employees",
  seg:  "Platform",                                   // must match a filter pill
  metric: "1,482",                                    // the ranking metric, pre-formatted
  score: 92,                                          // 0-100 from the scoring model
  tier: 1,                                            // 1 top, 2 strong, 3 watch
  tags: [{ t: "New VP Data · May 2026", kind: "hot" }],
  why:  "Hiring 6 platform engineers against Kubernetes; no incumbent named.",
  url:  "https://sumble.com/orgs/acme/overview"
}
```

Filtering is instant because it is a client-side array, which is what lets these files carry
several hundred accounts and still open anywhere as a single portable `.html`. Generate one
filter pill per segment actually present in the data, by hand, so the order stays stable.

Two conventions worth holding: `tier` drives the score pill's intensity, one accent at three
strengths rather than a rainbow of colors; and `tags` carry dated signals only, because an
undated trigger is not a trigger.

## Building it cheaply

The research pass behind this format should stay cheap until accounts survive the first cut.

1. **One jobs pass over the whole list.** `FindMatchAndEnrichJobs` scoped to the list, filtered
   to the profile's key projects and technology categories, `hiring_period EQ '3mo'`. Free
   attributes only. Never request paid attributes across a whole list.
2. **One signal sweep.** `SearchSignals` filtered by `account_list_ids` or `organization_ids`.
   One call, no per-org loop. Signals cost 1 credit each returned and are free when nothing
   matches; on a large list, trim with the `priorities` filter rather than by pre-filtering
   the accounts.
3. **Pull internal context** for the accounts that survive.
4. **Spend on the top few only.** Full job descriptions, `related_people`, and contact
   reveals belong in the account cards, not the board.

Costs and the query language live in `references/mcp-tools.md`.

## The card opens on the row

Give the top three to five a `card` object and their board row becomes expandable in place.
Every other row stays a plain row.

**Do not put the cards in a section of their own.** A rep reads the ranking top to bottom,
stops at a name they recognise, and wants the detail *there*. A separate section makes them
scroll away from the board, find the account again, then scroll back to carry on, and the
ranking is the thing they came for. Keeping the detail on the row also means the filter pills
hide a card along with its account, which a separate section cannot do.

Each card is a compressed deep dive: the evidence with links, one angle in the rep's voice
that names the product, one discovery question, and one to three people with the entry point
marked and both links on every name. The same call-line rules apply as in
`references/deep-dive-brief.md`, including the ban on Sumble vocabulary in anything the rep
says out loud.

Three mechanics, all handled by the template but easy to break:

- The detail row is a `<tr class="drow">` with a `colspan` cell, rendered immediately after
  the row that owns it. `toggleRow` walks to `nextElementSibling`, so the pairing is
  positional and needs no ids.
- `COLS` in the script must match the `<thead>` column count. Add a column to the table and
  the detail cell stops spanning the full width.
- The account name calls `event.stopPropagation()`, so clicking the name still navigates to
  Sumble while a click anywhere else on the row expands it.

Offer to build a full deep dive on any of them at the close.

## Deliver

Write the `.html` and hand it back. In Claude Code or a connected folder that means to disk;
in ephemeral chat, as a downloadable file.

**Publishing it as a hosted page needs one change.** The template references the Sumble mark
as `sumble-eyes-logo-512.png` next to it, which resolves on disk but not once the page is
hosted, and a strict artifact CSP blocks remote images outright. Base64-encode
`assets/sumble-eyes-logo-512.png` into a `data:image/png;base64,` URI in both the nav and the
footer before publishing. Use the official bundled asset only: never redraw, recolor, or
substitute an inline SVG for the Sumble logo. If the asset isn't available, omit the mark and
tell the user.
