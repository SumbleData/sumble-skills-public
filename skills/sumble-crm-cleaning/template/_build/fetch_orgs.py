"""Stage 2 — resolve the CRM account list via `POST /v6/organizations`.

ONE endpoint, no SQL. Two phases:

  1. Match + enrich every row of `_raw/accounts.csv` (columns: crm_account_id,
     name, domain[, parent_crm_id][, owner][, is_customer][, created_date]).
     Attributes only (CLEANING_ATTRIBUTES — id/slug/name/url/sumble_url free,
     ~4 paid attrs), no entity selections, so cost ≈ 5 credits per matched org.
  2. Walk the org hierarchy upward: collect `parent_id`s of matched orgs that
     are NOT themselves matched CRM orgs and resolve them by Sumble id (direct
     identification, no matching). Repeat up to MAX_PARENT_HOPS levels so the
     analyzer can detect a CRM account whose ultimate parent is another CRM
     account even when intermediate holding orgs are absent from the CRM.

Writes:
  _raw/responses/resp_*.json   raw endpoint responses (one per batch)
  _raw/fetch_index.json        per-input-row CRM fields aligned to the
                               flattened response order
  _raw/parent_orgs.json        {org_id: {id, slug, name, url, sumble_url,
                               employee_count_int, headquarters_country,
                               parent_id}} for every non-CRM ancestor resolved

Auth: SUMBLE_API_KEY from the environment, a saved key file, or --env-file.

Usage:
  python3 fetch_orgs.py --raw <output_root>/_raw
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import sumble_v6

# The endpoint accepts up to 1000 orgs/call; 250 keeps payloads comfortably
# small (credits are unchanged — cost is per matched org, not per call).
BATCH = 250

# How many hierarchy levels to resolve above the CRM's own orgs. 3 covers
# brand → division → holding-company chains without runaway lookups.
MAX_PARENT_HOPS = 3


def _clear_responses(raw: Path) -> Path:
    resp_dir = raw / "responses"
    resp_dir.mkdir(exist_ok=True)
    for old in resp_dir.glob("resp_*.json"):
        old.unlink()
    return resp_dir


def match_accounts(
    rows: list[dict], api_key: str, resp_dir: Path
) -> tuple[list[dict], dict[int, dict]]:
    """Phase 1: match + enrich the CRM list. Returns (fetch_index, org_attrs)."""
    select = {"attributes": sumble_v6.CLEANING_ATTRIBUTES, "entities": []}
    index: list[dict] = []
    org_attrs: dict[int, dict] = {}
    matched_total = 0
    for bi in range(0, len(rows), BATCH):
        chunk = rows[bi : bi + BATCH]
        orgs = [
            {"name": r.get("name") or "", "url": r.get("domain") or r.get("url") or ""}
            for r in chunk
        ]
        body = {"organizations": orgs, "select": select}
        resp = sumble_v6.post(api_key, body)
        assert resp is not None  # fatal=True never returns None
        batch_no = bi // BATCH
        (resp_dir / f"resp_{batch_no:03d}.json").write_text(json.dumps(resp))
        resp_orgs = resp.get("organizations") or []
        for r, ro in zip(chunk, resp_orgs):
            attrs = (ro or {}).get("attributes") or {}
            org_id = attrs.get("id")
            index.append(
                {
                    "crm_account_id": r.get("crm_account_id") or "",
                    "crm_account_name": r.get("name") or "",
                    "crm_url": r.get("domain") or r.get("url") or "",
                    "parent_crm_id": r.get("parent_crm_id") or "",
                    "owner": r.get("owner") or "",
                    "is_customer": r.get("is_customer") or "",
                    "created_date": r.get("created_date") or "",
                    "org_id": int(org_id) if org_id else None,
                }
            )
            if org_id:
                org_attrs[int(org_id)] = attrs
        matched_total += resp.get("matched_count") or 0
        print(
            f"[fetch] batch {batch_no + 1}: {len(chunk)} sent, "
            f"matched={resp.get('matched_count')} credits={resp.get('credits_used')}"
        )
    print(f"[fetch] accounts done: {len(rows)} rows, {matched_total} matched.")
    return index, org_attrs


def resolve_parents(
    org_attrs: dict[int, dict], api_key: str, resp_dir: Path, start_batch: int
) -> dict[int, dict]:
    """Phase 2: resolve unknown ancestor orgs by Sumble id, hop by hop."""
    select = {"attributes": sumble_v6.PARENT_ATTRIBUTES, "entities": []}
    known: dict[int, dict] = dict(org_attrs)
    parents: dict[int, dict] = {}
    batch_idx = start_batch
    frontier = _unknown_parent_ids(known.values(), known)
    for hop in range(MAX_PARENT_HOPS):
        if not frontier:
            break
        print(f"[fetch] parent hop {hop + 1}: resolving {len(frontier)} ancestor orgs")
        new_attrs: list[dict] = []
        ids = sorted(frontier)
        for bi in range(0, len(ids), BATCH):
            chunk = ids[bi : bi + BATCH]
            body = {"organizations": [{"id": i} for i in chunk], "select": select}
            resp = sumble_v6.post(api_key, body, fatal=False)
            if not resp:
                print("[fetch] parent lookup batch failed — continuing without it.")
                continue
            (resp_dir / f"resp_{batch_idx:03d}.json").write_text(json.dumps(resp))
            batch_idx += 1
            for ro in resp.get("organizations") or []:
                attrs = (ro or {}).get("attributes") or {}
                if attrs.get("id"):
                    new_attrs.append(attrs)
        for attrs in new_attrs:
            oid = int(attrs["id"])
            known[oid] = attrs
            parents[oid] = attrs
        frontier = _unknown_parent_ids(new_attrs, known)
    if frontier:
        print(
            f"[fetch] stopped at {MAX_PARENT_HOPS} hops with "
            f"{len(frontier)} ancestors unresolved (chains deeper than the cap)."
        )
    return parents


def _unknown_parent_ids(attr_rows, known: dict[int, dict]) -> set[int]:
    out: set[int] = set()
    for attrs in attr_rows:
        pid = attrs.get("parent_id")
        if pid and int(pid) not in known:
            out.add(int(pid))
    return out


def _parent_row(attrs: dict) -> dict:
    return {
        "id": int(attrs["id"]),
        "slug": attrs.get("slug") or "",
        "name": attrs.get("name") or "",
        "url": attrs.get("url") or "",
        "sumble_url": attrs.get("sumble_url") or "",
        "employee_count_int": sumble_v6.exact_employee_count(attrs),
        "headquarters_country": attrs.get("headquarters_country") or "",
        "parent_id": int(attrs["parent_id"]) if attrs.get("parent_id") else None,
        "tags": attrs.get("tags") or [],
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Resolve the CRM account list via /v6/organizations."
    )
    ap.add_argument("--raw", default="../_raw")
    ap.add_argument("--env-file", default=None, help="read SUMBLE_API_KEY from this file")
    args = ap.parse_args()

    raw = Path(args.raw).resolve()
    accounts_path = raw / "accounts.csv"
    if not accounts_path.exists():
        sys.exit(f"Missing {accounts_path} — write the CRM list first (Stage 1).")
    with accounts_path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit(f"{accounts_path} has no rows.")

    api_key = sumble_v6.load_api_key(args.env_file)
    resp_dir = _clear_responses(raw)

    index, org_attrs = match_accounts(rows, api_key, resp_dir)
    (raw / "fetch_index.json").write_text(json.dumps(index))

    n_account_batches = (len(rows) + BATCH - 1) // BATCH
    parents = resolve_parents(org_attrs, api_key, resp_dir, n_account_batches)
    (raw / "parent_orgs.json").write_text(
        json.dumps({str(k): _parent_row(v) for k, v in parents.items()})
    )
    print(
        f"[fetch] wrote fetch_index.json ({len(index)} rows) and "
        f"parent_orgs.json ({len(parents)} ancestor orgs)."
    )


if __name__ == "__main__":
    main()
