"""Stage 2 — fetch the whitespace pool + calibration data from one endpoint.

Replaces the candidate-ranking SQL + per-query MCP runs. ONE endpoint, no SQL:
`POST https://api.sumble.com/v6/organizations` (match + enrich + select).

Does up to three things from `_raw/`, based on which inputs exist:
  1. Candidate pool — `filter` mode ranks Sumble's universe by an ICP advanced
     query, enriching each page → `responses/resp_*.json`.
  2. CRM list (`crm.csv`: name,domain) — `list` mode resolves to org ids (for
     exclusion / subsidiary parent lookup) → `crm_matches.json`.
  3. Customer list (`customers.csv`: name,domain[,crm_account_id]) — `list`
     mode enriches the closed-won set for calibration → `customer_responses/`.

Auth: SUMBLE_API_KEY from env or --env-file (e.g. notebooks/.env).

Usage:
  python fetch_data.py --raw _raw --pool 1000
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import sumble_v6

# list mode: the endpoint accepts up to 1000 orgs/call, but a rich ICP (many
# techs/personas → 50+ entity selections per org) makes a 1000-org payload heavy
# enough to 500. 250 keeps payloads safe; credits are unchanged (cost is per org).
BATCH = 250
PAGE = 200


def load_api_key(env_file: str | None) -> str:
    key = sumble_v6.resolve_api_key(env_file, allow_prompt=sys.stdin.isatty())
    if not key:
        sys.exit(
            "No Sumble API key found. Run `python set_api_key.py` (prompts for the "
            "key and saves it), or `export SUMBLE_API_KEY=...`, or pass "
            "--env-file path/to/.env, then re-run."
        )
    return key


def post(api_key: str, body: dict, *, retries: int = 4) -> dict:
    data = json.dumps(body).encode("utf-8")
    for attempt in range(retries):
        req = urllib.request.Request(sumble_v6.API_URL, data=data, method="POST")
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2**attempt)
                continue
            sys.exit(f"[fetch] HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:400]}")
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries - 1:
                time.sleep(2**attempt)
                continue
            sys.exit(f"[fetch] network error: {e}")
    raise SystemExit("[fetch] exhausted retries")


def _clear(resp_dir: Path) -> None:
    resp_dir.mkdir(exist_ok=True)
    for old in resp_dir.glob("resp_*.json"):
        old.unlink()


def fetch_candidates(raw: Path, spec: dict, select: dict, api_key: str, pool: int) -> None:
    techs = [t["slug"] for t in spec["techs"]]
    projects = [p["slug"] for p in spec.get("projects") or []]
    terms = [f"technology EQ {sumble_v6._q(s)}" for s in techs]
    terms += [f"project EQ {sumble_v6._q(s)}" for s in projects]
    query = "(" + " OR ".join(terms) + ")" if terms else "employee_count GTE 1"
    order_col = spec.get("universe_filters", {}).get("order_by_column", "employee_count")

    resp_dir = raw / "responses"
    _clear(resp_dir)
    fetched = 0
    page = 0
    while fetched < pool:
        body = {
            "filter": {"query": query},
            "select": select,
            "order_by_column": order_col,
            "order_by_direction": "DESC",
            "limit": min(PAGE, pool - fetched),
            "offset": fetched,
        }
        resp = post(api_key, body)
        orgs = resp.get("organizations") or []
        if not orgs:
            break
        (resp_dir / f"resp_{page:03d}.json").write_text(json.dumps(resp))
        fetched += len(orgs)
        page += 1
        print(f"[fetch] candidates page {page}: {len(orgs)} (total {fetched}/{pool})")
        if len(orgs) < body["limit"]:
            break
    print(f"[fetch] candidates done: {fetched} over {page} pages.")


def _read_rows(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def resolve_crm(raw: Path, api_key: str) -> None:
    path = raw / "crm.csv"
    if not path.exists():
        print("[fetch] no crm.csv — skipping CRM resolution.")
        return
    rows = _read_rows(path)
    matches: list[dict] = []
    select = {"attributes": ["id", "name"], "entities": []}
    for bi in range(0, len(rows), BATCH):
        chunk = rows[bi : bi + BATCH]
        orgs = [
            {"name": r.get("name") or "", "url": r.get("domain") or r.get("url") or ""}
            for r in chunk
        ]
        resp = post(api_key, {"organizations": orgs, "select": select})
        for ro in resp.get("organizations") or []:
            attrs = ro.get("attributes") or {}
            if attrs.get("id"):
                matches.append({"org_id": attrs["id"], "name": attrs.get("name") or ""})
        print(f"[fetch] CRM batch {bi // BATCH + 1}: matched={resp.get('matched_count')}")
    (raw / "crm_matches.json").write_text(json.dumps(matches))
    print(f"[fetch] CRM resolved: {len(matches)} org ids.")


def enrich_customers(raw: Path, select: dict, api_key: str) -> None:
    path = raw / "customers.csv"
    if not path.exists():
        print("[fetch] no customers.csv — skipping customer calibration fetch.")
        return
    rows = _read_rows(path)
    resp_dir = raw / "customer_responses"
    _clear(resp_dir)
    for bi in range(0, len(rows), BATCH):
        chunk = rows[bi : bi + BATCH]
        orgs = [
            {"name": r.get("name") or "", "url": r.get("domain") or r.get("url") or ""}
            for r in chunk
        ]
        resp = post(api_key, {"organizations": orgs, "select": select})
        (resp_dir / f"resp_{bi // BATCH:03d}.json").write_text(json.dumps(resp))
        mc = resp.get("matched_count")
        print(f"[fetch] customers batch {bi // BATCH + 1}: matched {mc}")
    print(f"[fetch] customers enriched: {len(rows)} rows.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch whitespace data via /v6/organizations.")
    ap.add_argument("--raw", default="../_raw")
    ap.add_argument("--pool", type=int, default=None, help="candidates to rank")
    ap.add_argument("--env-file", default=None)
    args = ap.parse_args()

    raw = Path(args.raw).resolve()
    spec = json.loads((raw / "spec.json").read_text())
    select = sumble_v6.build_select(spec)
    api_key = load_api_key(args.env_file)
    pool = args.pool or int(spec.get("pool_size", 1000))

    fetch_candidates(raw, spec, select, api_key, pool)
    resolve_crm(raw, api_key)
    enrich_customers(raw, select, api_key)


if __name__ == "__main__":
    main()
