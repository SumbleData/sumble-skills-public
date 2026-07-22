# sumble-territory-planning

Companion skill to [`sumble-account-scoring`](../sumble-account-scoring).
Scoring answers *which accounts are strong*; this answers **are the right reps
on them, and are the books fair**.

Builds a territory-review web app from a CRM ownership list, an account-strength
score, and per-rep×account activity (calendar, call recorders, CRM email). Emits
an `actions.csv` of approved owner changes.

- Workflow: `SKILL.md` (interview → fetch → calibrate → merge → suggest → app)
- Pipeline internals, schemas, and policy constants: `template/_build/README.md`
- Account strength: an existing account-scoring `score.csv` (preferred — tuned
  to the user's own ICP), else Sumble's `sumble_score` via
  `POST https://api.sumble.com/v6/organizations`
- Output app: zero-dependency stdlib Python + vanilla HTML/JS, modeled on
  `sumble-account-scoring`

## What it surfaces

| Highlight | Meaning |
|---|---|
| Not being worked | Owned, but zero meetings / calls / outbound email from the owner in the window |
| Strong but idle | Top-quartile score **for its segment**, and nobody is working it |
| Wrong segment | The account's size belongs to one segment; its owner sells another |
| Unallocated | No active rep owns it — nobody, a queue, or someone who has left |
| Double-allocated | Two reps own CRM records resolving to the **same Sumble org** |

Balance is the coefficient of variation of **total account score** per rep, not
account count — a rep with 40 weak accounts does not have a bigger book than one
with 15 strong ones.

## The constraint that shapes everything

**An account with activity is never proposed for a move.** A rep who has met,
called, or emailed a prospect has context the balance maths cannot see. The
planner takes the free wins first (misfits, unallocated, whitespace) and only
then moves already-owned, untouched accounts to even out the books.
