# Direct-mail audience builder

This local Marimo app finds people in selected job functions and seniority bands who
live within a chosen distance of a company office.

It uses the public Sumble API to resolve companies, load their structured headquarters
addresses, and find people. Parallel Search finds additional offices in its Basic mode, then
Parallel Extract reads complete official location lists. The app geocodes US offices with the
public US Census Geocoder and uses OpenStreetMap Nominatim as a fallback. It calculates distance
and creates downloadable CSV files on your machine.

## Start the app

Install [uv](https://docs.astral.sh/uv/) if it is not already installed. Then run:

```bash
uv sync --locked
uv run python -m direct_mail.configure_env
uv run marimo run app.py --host 127.0.0.1 --port 2718
```

Open [http://127.0.0.1:2718](http://127.0.0.1:2718).

`uv` creates a project-local `.venv` and installs the Python and package versions in
`uv.lock`. It does not change a global Python, Marimo, or another repository's packages.

## Workflow

The app runs in four user-controlled stages:

1. Resolve company domains and headquarters addresses through `POST /v9/organizations`.
2. Review the Sumble headquarters, upload known offices, and optionally use Parallel Search
   and Extract to find additional locations.
3. Select Sumble job functions and job levels, review the generated query, and run
   `POST /v9/people`.
4. Geocode people, calculate the nearest office, apply the radius, and rank the audience.

Each stage has its own submit button, progress indicator, result table, and error output.
The app does not start a later stage until the user starts it.

## Inputs

Company domains can be pasted into the app or uploaded in a CSV:

```csv
domain
mongodb.com
```

The office CSV needs `company_domain` and `city`. These columns are also supported:

```csv
company_domain,company_name,office_name,street,city,state_region,postal_code,country_code,latitude,longitude,source_url
```

Uploaded offices take precedence over Sumble and Parallel when the same address appears more
than once. Sumble's structured headquarters address takes precedence over a matching Parallel
result.

The app treats researched addresses as evidence, not facts:

- A Sumble result with a different domain brand is rejected. Known aliases such as
  `notion.com` and `notion.so` still match.
- An address from another website must mention the exact company domain and identify the text
  as a headquarters or physical office address. A company name alone is not enough.
- Mailboxes, registered-agent addresses, virtual offices, and mail drops are rejected.
- Geocoding must return the requested street number, street name, city, and state. A road or
  city-center result does not count as a successful geocode. The office export records the
  provider and matched address in `geocode_source` and `geocode_match`.

Every researched office also receives a validation status:

- `verified` means an official operational page supports it, or at least two independent
  sources agree and one is an official, LinkedIn, commercial-property, or business-data source
  that the app treats as strong evidence.
- `review_required` means the only evidence is one third-party source, an official legal page,
  a non-location company page, or stale dated material.
- `rejected` means the address failed exact street-level geocoding or the evidence described a
  mailbox, registered office, coworking space, former location, or closed office.

Only `verified` offices feed the audience match. Review and rejected rows remain visible and
downloadable. The export includes the supporting excerpt, URLs, source publication date when
Parallel provides one, a machine-readable `evidence_json` record, and `checked_at`. The check
date is not presented as the date when a company moved into the office.

## Downloads

The final screen provides two browser downloads:

- `audience_results.csv` has company and person details, the nearest office, distance,
  and the reason the row matched.
- `offices.csv` has uploaded and researched offices, coordinates, evidence URLs,
  confidence, and verification dates.

The exports omit Sumble organization and person IDs. The app never requests email or
phone contact data.

## Local files

The app stores geocoding results in `.cache/geocodes.sqlite3` so repeated runs do not
geocode the same location again. `.env`, `.env.local`, `.cache`, and `outputs` are
gitignored.

## Development

```bash
uv run pytest
uv run ruff check .
uv run marimo check app.py
```

The key helper accepts both keys without echoing them and writes `.env` with mode `0600`.
It never sends the keys to the agent or stores them in chat.
