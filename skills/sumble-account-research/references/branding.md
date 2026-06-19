# Sumble brand styling (default for a plan / deck with no example)

Use this **only when the user supplied no example** in Step 1. With an example, match
*that* — ignore this file. The goal is something that reads as Sumble's own: a
single emerald accent on a clean neutral page, never a rainbow.

**Palette** (use these exact hex values):

| Token | Hex | Use |
|---|---|---|
| Green (primary accent) | `#16a34a` | one accent: headings/dividers/key stats/CTA, the brand dot |
| Green dark | `#15803d` | accent hover / a second emphasis only if needed |
| Green soft | `#ecfdf3` | light fill for a callout or "good fit" badge |
| Ink (body text) | `#172033` | headings + body copy |
| Muted | `#64748b` | secondary text, captions, metadata |
| Faint | `#f1f5f9` | section / card background |
| Line | `#e2e8f0` | borders, rules, table gridlines |
| Red (sparingly) | `#dc2626` | only to flag a gap / risk / missing data |

**Type.** Sumble's brand faces are **NEXT Poster Medium** (headings) and **NEXT Book
Medium** (body) — proprietary, so don't try to embed them in a Google Doc/Slides/PDF
you generate. Substitute a clean neutral sans (Inter, then system `ui-sans-serif`).
Weights: **Medium (500)** for UI/labels, **Semibold (600)** for headings; **never**
heavy bold (700+) or light (≤300).

**Logo / wordmark.** This skill ships the assets — use the packaged files, don't
redraw:
- Wordmark: `assets/sumble-wordmark.svg` (fallback: `https://sumble.com/img/sumble-wordmark.svg`)
- Mascot ("Sumblemander"): `assets/sumblemander.svg` (fallback: `https://sumble.com/img/sumblemander.svg`)

Place the wordmark on the title and closing slide / plan header; keep clear space
around it; use the mascot only as a small, optional accent.

**Guardrails — do:** green as a *single* accent over a slate/white neutral base;
generous whitespace; hierarchy by weight and color, not boxes and color blocks; use
the packaged wordmark at its native aspect ratio.

**Guardrails — don't:** recolor, stretch, rotate, add effects to, or hand-recreate
the logo/wordmark; invent a new Sumble logo or tagline; flood the page with green or
add off-palette colors; use bold/light weights; imply a partnership or co-brand with
the prospect's logo. When unsure, default to plainer and more neutral.
