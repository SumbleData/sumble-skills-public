# Territory Planning — demo

A public, self-contained demo of the [`sumble-territory-planning`](../../skills/sumble-territory-planning)
skill's app: per-segment **book-strength heatmaps** (Capture / Activation +
top 10/25/50/100/200 depth by average in-segment rank), a live **Calibrate**
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

The seeded numbers tell a story on purpose: one enterprise rep (*Chen Wei*)
holds a big book at **0% activation** (sitting on value), another (*Dev Ramesh*)
works his whole top tier, and the commercial star (*Alex Rivera*) captures and
activates the most — so the heatmaps, the Capture/Activation columns, the
attention flags, and the Calibrate/Moves flows all have something to show.

## Rebuild from source

The committed app + data are produced by `build.sh` — copy the stdlib app from
the skill template, generate the fictitious inputs, run the real pipeline, and
inject the demo banner:

```bash
bash examples/territory-planning/build.sh
```

`make_demo.py` is the generator (accounts + scores + reps + ownership +
activity); tweak `ENTERPRISE_REPS` / `COMMERCIAL_REPS`, the boundary, or the
`*_weight` tables there to reshape the demo.

## Deploy

The demo ships a `Dockerfile` and reads `$PORT` / `$HOST`, and gates itself with
HTTP Basic Auth when `BASIC_AUTH_PASS` is set — so it deploys anywhere.

**fly.io** (via the internal `fly-deploy` skill), or **Google Cloud Run**:

```bash
gcloud run deploy sumble-territory-demo \
  --source examples/territory-planning \
  --region us-central1 --allow-unauthenticated --port 8080 \
  --set-env-vars BASIC_AUTH_USER=demo,BASIC_AUTH_PASS=demo \
  --project <your-gcp-project>
```

> The container filesystem is ephemeral — allocations/calibrations made on the
> live demo reset when the instance recycles (which is fine for a demo: every
> viewer gets a clean slate). Export `actions.csv` to keep a session's changes.
