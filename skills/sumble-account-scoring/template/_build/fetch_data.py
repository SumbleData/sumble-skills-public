"""Stage 2 — fetch all calibration data from `POST /v6/organizations`.

Replaces the old SQL-generation + per-query MCP run. ONE endpoint, no SQL.

Modes (objective-driven; both phases below are optional, so one run serves
account-scoring, whitespace-only, or both):
  list   (default) — resolve + enrich the scored sample in `_raw/sample.csv`
         (columns: crm_account_id, name, domain[, is_gold][, is_owned]). In
         scoring mode this is the CRM calibration sample; in whitespace-only
         mode it's just the closed-won customers (is_gold=1) for calibration +
         eval. Each row's `account_category` (customer/allocated/unallocated) is
         derived from is_gold/is_owned. Skipped when sample.csv is absent/empty.
  filter (no CRM)  — rank Sumble's universe by an ICP advanced query
         (paginated), enriching each candidate with the same `select`.

  --whitespace N — rank N ICP-fit candidates NOT in the CRM and append them with
         `account_category=whitespace`. `_raw/crm.csv` (name,domain — the WHOLE
         CRM universe) is OPTIONAL: present → those org ids are excluded; absent
         → nothing excluded (a plain ICP ranking). Combine with sample.csv for
         "both", or use alone for whitespace-only.

Writes:
  _raw/responses/resp_*.json   raw endpoint responses (one per batch/page)
  _raw/crm_matches.json        [{org_id, name}] resolved CRM universe (--whitespace)
  _raw/fetch_index.json        per-org {crm_account_id, crm_account_name,
                               crm_url, is_gold, account_category} aligned to
                               the flattened response order (list mode; empty
                               in filter mode)

Auth: SUMBLE_API_KEY from the environment, or --env-file (e.g. notebooks/.env).

Usage:
  python fetch_data.py --raw _raw                          # list mode
  python fetch_data.py --raw _raw --whitespace 10000       # list + whitespace
  python fetch_data.py --raw _raw --whitespace 10000 --rank-only  # FREE preview
  python fetch_data.py --raw _raw --mode filter --pool 1000
"""

from __future__ import annotations

import argparse
import csv
import http.client
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
RANK_PAGE_CAP = 40  # base cap on filter pages scanned per stratum (scaled to quota)

# Stratified whitespace preselection weights (policy constant; same spec → same
# pool). Diversifies the candidate pool so it isn't just the biggest orgs.
STRATA_WEIGHTS = {
    "tech": 0.20,
    "project": 0.20,
    "persona_people": 0.20,
    "persona_growth": 0.40,
}
DEFAULT_MIN_EMPLOYEES = 50


def _truthy(v: object) -> bool:
    return str(v or "0").strip().lower() in ("1", "true", "yes")


def account_category(is_gold: bool, is_owned: bool) -> str:
    """Single source of truth, precedence customer > allocated > unallocated."""
    if is_gold:
        return "customer"
    return "allocated" if is_owned else "unallocated"


def load_api_key(env_file: str | None) -> str:
    key = sumble_v6.resolve_api_key(env_file, allow_prompt=sys.stdin.isatty())
    if not key:
        sys.exit(
            "No Sumble API key found. Run `python set_api_key.py` (prompts for the "
            "key and saves it), or `export SUMBLE_API_KEY=...`, or pass "
            "--env-file path/to/.env, then re-run."
        )
    return key


def post(api_key: str, body: dict, *, retries: int = 4, fatal: bool = True) -> dict | None:
    data = json.dumps(body).encode("utf-8")
    for attempt in range(retries):
        req = urllib.request.Request(sumble_v6.API_URL, data=data, method="POST")
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2**attempt)
                continue
            if not fatal:
                print(f"[fetch] HTTP {e.code} (non-fatal): {detail}")
                return None
            sys.exit(f"[fetch] HTTP {e.code}: {detail}")
        except (
            urllib.error.URLError,
            TimeoutError,
            http.client.IncompleteRead,
            http.client.HTTPException,
            ConnectionError,
            OSError,
        ) as e:
            if attempt < retries - 1:
                time.sleep(2**attempt)
                continue
            if not fatal:
                return None
            sys.exit(f"[fetch] network error: {e}")
    if fatal:
        raise SystemExit("[fetch] exhausted retries")
    return None


def _clear_responses(raw: Path) -> Path:
    resp_dir = raw / "responses"
    resp_dir.mkdir(exist_ok=True)
    for old in resp_dir.glob("resp_*.json"):
        old.unlink()
    return resp_dir


def run_list(
    sample: list[dict],
    select: dict,
    api_key: str,
    resp_dir: Path,
    start_batch: int,
    index: list[dict],
) -> int:
    """Enrich the scored CRM/customer sample, appending to `index`. Returns the
    next free batch index (so whitespace enrichment can continue numbering)."""
    matched_total = 0
    batch_idx = start_batch
    for bi in range(0, len(sample), BATCH):
        chunk = sample[bi : bi + BATCH]
        orgs = [
            {"name": r.get("name") or "", "url": r.get("domain") or r.get("url") or ""}
            for r in chunk
        ]
        body = {"organizations": orgs, "select": select}
        resp = post(api_key, body)
        assert resp is not None  # fatal=True never returns None
        (resp_dir / f"resp_{batch_idx:03d}.json").write_text(json.dumps(resp))
        batch_idx += 1
        matched_total += resp.get("matched_count") or 0
        for r in chunk:
            is_gold = _truthy(r.get("is_gold"))
            is_owned = _truthy(r.get("is_owned"))
            index.append(
                {
                    "crm_account_id": r.get("crm_account_id") or "",
                    "crm_account_name": r.get("name") or "",
                    "crm_url": r.get("domain") or r.get("url") or "",
                    "is_gold": int(is_gold),
                    "account_category": account_category(is_gold, is_owned),
                }
            )
        print(
            f"[fetch] batch {batch_idx}: {len(chunk)} sent, "
            f"matched={resp.get('matched_count')} credits={resp.get('credits_used')}"
        )
    print(f"[fetch] list done: {len(sample)} orgs, {matched_total} matched.")
    return batch_idx


def _icp_query(spec: dict) -> str:
    terms: list[str] = []
    tc = sumble_v6.tech_clause(spec["techs"])  # handles individual + category techs
    if tc:
        terms.append(tc)
    terms += [f"project EQ {sumble_v6._q(p['slug'])}" for p in spec.get("projects") or []]
    return "(" + " OR ".join(terms) + ")" if terms else "employee_count GTE 1"


def resolve_crm(raw: Path, api_key: str) -> set[int]:
    """Resolve the whole CRM universe (crm.csv: name,domain) → org ids to exclude
    from the whitespace pool. crm.csv is optional: with none, nothing is excluded
    (whitespace becomes a plain ICP ranking of Sumble's universe)."""
    path = raw / "crm.csv"
    if not path.exists():
        print("[fetch] no crm.csv — whitespace will not exclude any CRM accounts.")
        (raw / "crm_matches.json").write_text(json.dumps([]))
        return set()
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    matches: list[dict] = []
    select = {"attributes": ["id", "name"], "entities": []}
    for bi in range(0, len(rows), BATCH):
        chunk = rows[bi : bi + BATCH]
        orgs = [
            {"name": r.get("name") or "", "url": r.get("domain") or r.get("url") or ""}
            for r in chunk
        ]
        resp = post(api_key, {"organizations": orgs, "select": select})
        assert resp is not None  # fatal=True never returns None
        for ro in resp.get("organizations") or []:
            attrs = ro.get("attributes") or {}
            if attrs.get("id"):
                matches.append({"org_id": attrs["id"], "name": attrs.get("name") or ""})
        print(f"[fetch] CRM batch {bi // BATCH + 1}: matched={resp.get('matched_count')}")
    (raw / "crm_matches.json").write_text(json.dumps(matches))
    ids = {int(m["org_id"]) for m in matches}
    print(f"[fetch] CRM universe resolved: {len(ids)} org ids to exclude from whitespace.")
    return ids


# --- whitespace candidate preselection (phase 1, free id/name/url selects) ---
# Ported from the standalone whitespace skill so this skill fully subsumes it.


def _emp_gate(min_emp: int) -> str:
    # employee_count takes a range-string value ('min-' = >= min), not a GTE op.
    return f"employee_count EQ {sumble_v6._q(f'{min_emp}-')}" if min_emp > 0 else ""


def _and(*parts: str) -> str:
    return " AND ".join(p for p in parts if p)


def _project_clause(slugs: list[str]) -> str:
    return "(" + " OR ".join(f"project EQ {sumble_v6._q(s)}" for s in slugs) + ")"


def _exclude_clause(filters: dict) -> str:
    """Push hard-exclude TAGS into the rank query so excluded orgs don't eat a
    stratum quota. professional_services is industry-based (a merge-time filter)."""
    tags = filters.get("hard_exclude_tags") or []
    return f"tag NOT IN {sumble_v6._in_list(tags)}" if tags else ""


def rank_stratum(
    api_key: str, query: str, order_col: str, want: int, seen: set[int]
) -> list[dict]:
    """Paginate a filter query (cheap id/name/url select) collecting up to `want`
    NEW orgs (id not already in `seen`), ordered by `order_col` DESC."""
    select = {"attributes": ["id", "name", "url"], "entities": []}
    out: list[dict] = []
    page_cap = max(RANK_PAGE_CAP, (want + PAGE - 1) // PAGE * 4 + 5)
    for page in range(page_cap):
        if len(out) >= want:
            break
        body = {
            "filter": {"query": query},
            "select": select,
            "order_by_column": order_col,
            "order_by_direction": "DESC",
            "limit": PAGE,
            "offset": page * PAGE,
        }
        resp = post(api_key, body, fatal=False)
        if not resp:
            break
        orgs = resp.get("organizations") or []
        if not orgs:
            break
        for o in orgs:
            a = o.get("attributes") or {}
            oid = a.get("id")
            if not oid or int(oid) in seen:
                continue
            seen.add(int(oid))
            out.append({"name": a.get("name") or "", "url": a.get("url") or ""})
            if len(out) >= want:
                break
        if len(orgs) < PAGE:
            break
    return out


def select_candidates_stratified(
    spec: dict, api_key: str, pool: int, exclude_ids: set[int]
) -> tuple[list[dict], dict]:
    """Diversified pool in 4 strata (key tech / project / persona people / persona
    growth) so it isn't just the biggest orgs. Each stratum dedupes against the CRM
    and everything chosen before it; all gate on a min-employee floor."""
    filters = spec.get("universe_filters", {})
    min_emp = int(filters.get("min_employees", DEFAULT_MIN_EMPLOYEES) or 0)
    gate = _emp_gate(min_emp)
    excl = _exclude_clause(filters)

    key_tech_dicts = [t for t in spec["techs"] if t.get("tier") != "other"]
    key_projects = [p["slug"] for p in (spec.get("projects") or [])]
    key_personas = [p["name"] for p in spec["personas"] if p.get("tier") == "key"]
    if not key_tech_dicts:
        key_tech_dicts = list(spec["techs"])
    if not key_personas:
        key_personas = [p["name"] for p in spec["personas"]]
    key_tech_clause = sumble_v6.tech_clause(key_tech_dicts)  # individual + category

    q_tech = round(STRATA_WEIGHTS["tech"] * pool)
    q_proj = round(STRATA_WEIGHTS["project"] * pool)
    q_ppl = round(STRATA_WEIGHTS["persona_people"] * pool)
    q_growth = pool - q_tech - q_proj - q_ppl

    seen = set(exclude_ids)  # never pick CRM orgs or repeats
    composition: dict = {"strata": [], "min_employees": min_emp}
    chosen: list[dict] = []

    def take(label: str, query: str, order_col: str, want: int) -> None:
        if want <= 0 or not query:
            return
        picked = rank_stratum(api_key, query, order_col, want, seen)
        chosen.extend(picked)
        composition["strata"].append(
            {"stratum": label, "order_by": order_col, "wanted": want, "got": len(picked)}
        )
        print(f"[rank] {label}: wanted {want}, got {len(picked)} (order {order_col})")

    if key_tech_clause:
        take("key_tech_jobs",
             _and(key_tech_clause, gate, excl),
             "jobs_count", q_tech)
    if key_projects:
        take("key_project_jobs",
             _and(_project_clause(key_projects), gate, excl),
             "jobs_count", q_proj)
    if key_personas:
        take("key_persona_people",
             _and(f"job_function IN {sumble_v6._in_list(key_personas)}", gate, excl),
             "people_count", q_ppl)
        n = len(key_personas)
        base = q_growth // n
        rem = q_growth - base * n
        for i, name in enumerate(key_personas):
            take(f"key_persona_growth:{name}",
                 _and(f"job_function EQ {sumble_v6._q(name)}", gate, excl),
                 "jobs_count_growth_6mo", base + (1 if i < rem else 0))

    composition["total_selected"] = len(chosen)
    composition["pool_target"] = pool
    return chosen, composition


def select_candidates_ordered(
    spec: dict, api_key: str, pool: int, exclude_ids: set[int], order_col: str
) -> tuple[list[dict], dict]:
    """Single-order preselection (e.g. account_score): orgs matching the ICP
    (OR of techs + projects), ranked by one column."""
    filters = spec.get("universe_filters", {})
    min_emp = int(filters.get("min_employees", DEFAULT_MIN_EMPLOYEES) or 0)
    projects = [p["slug"] for p in (spec.get("projects") or [])]
    tc = sumble_v6.tech_clause(spec["techs"])  # individual + category techs
    terms = [tc] if tc else []
    if projects:
        terms.append(_project_clause(projects))
    icp = "(" + " OR ".join(terms) + ")" if terms else ""
    query = _and(icp, _emp_gate(min_emp), _exclude_clause(filters)) or "employee_count EQ '1-'"
    chosen = rank_stratum(api_key, query, order_col, pool, set(exclude_ids))
    comp = {"strata": [{"stratum": order_col, "order_by": order_col, "wanted": pool,
                        "got": len(chosen)}], "total_selected": len(chosen),
            "pool_target": pool}
    print(f"[rank] {order_col}: wanted {pool}, got {len(chosen)}")
    return chosen, comp


def account_score_available(api_key: str) -> bool:
    """Probe whether the caller's domain exposes Sumble account scores."""
    body = {
        "filter": {"query": "employee_count GTE 100000"},
        "select": {"attributes": ["id", "name", "sumble_score"], "entities": []},
        "order_by_column": "account_score",
        "order_by_direction": "DESC",
        "limit": 3,
        "offset": 0,
    }
    resp = post(api_key, body, fatal=False)
    if not resp:
        return False
    for o in resp.get("organizations") or []:
        if (o.get("attributes") or {}).get("sumble_score") is not None:
            return True
    return False


def rank_whitespace(
    raw: Path, spec: dict, api_key: str, pool: int, exclude_ids: set[int]
) -> list[dict]:
    """Preselect ICP-fit candidates NOT in the CRM. `preselect` (in
    spec.universe_filters) is `auto` (→ account_score when the domain has scores,
    else stratified), `stratified`, or `account_score`. Phase 1 is FREE (id/name/url
    selects cost no credits); only the final pool is enriched (phase 2)."""
    preselect = (spec.get("universe_filters", {}) or {}).get("preselect", "auto")
    if preselect == "auto":
        preselect = "account_score" if account_score_available(api_key) else "stratified"
        print(f"[fetch] whitespace preselect auto-detected: {preselect}")
    if preselect == "account_score":
        candidates, comp = select_candidates_ordered(
            spec, api_key, pool, exclude_ids, "account_score"
        )
    else:
        candidates, comp = select_candidates_stratified(spec, api_key, pool, exclude_ids)
    comp["preselect"] = preselect
    (raw / "_preselection.json").write_text(
        json.dumps({"composition": comp, "candidates": candidates}, indent=2)
    )
    print(f"[fetch] whitespace ranked: {len(candidates)} net-new candidates "
          f"(target {pool}, {preselect}).")
    return candidates


def enrich_whitespace(
    resp_dir: Path,
    candidates: list[dict],
    select: dict,
    api_key: str,
    start_batch: int,
    index: list[dict],
) -> None:
    """Enrich whitespace candidates, appending responses + index entries."""
    batch_idx = start_batch
    for bi in range(0, len(candidates), BATCH):
        chunk = candidates[bi : bi + BATCH]
        orgs = [{"name": c["name"], "url": c["url"]} for c in chunk]
        resp = post(api_key, {"organizations": orgs, "select": select})
        assert resp is not None  # fatal=True never returns None
        (resp_dir / f"resp_{batch_idx:03d}.json").write_text(json.dumps(resp))
        batch_idx += 1
        for c in chunk:
            index.append(
                {
                    "crm_account_id": "",
                    "crm_account_name": "",
                    "crm_url": c.get("url") or "",
                    "is_gold": 0,
                    "account_category": "whitespace",
                }
            )
        print(
            f"[fetch] whitespace batch {batch_idx - start_batch}: {len(chunk)} sent, "
            f"matched={resp.get('matched_count')} credits={resp.get('credits_used')}"
        )
    print(f"[fetch] whitespace enriched: {len(candidates)} candidates.")


def run_filter(raw: Path, spec: dict, select: dict, api_key: str, pool: int) -> None:
    """Rank Sumble's universe by an ICP advanced query, enriching each page."""
    query = _icp_query(spec)
    order_col = spec.get("universe_filters", {}).get("order_by_column", "employee_count")

    resp_dir = _clear_responses(raw)
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
        assert resp is not None  # fatal=True never returns None
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
    ap.add_argument(
        "--whitespace",
        type=int,
        default=0,
        metavar="N",
        help="list mode: also rank+enrich N net-new (non-CRM) whitespace candidates",
    )
    ap.add_argument(
        "--rank-only",
        action="store_true",
        help="whitespace: do the FREE candidate rank + write _preselection.json, "
        "then stop (no enrichment, no credits) — a preview of who'd be in the pool",
    )
    ap.add_argument("--env-file", default=None, help="read SUMBLE_API_KEY from this file")
    args = ap.parse_args()

    raw = Path(args.raw).resolve()
    spec = json.loads((raw / "spec.json").read_text())
    select = sumble_v6.build_select(spec)
    api_key = load_api_key(args.env_file)

    if args.mode == "filter":
        run_filter(raw, spec, select, api_key, args.pool)
        return

    # Free whitespace preview: rank only, write _preselection.json, spend nothing.
    if args.rank_only:
        if args.whitespace <= 0:
            sys.exit("--rank-only needs --whitespace N (it previews the whitespace pool).")
        crm_ids = resolve_crm(raw, api_key)
        rank_whitespace(raw, spec, api_key, args.whitespace, crm_ids)
        print("[fetch] --rank-only: wrote _raw/_preselection.json; no enrichment, no credits.")
        return

    # Unified list/whitespace path. Both phases are optional, so this serves
    # account-scoring (sample only), whitespace-only (--whitespace, no sample),
    # and both. The scored sample (sample.csv) holds CRM rows in scoring mode, or
    # just the closed-won customers in whitespace-only mode (for calibration/eval).
    resp_dir = _clear_responses(raw)
    index: list[dict] = []
    next_batch = 0

    sample_path = raw / "sample.csv"
    sample: list[dict] = []
    if sample_path.exists():
        with sample_path.open(newline="") as f:
            sample = list(csv.DictReader(f))
    if sample:
        next_batch = run_list(sample, select, api_key, resp_dir, next_batch, index)
    else:
        print("[fetch] no sample.csv rows — skipping the scored CRM/customer list.")

    if args.whitespace > 0:
        crm_ids = resolve_crm(raw, api_key)
        candidates = rank_whitespace(raw, spec, api_key, args.whitespace, crm_ids)
        enrich_whitespace(resp_dir, candidates, select, api_key, next_batch, index)

    if not index:
        sys.exit(
            "Nothing to fetch: provide _raw/sample.csv (scored accounts and/or "
            "closed-won customers) and/or pass --whitespace N."
        )
    (raw / "fetch_index.json").write_text(json.dumps(index))
    print(f"[fetch] wrote fetch_index.json ({len(index)} orgs).")


if __name__ == "__main__":
    main()
