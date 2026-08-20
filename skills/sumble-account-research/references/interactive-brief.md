# Building the interactive HTML brief (Step 5d)

A single self-contained `.html` — a clickable page where each **signal** expands into the
play, the call, what to test, who to reach, and their reporting line. Template:
`assets/intelligence-brief-template.html` (fan-out JS + styling baked in; you fill the
`{{TOKENS}}` and duplicate the repeating blocks). Opens anywhere — no build step, no
embedded fonts. Build from the Step 5 research you already ran; no new queries. One
signal → one card → one play. **Hold every line to `references/writing-rules.md`.**

**Sumble-branded by design** — an internal research artifact ("Sumble Intelligence"), not
prospect-facing, so it skips `references/branding.md`. The template already carries the
brand: one emerald accent (`#16a34a`) on slate/white, the official Sumble mark, Inter.
Don't recolor it to the prospect or the seller.

**The logo is base64-embedded — keep it that way.** The template carries the bundled
`assets/sumble-eyes-logo-512.png` inline as a data URI in both the nav and the footer, so a
delivered brief renders on a plane and still renders after someone forwards it. Never swap it
for a hotlinked URL, never redraw it in SVG/CSS, and never point it at a different mark.
**Before you ship, grep the finished file for `src="http`** — it must return nothing. The one
external request the template makes by design is the Google Fonts `<link>` for Inter and
JetBrains Mono; those degrade to system fonts offline, whereas a hotlinked logo just breaks.

**Brand-font upgrade (Sumble-internal runs only).** The public template ships **Inter**
because the NEXT brand faces (NextPoster/NextBook) are proprietary and this repo is public —
never commit the NEXT font files here. But if you're running inside Sumble and the NEXT
woff2 files are available locally (from a Sumble brand-assets source you already have
installed), embed them into the **output** `.html` for a full brand match: base64-encode
each woff2, add two `@font-face` blocks, and point the vars at them —

```css
@font-face{font-family:'NextPoster';src:url(data:font/woff2;base64,<POSTER_B64>) format('woff2');font-weight:300 800;font-display:swap}
@font-face{font-family:'NextBook';src:url(data:font/woff2;base64,<BOOK_B64>) format('woff2');font-weight:300 800;font-display:swap}
:root{--font-display:'NextPoster','Inter',system-ui,sans-serif;--font-body:'NextBook','Inter',system-ui,sans-serif;}
```

The fonts live in the delivered file only, never in the repo. No fonts handy → leave the
template on Inter; it still renders clean.

## Map the plays to pills + badges

The pills and badges are the user's **sales plays** — already settled in the Step 3
profile (and the play(s) you're chasing for this account). Don't re-pick them here; just
map them onto the template:

- the **filter pills** (`data-filter` = a slug of the play name; keep `All plays`),
- each signal's **badge** and **`data-play`** (must match a pill's slug).

If the profile has no distinct named plays, keep only the `All plays` pill and drop the
badges — the cards still work; they just aren't play-filtered.

## Fill the shell

| Token | What goes in |
|---|---|
| `{{ACCOUNT}}` | Company name (nav, hero pill, footer, sources). |
| `{{MONTH_YEAR}}` | e.g. `June 2026`. |
| `{{RECIPIENT}}` | Who it's for (the rep / their manager), or omit. |
| `{{CONTEXT}}` | Short framing, e.g. `Account brief` or `Expansion`. |
| `{{HEADLINE}}` | The one-line "so what" for the whole account — a consequence, not a topic. |
| `{{ACCOUNT_NARRATIVE}}` | 2–4 sentences on the situation + why now. NOT a recap of the signals. |
| `{{SUMBLE_ORG_URL}}` | `sumble.com/orgs/<slug>/overview`. |
| `{{AUTHOR}}` / `{{AUTHOR_EMAIL}}` | The seller, or omit. |

## Fill each signal card (duplicate `.signal-card` per signal)

Order strongest-first; each card maps one Step 5b signal to one play.

- **`sig-num`** — `01`, `02`, … in order.
- **`sig-title`** — the "so what" in one line (the consequence, not the artifact).
- **`sig-sub`** — `team · one-line evidence` (mono, truncates — keep it short).
- **`sig-badge`** + **`data-play`** — the play (slug must match the pill).
- **Signal box** (`.trigger-text`) — the evidence; lead with the confirmed tech or hiring
  signal, hyperlink the org + the single strongest job posting to Sumble.
- **Stack** (`.stack-tags`) — `um-strong` = tech confirmed in their profile; `um-weak` =
  competitor / displacement tech, or postings-only (not confirmed adopted). Append counts
  (`Splunk 42/81`) only from a real `RunSqlQuery` pass — never invent them.
- **The call** (`.call-line`) — **one quoted sentence in the seller's voice**: what the
  rep *says to the prospect*, and it **names the product**. The rep is selling, not running a
  neutral discovery script; a card that never says what they sell hands them evidence with no
  bridge to a deal. Three rules:
  - **Open on their situation, land on the product.** Their evidence earns the sentence; the
    product is the answer to it, not the greeting. "You're running Splunk at real scale, and
    paying for every gigabyte you index — that's what our tiered storage is for" works;
    "Have you considered our tiered storage?" does not. Same sentence, different order,
    completely different call.
  - **Name the specific product or module, not the company.** Add a **reference customer with a
    concrete outcome** as a trailing `.proof` span when you have one (pull them from
    `GetMyCompanyProfile` → `company_reference_customers`); it belongs to the rep, so keep it to
    one clause.
  - **The product must match the card's `sig-badge` play**, or the badge is decoration and the
    play mapping is wrong — fix one or the other.

  **Never Sumble vocabulary** — no "used/mentioned", "N postings", "Sumble sees", no raw counts.
  The prospect has never heard of Sumble. Translate the evidence into seller language ("you're
  running Splunk at real scale"); counts stay in the Signal box and Stack.
- **What to test** (`.detail-col p`) — the discovery question as the rep's curiosity
  ("how's the Splunk renewal going?"), not a metric, and **not a second pitch** — the call
  already named the product, so this block goes back to listening. Bold the key qualifier.
  Natural sentences, no "**Label:** sentence" bullets.
- **Sources** — `Sumble · {{ACCOUNT}} profile` link plus any web sources.

## Buying group + the reporting fan-out

The **buying group is defined in SKILL.md Step 5c** — the contacts, the scored reporting
lines (`related_people` + `confidence` → 1–10), both links per person, the path in, and the
"every person accounted for" rule. This section is just its **HTML rendering** (`.buygroup`
header, role chips, `.fan` blocks, `.plinks`); don't re-derive the data rules here — Step 5c
is the source of truth, and the same group feeds the deck, call-prep, and outreach
deliverables too.

**Freshness gate first (SKILL.md Step 5c).** Only include people *currently at the
company*. Verify each name (web / current LinkedIn role) before it goes on a card.
Departed → drop (don't list, don't anchor a fan-out, don't reveal). Active but with a
stale Sumble record (wrong title / mislabeled / 0 reports) → keep, but show the
**verified current title** (not the Sumble one) and note the record is stale. Same for
fan-out reports: a departed report comes off the line.

Every card ends in a **labelled buying group**: the team that owns the signal, the path to
the buyer, the role-tagged people, then each person's scored reporting line. Don't leave the
people as a bare list.

**1 · Team header (`.buygroup`).** Anchor the card on a **real, navigable Sumble team** —
never a noisy auto-cluster ("Manager", "AVP", a generic "Security"). The clean source is the
team that recurs across your contacts' `FindMatchAndEnrichPeople` `confidence.matched_features`
with `match_type:"team"` — it carries the team `name` **and `slug`**. Roster link is slug-form,
not numeric ids: `https://sumble.com/orgs/<org-slug>/teams/<team-slug>/people`, text **"See
who's on this team →"** (Sumble's inferred, confidence-scored membership, not a confirmed
roster). **No curated team** — some orgs surface only the generic org-level cluster (its slug
is just the org name, e.g. `nfl`); don't anchor on that. Name the group by the function you're
selling into and point the roster at `https://sumble.com/orgs/<org-slug>/people` with text
**"See who Sumble links to this org →"**, noting it in `.bg-path`.

**2 · Path in (`.bg-path`).** One line naming the entry point and the buyer above it:
`{{champion}} (champion) → {{economic buyer}} (economic buyer)`. Don't render an empty "above"
fan for a senior contact whose inferred manager is missing — just name the path here.

**3 · Contacts (`.contact-row`), each with a role chip + both links.** The 2–3 Step 5c people
— avatar initials, name with **LinkedIn + Sumble** links (`.plinks`), title, `location ·
why-this-person` (the play's persona) — plus a **`.contact-role` chip**: `Economic buyer` /
`Champion` (green) or `Multithread` (`class="contact-role multi"`, slate). The role is a
visible label, not buried in the prose.

**4 · Reporting fan-out (`.fan`)** — a `.fan` block per contact: their **direct reports** (who
rolls up to them, `▼`), each row carrying the **real Sumble 1–10 confidence** and its own
LinkedIn + Sumble links.

**Every listed contact gets a block — no silent omissions.** For each contact on the card,
render **either** their own `.fan` (their reporting line) **or** a `.fan-none` note that says
why there isn't one — *no reports mapped in Sumble*, *shown as a report under {anchor} above
({score})*, or *reporting line already shown on the {other} card*. Never list a contact and
leave their line out: if you didn't pull it (you batched only some anchors, or they're a VP
with no mapped reports), say so and point the rep to reach directly. **Self-check before
delivering: per card, the count of `.contact-row` blocks must equal the count of
`.fan` + `.fan-none` blocks.** Don't repeat an identical fan across cards — cross-reference it
("line shown on card N") instead.

**One call gets the scores + both links.** `FindMatchAndEnrichPeople` in **match mode**,
batching all a card's contacts by `person_id`/`linkedin_url`, with the reporting line and
its confidence requested *inside* `related_people` (the inner `attributes` is what returns
names/titles/links/scores — omit it and you get bare ids with no score):

```
attributes: ["name","job_title","job_level","linkedin_url"]
related_people: { direction: ["direct_reports"],
                  attributes: ["name","job_title","job_level","linkedin_url","confidence"] }
```

1. **Sumble link** = each person's free `sumble_url` (`https://sumble.com/l/person/…`),
   returned on the contact **and** every related person. Put it next to the LinkedIn link on
   every row — anchor contacts and fan rows alike. That Sumble page is where the user sees
   the full confidence-scored roll-up.
2. **Score** (`.fan-rank`) = each related person's `confidence.score` (a 0–1 float at the
   **top level** of the report object, *not* under `attributes`). Convert to the web app's
   1–10 exactly: `ceil(score*100)/10` (`0.3865 → 3.9`, `0.51 → 5.1`). These are the same
   numbers on the person's Sumble page. Rank each contact's `direct_reports` by score, show
   the **top ~5**.
3. **Direction.** Use `direct_reports` (`▼`). The `managers` (up) direction is near-empty
   for senior contacts (a CXO/SVP rarely has an inferred manager) — don't render an empty
   `▲` fan; express the path-to-buyer in prose instead.
4. **Noisy / off-target line → don't show a misleading fan.** Common for CXOs (e.g. a CISO
   whose top "reports" are physical-security or strategy people, or a CDAO whose Sumble
   record is stale with 0 reports). Render a `.fan-none` note ("reach them through the
   champion") instead of padding. Never invent reports.
5. The response is large and usually spills to a file — read it back with `jq`
   (`.people[].related_people.direct_reports | sort_by(-.confidence.score)`), not inline.

Apply this to **every** recommended contact — the economic buyer and the champion both get
the dual links and their scored reporting line, exactly as on the Sumble people page.

**Load-bearing honesty:** the fan-out is an *inferred* map from shared signals (tech,
function, team, title, location) — the same figure shown on each person's Sumble page — a
suggested map, **not** a confirmed org chart, and the score is confidence-the-person-sits-in-
that-line, **not** confidence-the-play-lands. Keep the `.orgtree-note` disclaimer.

## Deliver

Write the `.html` and hand it back (Claude Code / connected folder → disk; ephemeral chat
→ downloadable file). Reveal email/phone for top contacts only if the user wants to act
(Step 5e) — the brief stands on its own without reveals.
