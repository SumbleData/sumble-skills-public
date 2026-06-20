# Brand styling (default for a plan / deck with no example)

Use this **only when the user supplied no example** in Step 1. With an example, match
*that* — ignore this file.

**Brand it for the seller's own company — the company using this skill (the Sumble
customer) — not for Sumble.** A deck is presented to the prospect under the seller's
name, and an account plan is the seller's internal document; both represent the
seller's company. Sumble is the research tool behind the work, not the brand on the
page. The goal is a clean, professional artifact that looks like it came from the
seller's company: their colors and logo, one accent over a neutral base, never a
rainbow.

## Get the seller's company brand (in this order)

1. **Identify the company** from `GetMyCompanyProfile` (name + domain) — you already
   have this from Step 3.
2. **Ask for a brand kit / template** if you don't have one: a deck master/template,
   brand colors (hex), logo file, or fonts. One quick ask — "Do you have a deck
   template or brand colors/logo I should match?" — saves a redesign.
3. **Derive a light brand** from their public website / logo if they have nothing
   handy: their primary brand color + their logo (linked, not redrawn).
4. **Fall back to a neutral professional design** (palette below) with the company
   **name** set prominently on the title slide / plan header — never invent a logo.

## Neutral fallback palette (only when the company's colors are unknown)

| Token | Hex | Use |
|---|---|---|
| Ink (headings + body) | `#172033` | primary text |
| Muted | `#64748b` | secondary text, captions, metadata |
| Accent (one) | `#2563eb` | a single neutral accent: headings/dividers/key stats/CTA |
| Faint | `#f1f5f9` | section / card background |
| Line | `#e2e8f0` | borders, rules, table gridlines |
| Red (sparingly) | `#dc2626` | only to flag a gap / risk / missing data |

Swap the accent for the seller's brand color the moment you know it. Type: use the
company's brand font if known, else a clean neutral sans (Inter, then system
`ui-sans-serif`); weights **Medium (500)** for labels and **Semibold (600)** for
headings — never heavy bold (700+) or light (≤300).

## Sumble attribution (optional, subtle)

Sumble appears only as a small **"Research powered by Sumble"** footer/endnote if the
seller wants it — never as the dominant brand. Default to leaving it off a
prospect-facing deck unless asked.

When you do show it, it is the **only** Sumble-branded element on the page, so it must
follow Sumble's official brand guide exactly. **If the `sumble-brand-guidelines` skill
is installed, defer to it** for the logo, color, and clear-space rules. Otherwise apply
these (from that guide):

- **Use the official bundled logo asset only:** `assets/sumble-eyes-logo-512.png`. Size
  it down proportionally from the 512px PNG; keep clear space around it.
- **Never** draw, approximate, generate, trace, rebuild, recolor, distort, rotate, crop,
  mask, shadow, or otherwise alter the Sumble logo, and never substitute a CSS/inline-SVG
  version. If the official asset isn't available, omit the mark and tell the user.
- If the footer text needs an accent, use **Green 600 `#16a34a` sparingly**; set the text
  in Slate (`#475569` / `#334155`). Do not introduce Sumble green into the rest of a
  seller-branded artifact.

## Guardrails

**Do:** use the seller's *real* colors and logo; one accent over a slate/white neutral
base; generous whitespace; hierarchy by weight and color, not boxes and color blocks;
use any logo at its native aspect ratio.

**Don't:** invent or hand-recreate the seller's (or Sumble's) logo; recolor, stretch,
rotate, or add effects to a logo; flood the page with one color or add off-palette
colors; use bold/light weights; **brand the artifact as Sumble's** when it should be
the seller's; co-brand with the prospect's logo in a way that implies a partnership.
When unsure, default to plainer and more neutral.
