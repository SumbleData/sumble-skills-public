# People scoring — Sumble's own run (example)

A real, runnable app the [`sumble-people-scoring`](../../skills/sumble-people-scoring)
skill produced, pointed at Sumble's own ICP: **everyone Head-and-above in five
GTM job functions, across a random sample of 100 of Sumble's target
accounts** — 4,218 people, met or not.

**▶ Live demo: https://people-scoring-demo.sumble.com/**

> ## ⚠️ Illustrative demo — real people, demo scoring
>
> The **people are real** — public-profile data (names, titles, LinkedIn URLs),
> the same data Sumble surfaces in its product. What's illustrative is the
> **scoring**: the lead scores, the ICP weighting, and the per-account ranking
> here are a **demonstration only** — *not* Sumble's real lead prioritization,
> and *not* a judgment of any individual. No closed-won / "gold" set was used;
> the weights are the skill's policy defaults, untuned.

```bash
python app.py
# open http://localhost:8002 — pick an account, drag sliders, click Save
```

Stock Python 3.10+, stdlib only — no `pip install`.

## What's in here

- `data.csv` — the immutable pull: identity, function, seniority, matched
  skills (from the v6 `technologies` attribute), and the account score joined
  from the [account-scoring example](../account-scoring)'s model.
- `config.json` — the scoring config the skill generated (weights, per-function
  ranges, skill cap).
- `score.csv` — regenerated on every Save and at startup (gitignored).
- `score_leads.py` — the portable scorer: applies saved weights to any
  enriched people CSV, no browser.

## What it shows

- **Met and unmet people on one scale.** The whole point of the method: the
  ranked list per account includes the people no CRM has ever heard of.
- **The buying committee.** Head through CXO across Sales, SDR, AE, RevOps and
  Marketing — the leaders a deal actually has to win.
- **Account context.** Each person inherits their account's score, so a
  director at a top account outranks the same title at a weak one.

The method is written up in
[the people-scoring article](../../skills/sumble-people-scoring/articles/01-people-scoring-use-cases.md).

## Deploy

This folder is a self-contained Cloud Run app (stdlib-only `Dockerfile`; the app
reads `$PORT` and binds `$HOST=0.0.0.0`). `score.csv` is regenerated in the
container at startup, so only `data.csv` + `config.json` need to ship. Deploy
into the same GCP project that hosts the account demo (where `sumble.com` is
verified for domain mapping):

```bash
cd sumble-skills/examples/people-scoring

# 1. Deploy the service.
gcloud run deploy sumble-people-scoring-demo \
  --source . --region us-west1 --allow-unauthenticated --memory 1Gi

# 2. Map the custom domain (one-time), then add the records gcloud prints
#    to the sumble.com DNS zone.
gcloud beta run domain-mappings create \
  --service sumble-people-scoring-demo \
  --domain people-scoring-demo.sumble.com \
  --region us-west1
```

## Security note

The local app binds 127.0.0.1 and has no auth. `data.csv` is real
public-profile data (names, titles, LinkedIn URLs) for people at real
companies — treat the folder accordingly. The deployed demo is intentionally
public (`--allow-unauthenticated`); the in-app banner marks the scoring as
illustrative.
