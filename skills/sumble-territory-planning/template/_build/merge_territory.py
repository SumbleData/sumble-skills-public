"""Join every input into `territory.csv` — one row per Sumble org.

Inputs (all under `_raw/`, all optional except the account table):
  spec.json / ../territory-plan.json   segments, boundary, roster, activity window
  score.csv (via plan.score_source) OR sumble_light.csv   identity + strength score
  ownership.csv    crm_account_id,name,domain,owner,owner_email[,owner_is_queue][,is_customer]
  reps.csv         the roster (read from the plan, which build_plan.py validated)
  activity/*.csv   source,rep_email,account_domain,kind,ts
  pipeline.csv     domain,pipeline_value

The join key is the Sumble `org_id`, which is what makes double allocation
detectable: two CRM records with different names and domains that resolve to the
same organisation are two reps working one company, and no amount of
name-matching would have found it.

Flags written per row (each is a highlight the app can filter on):
  unallocated      nobody owns it, or its owner is a queue / not an active rep
  double_allocated two or more active reps own records for the same org
  segment_misfit   the account's size segment differs from its owner's segment
  worked           the owner has outbound activity with the account in-window
  strong_idle      top-quartile score for its segment AND not worked

Usage:
  python3 merge_territory.py --raw /abs/path/_raw
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import territory_lib as tl

# Which account_category wins when several CRM records resolve to one org.
CATEGORY_RANK = {
    "customer": 4,
    "allocated": 3,
    "unallocated": 2,
    "whitespace_subsidiary": 1,
    "whitespace": 0,
    "": 0,
}
WHITESPACE_CATEGORIES = {"whitespace", "whitespace_subsidiary"}


def load_account_table(raw: Path, plan: dict) -> tuple[list[dict], str, str]:
    """(rows, score column, score source label)."""
    source = plan.get("score_source") or {}
    if str(source.get("kind") or "") == "custom" and source.get("path"):
        path = Path(str(source["path"])).expanduser()
        if not path.exists():
            sys.exit(f"[merge] score.csv not found: {path}")
        rows = tl.read_csv(path)
        if rows and "score" not in rows[0]:
            sys.exit(f"[merge] {path} has no 'score' column — is it an account-scoring score.csv?")
        return rows, "score", "custom"
    path = raw / "sumble_light.csv"
    if not path.exists():
        sys.exit(
            f"[merge] {path} not found. Either run fetch_light.py, or set "
            "score_source.kind='custom' with the path to an account-scoring score.csv."
        )
    return tl.read_csv(path), "sumble_score", "sumble"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--plan", default=None, help="territory-plan.json (default: <raw>/../territory-plan.json)")
    ap.add_argument("--out", default=None, help="territory.csv (default: <raw>/../territory.csv)")
    args = ap.parse_args()

    raw = Path(args.raw).expanduser().resolve()
    root = raw.parent
    plan_path = Path(args.plan).expanduser() if args.plan else root / "territory-plan.json"
    if not plan_path.exists():
        sys.exit(f"[merge] {plan_path} not found — run build_plan.py first.")
    plan = tl.read_json(plan_path)
    out_path = Path(args.out).expanduser() if args.out else root / "territory.csv"

    segments = plan["segments"]
    boundary = plan["boundary"]
    reps = plan["reps"]
    active_reps = {r["name"]: r for r in reps if r.get("is_rep")}

    acct_rows, score_col, score_source = load_account_table(raw, plan)
    if not acct_rows:
        sys.exit("[merge] the account table is empty.")
    size_col = tl.resolve_size_column(
        {"boundary": boundary}, acct_rows[0].keys()
    )
    if size_col not in acct_rows[0]:
        sys.exit(
            f"[merge] boundary column '{size_col}' is missing from the account table. "
            "Run fetch_light.py --only-jf to add it, or switch the boundary to total "
            "employee count."
        )

    # --- 1. collapse the account table to one record per org -------------------
    orgs: dict[str, dict] = {}
    for r in acct_rows:
        org_id = str(r.get("org_id") or "").strip()
        if not org_id:
            continue
        dom = tl.norm_domain(r.get("url") or r.get("domain") or r.get("input_domain"))
        cat = str(r.get("account_category") or "").strip()
        rec = orgs.get(org_id)
        if rec is None:
            rec = {
                "org_id": org_id,
                "name": r.get("name") or r.get("crm_account_name") or "",
                "domains": set(),
                "crm_account_ids": set(),
                "account_category": cat,
                "score": tl.to_float(r.get(score_col)),
                "size_metric": tl.to_float(r.get(size_col)),
                "sumble_url": r.get("sumble_url") or "",
            }
            orgs[org_id] = rec
        else:
            # Keep the strongest category and the highest score seen for the org.
            if CATEGORY_RANK.get(cat, 0) > CATEGORY_RANK.get(rec["account_category"], 0):
                rec["account_category"] = cat
            rec["score"] = max(rec["score"], tl.to_float(r.get(score_col)))
        if dom:
            rec["domains"].add(dom)
        for key in ("crm_account_id", "crm_id"):
            if str(r.get(key) or "").strip():
                rec["crm_account_ids"].add(str(r[key]).strip())

    # Lookups for resolving ownership rows onto orgs.
    by_domain: dict[str, str] = {}
    by_name: dict[str, str] = {}
    by_crm_id: dict[str, str] = {}
    for org_id, rec in orgs.items():
        for d in rec["domains"]:
            by_domain.setdefault(d, org_id)
        nm = str(rec["name"] or "").strip().lower()
        if nm:
            by_name.setdefault(nm, org_id)
        for cid in rec["crm_account_ids"]:
            by_crm_id.setdefault(cid, org_id)

    # --- 2. ownership ---------------------------------------------------------
    ownership = tl.read_csv(raw / "ownership.csv")
    owners_by_org: dict[str, list[dict]] = {}
    unresolved = 0
    customers: set[str] = set()
    for o in ownership:
        cid = str(o.get("crm_account_id") or "").strip()
        dom = tl.norm_domain(o.get("domain") or o.get("url"))
        nm = str(o.get("name") or "").strip().lower()
        org_id = by_crm_id.get(cid) or by_domain.get(dom) or by_name.get(nm)
        if not org_id:
            unresolved += 1
            continue
        rec = orgs[org_id]
        if dom:
            rec["domains"].add(dom)
        if cid:
            rec["crm_account_ids"].add(cid)
        if tl.truthy(o.get("is_customer")):
            customers.add(org_id)
        owner = str(o.get("owner") or "").strip()
        if not owner:
            continue
        owners_by_org.setdefault(org_id, []).append({
            "owner": owner,
            "owner_email": tl.norm_email(o.get("owner_email")) or (
                active_reps.get(owner, {}).get("email", "")
            ),
            "is_queue": tl.truthy(o.get("owner_is_queue")),
            "crm_account_id": cid,
        })

    # --- 3. activity + pipeline ----------------------------------------------
    window = tl.to_int((plan.get("activity") or {}).get("window_days"), 90) or 90
    activity = tl.load_activity(raw, window)
    pipeline = {
        tl.norm_domain(p.get("domain") or p.get("url")): tl.to_float(p.get("pipeline_value"))
        for p in tl.read_csv(raw / "pipeline.csv")
    }

    # --- 4. build one row per org --------------------------------------------
    rows: list[dict] = []
    for org_id in sorted(orgs, key=lambda k: int(k) if str(k).isdigit() else 0):
        rec = orgs[org_id]
        domains = sorted(rec["domains"])
        primary_domain = domains[0] if domains else ""
        owners = owners_by_org.get(org_id, [])

        # Only ACTIVE reps count as an allocation. A queue, an integration user,
        # or someone who has left the company is an unowned account wearing a
        # name — the single most common reason a "covered" book isn't covered.
        real = [o for o in owners if not o["is_queue"] and o["owner"] in active_reps]
        distinct = sorted({o["owner"] for o in real})

        # Canonical owner when several reps own the same org: whoever actually
        # has the relationship (most activity), ties alphabetically.
        chosen = ""
        chosen_email = ""
        best_activity = -1
        for owner in distinct:
            email = next((o["owner_email"] for o in real if o["owner"] == owner), "") or \
                active_reps.get(owner, {}).get("email", "")
            act = tl.activity_for(activity, email, domains)
            total = int(act["outbound_total"]) + int(act["email_in"])
            if total > best_activity:
                chosen, chosen_email, best_activity = owner, email, total

        rep = active_reps.get(chosen, {})
        rep_segment = str(rep.get("segment") or "")
        act = tl.activity_for(activity, chosen_email, domains)

        category = rec["account_category"]
        if not category or category not in CATEGORY_RANK:
            category = ""
        if org_id in customers:
            category = "customer"
        if not category:
            # Path B has no CRM category column — derive it from ownership.
            category = "allocated" if chosen else "unallocated"

        size_metric = rec["size_metric"]
        account_segment = tl.segment_for_size(size_metric, boundary, segments)
        is_whitespace = category in WHITESPACE_CATEGORIES
        unallocated = 0 if chosen else 1

        rows.append({
            "org_id": org_id,
            "name": rec["name"],
            "domain": primary_domain,
            "crm_account_id": "|".join(sorted(rec["crm_account_ids"])),
            "account_category": category,
            "score": round(rec["score"], 4),
            "score_source": score_source,
            "size_metric": round(size_metric, 2),
            "size_metric_name": boundary.get("label") or boundary.get("metric") or size_col,
            "account_segment": account_segment,
            "owner": chosen,
            "owner_email": chosen_email,
            "rep_segment": rep_segment,
            "unallocated": 0 if is_whitespace else unallocated,
            "double_allocated": 1 if len(distinct) > 1 else 0,
            "other_owners": "|".join(o for o in distinct if o != chosen),
            "segment_misfit": 1 if (chosen and rep_segment and account_segment and rep_segment != account_segment) else 0,
            "worked": 1 if act["outbound_total"] > 0 else 0,
            "strong_idle": 0,  # needs the per-segment p75, computed below
            "meetings": act["meeting"],
            "calls": act["call"],
            "emails_out": act["email_out"],
            "emails_in": act["email_in"],
            "last_activity_date": act["last_activity_date"],
            "activity_sources": act["activity_sources"],
            "pipeline_value": next(
                (pipeline[d] for d in domains if d in pipeline), ""
            ),
            "sumble_url": rec["sumble_url"],
            "proposed_owner": "",
            "proposal_reason": "",
            "proposal_status": "",
        })

    # strong_idle needs each segment's own p75: "strong" means strong for the
    # kind of company it is, so an enterprise cutoff isn't applied to SMB books.
    for seg in {r["account_segment"] for r in rows}:
        scored = [
            r["score"] for r in rows
            if r["account_segment"] == seg and r["account_category"] not in WHITESPACE_CATEGORIES
        ]
        p75 = tl.percentile(scored, 0.75)
        for r in rows:
            if r["account_segment"] == seg and r["score"] >= p75 and not r["worked"] and r["owner"]:
                r["strong_idle"] = 1

    # Trim whitespace to the routing depth — the rest is an account-scoring
    # question, not a territory one, and would swamp the sheet.
    top_n = tl.to_int((plan.get("move_policy") or {}).get("whitespace_top_n"), tl.DEFAULT_WHITESPACE_TOP_N)
    ws = [r for r in rows if r["account_category"] in WHITESPACE_CATEGORIES]
    dropped_ws = 0
    if len(ws) > top_n:
        keep = {
            r["org_id"] for r in sorted(ws, key=lambda r: (-r["score"], r["org_id"]))[:top_n]
        }
        dropped_ws = len(ws) - len(keep)
        rows = [
            r for r in rows
            if r["account_category"] not in WHITESPACE_CATEGORIES or r["org_id"] in keep
        ]

    rows.sort(key=lambda r: (-r["score"], r["org_id"]))
    tl.write_csv(out_path, rows, tl.TERRITORY_COLUMNS)

    # --- 5. audit -------------------------------------------------------------
    counts = {
        "orgs": len(rows),
        "allocated": sum(1 for r in rows if r["owner"]),
        "unallocated": sum(1 for r in rows if r["unallocated"]),
        "double_allocated": sum(1 for r in rows if r["double_allocated"]),
        "segment_misfit": sum(1 for r in rows if r["segment_misfit"]),
        "not_worked": sum(1 for r in rows if r["owner"] and not r["worked"]),
        "strong_idle": sum(1 for r in rows if r["strong_idle"]),
        "whitespace_kept": sum(1 for r in rows if r["account_category"] in WHITESPACE_CATEGORIES),
        "whitespace_dropped": dropped_ws,
        "ownership_rows_unresolved": unresolved,
        "activity_pairs": len(activity),
    }
    balance = tl.book_stats(rows, reps, (plan.get("balance") or {}).get(
        "include_categories", tl.DEFAULT_BALANCE_CATEGORIES))
    tl.write_json(raw / "_territory_audit.json", {
        "schema_version": tl.SCHEMA_VERSION,
        "score_source": score_source,
        "size_column": size_col,
        "activity_window_days": window,
        "counts": counts,
        "balance": {
            k: {"cv": round(v["cv"], 4), "label": v["label"], "reps": len(v["reps"])}
            for k, v in balance.items()
        },
    })

    print(f"[merge] wrote {out_path} · {counts['orgs']:,} orgs")
    print(
        f"[merge] {counts['allocated']:,} allocated · {counts['unallocated']:,} unallocated · "
        f"{counts['double_allocated']:,} double-allocated · {counts['segment_misfit']:,} misfit · "
        f"{counts['not_worked']:,} not worked · {counts['strong_idle']:,} strong-but-idle"
    )
    for seg, b in sorted(balance.items()):
        print(f"[merge] balance · {seg}: CV {b['cv']:.2f} ({b['label']}) across {len(b['reps'])} reps")
    if unresolved:
        print(
            f"[merge] NOTE: {unresolved:,} ownership rows didn't match any org in the "
            "account table (unmatched by Sumble, or outside the scored set) and were skipped."
        )
    if dropped_ws:
        print(f"[merge] trimmed whitespace to the top {top_n} by score ({dropped_ws:,} dropped).")
    if not activity:
        print(
            "[merge] NOTE: no activity events found — every account will read "
            "'not worked'. Check _raw/activity/*.csv and the rep emails in reps.csv."
        )


if __name__ == "__main__":
    main()
