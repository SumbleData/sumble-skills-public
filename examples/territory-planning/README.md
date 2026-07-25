# Territory Planning — demo

A public, self-contained demo of the [`sumble-territory-planning`](../../skills/sumble-territory-planning)
skill's app: per-segment **book-strength heatmaps** (Capture / Activation, each
with the rep's **top 25** by average in-segment rank), a live **Calibrate**
sidebar (segment boundary, per-rep capacity, strong-account cutoff), a
granular **Accounts** tab where you assign any account to anyone, and a
suggest → accept/reject → **Export** flow.

Runs on any stock Python 3.10+ — **no pip install, no dependencies.**

```bash
cd examples/territory-planning
python3 app.py          # http://localhost:8002
```

## The data is fictitious

- **Company, reps, and activity are invented.** A made-up vendor (*Northwind*)
  with **10 Enterprise + 10 Commercial** reps (fictitious names) and synthetic
  calendar activity. Nothing here reflects a real sales team or book.
- **Account names are real public companies** (from the
  [`account-scoring`](../account-scoring) demo)
  with **synthetic demo scores** — that dataset is already public in this repo.
- **Deterministic:** everything is hash-seeded (no RNG), so the demo rebuilds
  byte-identically.
- **Books are sized to target.** Every rep is dealt a fixed quota, so all 20
  books land within **±40%** of their segment's target (Enterprise 50, so
  30–70; Commercial 150, so 90–210). `make_demo.py` fails the build if one
  drifts outside that band — otherwise "Target accounts per rep" in the
  Calibrate panel would be describing something the data doesn't do.

The seeded numbers tell a story on purpose: one enterprise rep (*Chen Wei*)
holds the segment's biggest book and a third of its best accounts but works
almost none of them (**33% Capture, 6% Activation** — sitting on value); the
foil (*Dev Ramesh*) works their top tier to **100%**; one ramping rep
(*Grace Okafor*) sits at **0%**; and the commercial star (*Alex Rivera*) both
captures and activates the most in that segment. So the heatmaps, the
Capture/Activation columns, the attention flags, and the Calibrate/Moves flows
all have something to show.

## Rebuild from source

The committed app + data are produced by `build.sh` — copy the stdlib app from
the skill template, generate the fictitious inputs, run the real pipeline, and
inject the demo banner:

```bash
bash examples/territory-planning/build.sh
```

`make_demo.py` is the generator (accounts + scores + reps + ownership +
activity); tweak `ENTERPRISE_REPS` / `COMMERCIAL_REPS`, `ENTERPRISE_MIN` (the
segment line), `SEGMENT_CAPACITY`, or the `ENT_QUOTA` / `COM_QUOTA` book sizes
there to reshape the demo. Change a quota and the ±40% guardrail will tell you
if it no longer fits its segment target.
