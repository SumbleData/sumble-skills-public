"""Stage 2 — fetch all calibration data from `POST /v6/organizations`.

Replaces the old SQL-generation + per-query MCP run. ONE endpoint, no SQL.

Modes:
  list   (default, Branch A) — resolve + enrich the CRM calibration sample in
         `_raw/sample.csv` (columns: crm_account_id, name, domain[, is_gold]).
         The endpoint matches by name/url AND enriches in the same call.
  filter (Branch B, no CRM)  — rank Sumble's universe by an ICP advanced query
         (paginated), enriching each candidate with the same `select`.

Writes:
  _raw/responses/resp_*.json   raw endpoint responses (one per batch/page)
  _raw/fetch_index.json        per-org {crm_account_id, crm_account_name,
                               crm_url, is_gold} aligned to the flattened
                               response order (list mode; empty in filter mode)

Auth: SUMBLE_API_KEY from the environment, or --env-file (e.g. notebooks/.env).

Usage:
  python fetch_data.py --raw _raw                       # list mode
  python fetch_data.py --raw _raw --mode filter --pool 1000
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
PAGE = 200  # filter mode: endpoint max limit per page


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


def run_list(raw: Path, select: dict, api_key: str) -> None:
    sample_path = raw / "sample.csv"
    if not sample_path.exists():
        sys.exit("_raw/sample.csv missing — write the CRM calibration sample first.")
    with sample_path.open(newline="") as f:
        sample = list(csv.DictReader(f))
    if not sample:
        sys.exit("_raw/sample.csv is empty.")

    resp_dir = raw / "responses"
    resp_dir.mkdir(exist_ok=True)
    for old in resp_dir.glob("resp_*.json"):
        old.unlink()

    index: list[dict] = []
    matched_total = 0
    for bi in range(0, len(sample), BATCH):
        chunk = sample[bi : bi + BATCH]
        orgs = [
            {"name": r.get("name") or "", "url": r.get("domain") or r.get("url") or ""}
            for r in chunk
        ]
        body = {"organizations": orgs, "select": select}
        resp = post(api_key, body)
        (resp_dir / f"resp_{bi // BATCH:03d}.json").write_text(json.dumps(resp))
        matched_total += resp.get("matched_count") or 0
        for r in chunk:
            index.append(
                {
                    "crm_account_id": r.get("crm_account_id") or "",
                    "crm_account_name": r.get("name") or "",
                    "crm_url": r.get("domain") or r.get("url") or "",
                    "is_gold": int(str(r.get("is_gold") or "0") in ("1", "true", "True")),
                }
            )
        print(
            f"[fetch] batch {bi // BATCH + 1}: {len(chunk)} sent, "
            f"matched={resp.get('matched_count')} credits={resp.get('credits_used')}"
        )
    (raw / "fetch_index.json").write_text(json.dumps(index))
    print(f"[fetch] done: {len(sample)} orgs, {matched_total} matched.")


def run_filter(raw: Path, spec: dict, select: dict, api_key: str, pool: int) -> None:
    """Rank Sumble's universe by an ICP advanced query, enriching each page."""
    techs = [t["slug"] for t in spec["techs"]]
    projects = [p["slug"] for p in spec.get("projects") or []]
    terms = [f"technology EQ {sumble_v6._q(s)}" for s in techs]
    terms += [f"project EQ {sumble_v6._q(s)}" for s in projects]
    query = "(" + " OR ".join(terms) + ")" if terms else "employee_count GTE 1"
    order_col = spec.get("universe_filters", {}).get("order_by_column", "employee_count")

    resp_dir = raw / "responses"
    resp_dir.mkdir(exist_ok=True)
    for old in resp_dir.glob("resp_*.json"):
        old.unlink()

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
        print(f"[fetch] page {page}: {len(orgs)} orgs (total {fetched}/{pool})")
        if len(orgs) < body["limit"]:
            break
    (raw / "fetch_index.json").write_text(json.dumps([]))
    print(f"[fetch] done: {fetched} candidates over {page} pages.")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Fetch calibration data via /v6/organizations."
    )
    ap.add_argument("--raw", default="../_raw")
    ap.add_argument("--mode", choices=["list", "filter"], default="list")
    ap.add_argument(
        "--pool", type=int, default=1000, help="filter mode: candidates to rank"
    )
    ap.add_argument("--env-file", default=None, help="read SUMBLE_API_KEY from this file")
    args = ap.parse_args()

    raw = Path(args.raw).resolve()
    spec = json.loads((raw / "spec.json").read_text())
    select = sumble_v6.build_select(spec)
    api_key = load_api_key(args.env_file)

    if args.mode == "list":
        run_list(raw, select, api_key)
    else:
        run_filter(raw, spec, select, api_key, args.pool)


if __name__ == "__main__":
    main()
