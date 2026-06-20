"""Stage 3 — turn the fetched org data into review findings.

Reads `_raw/fetch_index.json` + `_raw/responses/resp_*.json` +
`_raw/parent_orgs.json` (+ `_raw/config.json` for thresholds/checks) and writes:

  <output_root>/findings.json   everything the review app renders
  <output_root>/findings.csv    flat one-row-per-finding-account export

Detection is pure, deterministic policy — same inputs → byte-identical output.

Duplicate evidence — exactly one kind, by design:
  same_sumble_org   two CRM accounts resolve to the SAME Sumble org   → high
Sumble's matcher (`POST /v6/organizations`) is the sole duplicate signal —
no domain or name-similarity matching. Pairs already linked parent↔child
inside the CRM are never duplicate evidence (they're hierarchy, not dupes).

Each duplicate cluster is also tagged with a resolution-difficulty `category`
(see `categorize_cluster`), so the reviewer can triage:
  multi_owner     ≥2 distinct owners — decide who keeps the account (hard)
  split_activity  one owner, CRM footprint spread over >1 record — merge so no
                  history is lost (easy-ish)
  concentrated    one owner, footprint on ≤1 record — keep it, drop shells (easy)

Parent/subsidiary findings (walking each account's Sumble ancestor chain):
  missing_parent_link  the nearest ancestor that IS a CRM account, but the
                       CRM has no parent set on the child  → high (direct
                       parent) / medium (grandparent+)
  parent_conflict      the CRM parent differs from every org in the Sumble
                       ancestor chain                       → medium
  parent_not_in_crm    the account has a Sumble parent but no ancestor is a
                       CRM account — grouped per parent org → info

Usage:
  python3 analyze.py --raw <output_root>/_raw
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

import sumble_v6

MAX_ANCESTOR_DEPTH = 6

# Trailing legal-entity tokens stripped during name normalization (used only
# for the dissimilar-names note on duplicate clusters). Only ever stripped
# from the END of a name (repeatedly), so "Limited Brands" survives.
LEGAL_SUFFIXES = {
    "inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation",
    "co", "company", "gmbh", "sa", "sas", "srl", "bv", "ab", "plc", "pty",
    "llp", "lp", "kk", "oy", "as", "nv", "ag", "spa", "pvt", "sarl",
}

CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}

# Duplicate clusters are bucketed by how hard they are to resolve, so the
# reviewer can triage the hard ownership conflicts away from the trivial
# shell-merges. Ordered hardest → easiest (drives the default display order).
DUP_CATEGORIES = ("multi_owner", "split_activity", "concentrated")
CATEGORY_ORDER = {c: i for i, c in enumerate(DUP_CATEGORIES)}


def norm_domain(raw: str) -> str:
    d = (raw or "").strip().lower()
    d = re.sub(r"^[a-z][a-z0-9+.-]*://", "", d)
    d = d.split("/")[0].split("?")[0].split(":")[0]
    if d.startswith("www."):
        d = d[4:]
    return d


def norm_name(raw: str) -> str:
    n = (raw or "").lower()
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    tokens = n.split()
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def name_token_key(raw: str) -> str:
    return " ".join(sorted(norm_name(raw).split()))


class UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


# Optional per-account CRM metadata sidecar (`_raw/accounts_meta.csv`,
# columns: crm_account_id[, city][, state][, country][, linkedin_url]
# [, last_modified]). Pure pass-through for the review UI — never used as
# detection evidence.
META_FIELDS = (
    "crm_city",
    "crm_state",
    "crm_country",
    "crm_linkedin_url",
    "crm_last_modified",
)


def load_accounts_meta(raw: Path) -> dict[str, dict]:
    path = raw / "accounts_meta.csv"
    if not path.exists():
        return {}
    meta: dict[str, dict] = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            aid = (row.get("crm_account_id") or "").strip()
            if not aid:
                continue
            meta[aid] = {
                "crm_city": row.get("city") or "",
                "crm_state": row.get("state") or "",
                "crm_country": row.get("country") or "",
                "crm_linkedin_url": row.get("linkedin_url") or "",
                "crm_last_modified": row.get("last_modified") or "",
            }
    return meta


# Optional CRM-footprint columns in `_raw/accounts.csv` — how much CRM history
# each record carries. Read at analyze time (keyed by crm_account_id), so they
# can be added or refreshed without re-fetching from Sumble. They feed the
# merge-survivor suggestion and are shown on duplicate cards.
COUNT_FIELDS = ("contact_count", "opportunity_count", "activity_count")


def load_account_counts(raw: Path) -> dict[str, dict]:
    path = raw / "accounts.csv"
    if not path.exists():
        return {}
    counts: dict[str, dict] = {}
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        present = [c for c in COUNT_FIELDS if c in (reader.fieldnames or [])]
        if not present:
            return {}
        for row in reader:
            aid = (row.get("crm_account_id") or "").strip()
            if not aid:
                continue
            counts[aid] = {
                c: int(row[c]) if (row.get(c) or "").strip().isdigit() else 0
                for c in COUNT_FIELDS
            }
    return counts


def load_org_alternates(raw: Path) -> dict[int, dict]:
    """Optional display-only sidecar `_raw/org_alternates.json`:
    {"<org_id>": {"name_alternates": [...], "url_alternates": [...]}}.
    Alternate names/domains Sumble knows for matched orgs — shown on the
    finding cards to clarify WHY accounts matched; never detection evidence.
    (The public /v6/organizations endpoint does not expose alternates yet, so
    this file is populated out-of-band when available; absent → no-op.)"""
    path = raw / "org_alternates.json"
    if not path.exists():
        return {}
    return {int(k): v or {} for k, v in json.loads(path.read_text()).items()}


def load_org_attrs(raw: Path) -> dict[int, dict]:
    """All org attributes seen in any response (CRM matches + parent lookups)."""
    attrs: dict[int, dict] = {}
    for path in sorted((raw / "responses").glob("resp_*.json")):
        resp = json.loads(path.read_text())
        for ro in resp.get("organizations") or []:
            a = (ro or {}).get("attributes") or {}
            if a.get("id"):
                attrs[int(a["id"])] = a
    return attrs


def build_rows(
    index: list[dict],
    org_attrs: dict[int, dict],
    accounts_meta: dict[str, dict] | None = None,
    crm_url_template: str = "",
    org_alternates: dict[int, dict] | None = None,
    account_counts: dict[str, dict] | None = None,
) -> list[dict]:
    accounts_meta = accounts_meta or {}
    org_alternates = org_alternates or {}
    account_counts = account_counts or {}
    rows: list[dict] = []
    for i, entry in enumerate(index):
        org_id = int(entry["org_id"]) if entry.get("org_id") else None
        attrs = org_attrs.get(org_id) if org_id else None
        crm_account_id = entry.get("crm_account_id") or ""
        row = {
            "idx": i,
            "crm_account_id": crm_account_id,
            "crm_url": crm_url_template.replace("{id}", crm_account_id)
            if crm_url_template and crm_account_id
            else "",
            "crm_name": entry.get("crm_account_name") or "",
            "crm_domain": norm_domain(entry.get("crm_url") or ""),
            "parent_crm_id": entry.get("parent_crm_id") or "",
            "owner": entry.get("owner") or "",
            "is_customer": str(entry.get("is_customer") or "").strip().lower()
            in ("1", "true", "yes"),
            "created_date": entry.get("created_date") or "",
            "org_id": org_id,
            "sumble_name": "",
            "sumble_slug": "",
            "sumble_domain": "",
            "sumble_url": "",
            "sumble_name_alternates": [],
            "sumble_url_alternates": [],
            "employee_count_int": 0,
            "headquarters_country": "",
            "sumble_parent_id": None,
        }
        row.update(dict.fromkeys(META_FIELDS, ""))
        row.update(accounts_meta.get(row["crm_account_id"], {}))
        row.update(dict.fromkeys(COUNT_FIELDS, 0))
        row.update(account_counts.get(row["crm_account_id"], {}))
        if attrs:
            row["sumble_name"] = attrs.get("name") or ""
            row["sumble_slug"] = attrs.get("slug") or ""
            row["sumble_domain"] = norm_domain(attrs.get("url") or "")
            row["sumble_url"] = attrs.get("sumble_url") or (
                f"https://sumble.com/org/{attrs.get('slug')}" if attrs.get("slug") else ""
            )
            row["employee_count_int"] = sumble_v6.exact_employee_count(attrs)
            row["headquarters_country"] = attrs.get("headquarters_country") or ""
            pid = attrs.get("parent_id")
            row["sumble_parent_id"] = int(pid) if pid else None
            alt = org_alternates.get(org_id) or {} if org_id else {}
            row["sumble_name_alternates"] = alt.get("name_alternates") or []
            row["sumble_url_alternates"] = alt.get("url_alternates") or []
        rows.append(row)
    return rows


def crm_linked(a: dict, b: dict) -> bool:
    """True when the CRM already relates the two accounts parent↔child."""
    ida, idb = a["crm_account_id"], b["crm_account_id"]
    return bool(
        (ida and b["parent_crm_id"] == ida) or (idb and a["parent_crm_id"] == idb)
    )


def find_duplicates(rows: list[dict]) -> list[dict]:
    """Cluster CRM accounts that resolve to the SAME Sumble org.

    `same_sumble_org` is the only duplicate evidence: Sumble's matcher mapped
    two CRM accounts to one org id. CRM parent↔child pairs are suppressed
    (hierarchy, not dupes); larger same-org groups keep their other members.
    """
    groups: dict[int, list[int]] = {}
    for r in rows:
        if r["org_id"]:
            groups.setdefault(r["org_id"], []).append(r["idx"])

    uf = UnionFind(len(rows))
    edges: set[tuple[int, int]] = set()
    for members in groups.values():
        for ai in range(len(members)):
            for bi in range(ai + 1, len(members)):
                i, j = members[ai], members[bi]
                if crm_linked(rows[i], rows[j]):
                    continue
                edges.add((i, j))
                uf.union(i, j)

    clusters: dict[int, set[int]] = {}
    for i, j in edges:
        clusters.setdefault(uf.find(i), set()).update((i, j))

    findings: list[dict] = []
    for root in sorted(clusters):
        members = sorted(clusters[root])
        if len(members) < 2:
            continue
        member_rows = [rows[i] for i in members]
        note = ""
        if len({name_token_key(r["crm_name"]) for r in member_rows}) > 1:
            note = (
                "Same Sumble org but dissimilar CRM names — verify this isn't a "
                "parent/subsidiary pair both matching the parent org."
            )
        category, owners, footprint_records = categorize_cluster(member_rows)
        findings.append(
            {
                "confidence": "high",
                "evidence": ["same_sumble_org"],
                "category": category,
                "owners": owners,
                "footprint_records": footprint_records,
                "suggested_survivor_crm_id": pick_survivor(member_rows),
                "accounts": [account_payload(r) for r in member_rows],
                "note": note,
            }
        )
    findings.sort(
        key=lambda f: (
            CATEGORY_ORDER[f["category"]],
            -len(f["accounts"]),
            f["accounts"][0]["crm_account_id"],
        )
    )
    for i, f in enumerate(findings):
        f["id"] = f"dup_{i + 1:04d}"
    return findings


def categorize_cluster(member_rows: list[dict]) -> tuple[str, list[str], int]:
    """Bucket a duplicate cluster by resolution difficulty.

    multi_owner     ≥2 distinct (non-empty) owners across the cluster — the
                    records belong to different reps, so someone has to give up
                    the account before it can be merged (hard).
    split_activity  one owner (or none), but CRM footprint
                    (contacts + opportunities + activities) sits on >1 record —
                    merge so no relationship history is lost (easy-ish).
    concentrated    one owner (or none) with footprint on ≤1 record — keep the
                    populated record and drop the empty shells (easy). Also the
                    bucket when no `*_count` columns were provided, since spread
                    can't be detected without them.

    Priority: multi_owner wins over the activity split — an ownership conflict
    is the dominant concern regardless of how the footprint is distributed.
    Returns (category, sorted distinct owners, count of records with footprint).
    """
    owners_by_key: dict[str, str] = {}
    for r in member_rows:
        o = (r.get("owner") or "").strip()
        if o:
            owners_by_key.setdefault(o.lower(), o)
    owners = [owners_by_key[k] for k in sorted(owners_by_key)]
    footprint_records = sum(
        1 for r in member_rows if sum(r.get(c) or 0 for c in COUNT_FIELDS) > 0
    )
    if len(owners) >= 2:
        category = "multi_owner"
    elif footprint_records > 1:
        category = "split_activity"
    else:
        category = "concentrated"
    return category, owners, footprint_records


def pick_survivor(member_rows: list[dict]) -> str:
    """Deterministic survivor suggestion: owned > customer > biggest CRM
    footprint (contacts + opportunities + activities) > most-complete >
    oldest created_date > lowest CRM id."""

    def sort_key(r: dict):
        footprint = sum(r.get(c) or 0 for c in COUNT_FIELDS)
        completeness = sum(
            1
            for k in ("crm_domain", "owner", "parent_crm_id", "created_date")
            if r[k]
        )
        return (
            0 if r["owner"] else 1,
            0 if r["is_customer"] else 1,
            -footprint,
            -completeness,
            r["created_date"] or "9999-12-31",
            r["crm_account_id"],
        )

    return sorted(member_rows, key=sort_key)[0]["crm_account_id"]


def account_payload(r: dict) -> dict:
    return {
        k: r[k]
        for k in (
            "crm_account_id",
            "crm_url",
            "crm_name",
            "crm_domain",
            "parent_crm_id",
            "owner",
            "is_customer",
            "created_date",
            *COUNT_FIELDS,
            "org_id",
            "sumble_name",
            "sumble_domain",
            "sumble_url",
            "sumble_name_alternates",
            "sumble_url_alternates",
            "employee_count_int",
            "headquarters_country",
            *META_FIELDS,
        )
    }


def org_payload(org: dict) -> dict:
    return {
        "org_id": org.get("id"),
        "name": org.get("name") or "",
        "domain": norm_domain(org.get("url") or ""),
        "sumble_url": org.get("sumble_url")
        or (f"https://sumble.com/org/{org.get('slug')}" if org.get("slug") else ""),
        "employee_count_int": org.get("employee_count_int")
        if "employee_count_int" in org
        else sumble_v6.exact_employee_count(org),
        "headquarters_country": org.get("headquarters_country") or "",
    }


def ancestor_chain(
    org_id: int, org_attrs: dict[int, dict], parent_orgs: dict[int, dict]
) -> list[int]:
    """Org ids strictly above `org_id`, nearest first, cycle-safe."""
    chain: list[int] = []
    seen = {org_id}
    cur = org_id
    for _ in range(MAX_ANCESTOR_DEPTH):
        attrs = org_attrs.get(cur) or parent_orgs.get(cur)
        if not attrs:
            break
        pid = attrs.get("parent_id")
        pid = int(pid) if pid else None
        if not pid or pid in seen:
            break
        chain.append(pid)
        seen.add(pid)
        cur = pid
    return chain


def find_parent_sub(
    rows: list[dict],
    org_attrs: dict[int, dict],
    parent_orgs: dict[int, dict],
) -> tuple[list[dict], list[dict]]:
    org_to_rows: dict[int, list[dict]] = {}
    crm_id_to_row: dict[str, dict] = {}
    for r in rows:
        if r["org_id"]:
            org_to_rows.setdefault(r["org_id"], []).append(r)
        if r["crm_account_id"]:
            crm_id_to_row.setdefault(r["crm_account_id"], r)

    def org_name(oid: int) -> str:
        attrs = org_attrs.get(oid) or parent_orgs.get(oid) or {}
        return attrs.get("name") or f"org {oid}"

    findings: list[dict] = []
    not_in_crm: dict[int, list[dict]] = {}
    for r in rows:
        if not r["org_id"]:
            continue
        chain = ancestor_chain(r["org_id"], org_attrs, parent_orgs)
        if not chain:
            continue
        chain_names = [org_name(r["org_id"])] + [org_name(o) for o in chain]

        # Is the CRM's current parent already consistent with the Sumble chain?
        current = crm_id_to_row.get(r["parent_crm_id"]) if r["parent_crm_id"] else None
        if current and current["org_id"] in set(chain) | {r["org_id"]}:
            continue

        suggestion = None
        hop = 0
        for h, ancestor in enumerate(chain, start=1):
            candidates = [
                c
                for c in org_to_rows.get(ancestor, [])
                if c["crm_account_id"] != r["crm_account_id"]
            ]
            if candidates:
                suggestion = sorted(candidates, key=lambda c: c["crm_account_id"])[0]
                hop = h
                break

        if suggestion is None:
            top = chain[-1]
            attrs = org_attrs.get(top) or parent_orgs.get(top)
            if attrs and not r["parent_crm_id"]:
                not_in_crm.setdefault(top, []).append(r)
            continue

        if current is None and r["parent_crm_id"]:
            note = "CRM parent id does not resolve to an account in the provided list."
        elif current is not None:
            note = (
                f"CRM parent is '{current['crm_name']}' but Sumble places this "
                f"account under '{suggestion['crm_name']}'."
            )
        else:
            note = ""
        findings.append(
            {
                "type": "parent_conflict" if current is not None else "missing_parent_link",
                "confidence": "medium"
                if (current is not None or hop > 1)
                else "high",
                "child": account_payload(r),
                "suggested_parent": account_payload(suggestion),
                "current_parent": account_payload(current) if current else None,
                "chain": chain_names[: hop + 1],
                "note": note,
            }
        )

    findings.sort(
        key=lambda f: (
            CONFIDENCE_ORDER[f["confidence"]],
            f["type"],
            f["child"]["crm_account_id"],
        )
    )
    for i, f in enumerate(findings):
        f["id"] = f"ps_{i + 1:04d}"

    grouped: list[dict] = []
    for top in sorted(not_in_crm, key=lambda o: (-len(not_in_crm[o]), o)):
        attrs = org_attrs.get(top) or parent_orgs.get(top) or {}
        grouped.append(
            {
                "parent_org": org_payload(attrs),
                "children": [
                    account_payload(c)
                    for c in sorted(not_in_crm[top], key=lambda c: c["crm_account_id"])
                ],
            }
        )
    for i, g in enumerate(grouped):
        g["id"] = f"px_{i + 1:04d}"
        g["type"] = "parent_not_in_crm"
        g["confidence"] = "info"
    return findings, grouped


def write_findings_csv(out_path: Path, findings: dict) -> None:
    cols = [
        "finding_id", "finding_type", "confidence", "dup_category", "evidence",
        "role",
        "crm_account_id", "crm_url", "crm_name", "crm_domain", "owner",
        "is_customer", "created_date", *COUNT_FIELDS, *META_FIELDS,
        "org_id", "sumble_name",
        "sumble_domain", "sumble_url", "sumble_name_alternates",
        "sumble_url_alternates", "employee_count_int",
        "headquarters_country", "note",
    ]
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()

        def emit(fid, ftype, conf, evidence, role, acct, note="", dup_category=""):
            w.writerow(
                {
                    "finding_id": fid,
                    "finding_type": ftype,
                    "confidence": conf,
                    "dup_category": dup_category,
                    "evidence": "|".join(evidence),
                    "role": role,
                    "note": note,
                    **{
                        k: "|".join(v) if isinstance(v := acct.get(k, ""), list) else v
                        for k in cols
                        if k in acct
                    },
                }
            )

        for d in findings["duplicates"]:
            for a in d["accounts"]:
                role = (
                    "survivor"
                    if a["crm_account_id"] == d["suggested_survivor_crm_id"]
                    else "merge_into_survivor"
                )
                emit(d["id"], "duplicate", d["confidence"], d["evidence"], role, a,
                     d["note"], d["category"])
        for p in findings["parent_sub"]:
            emit(p["id"], p["type"], p["confidence"], [], "child", p["child"],
                 p["note"])
            emit(p["id"], p["type"], p["confidence"], [], "suggested_parent",
                 p["suggested_parent"])
            if p["current_parent"]:
                emit(p["id"], p["type"], p["confidence"], [], "current_parent",
                     p["current_parent"])
        for g in findings["parent_not_in_crm"]:
            parent = {
                "crm_account_id": "",
                "crm_name": g["parent_org"]["name"],
                "crm_domain": g["parent_org"]["domain"],
                "org_id": g["parent_org"]["org_id"],
                "sumble_name": g["parent_org"]["name"],
                "sumble_url": g["parent_org"]["sumble_url"],
                "employee_count_int": g["parent_org"]["employee_count_int"],
                "headquarters_country": g["parent_org"]["headquarters_country"],
            }
            emit(g["id"], "parent_not_in_crm", "info", [], "suggested_new_parent",
                 parent)
            for c in g["children"]:
                emit(g["id"], "parent_not_in_crm", "info", [], "child", c)
        for u in findings["unmatched"]:
            emit("", "unmatched", "info", [], "account", u)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build CRM-cleaning findings.")
    ap.add_argument("--raw", default="../_raw")
    args = ap.parse_args()

    raw = Path(args.raw).resolve()
    output_root = raw.parent
    config = {}
    cfg_path = raw / "config.json"
    if cfg_path.exists():
        config = json.loads(cfg_path.read_text())
    checks = config.get("checks") or ["duplicates", "parent_sub"]

    index = json.loads((raw / "fetch_index.json").read_text())
    org_attrs = load_org_attrs(raw)
    parent_orgs_raw = {}
    pp = raw / "parent_orgs.json"
    if pp.exists():
        parent_orgs_raw = {int(k): v for k, v in json.loads(pp.read_text()).items()}

    crm_url_template = (config.get("crm_url_template") or "").strip()
    org_alternates = load_org_alternates(raw)
    account_counts = load_account_counts(raw)
    accounts_meta = load_accounts_meta(raw)
    rows = build_rows(
        index,
        org_attrs,
        accounts_meta,
        crm_url_template,
        org_alternates,
        account_counts,
    )
    matched = [r for r in rows if r["org_id"]]
    unmatched = [r for r in rows if not r["org_id"]]

    duplicates = find_duplicates(rows) if "duplicates" in checks else []
    parent_sub, parent_not_in_crm = (
        find_parent_sub(rows, org_attrs, parent_orgs_raw)
        if "parent_sub" in checks
        else ([], [])
    )
    for g in parent_not_in_crm:
        alt = org_alternates.get(g["parent_org"]["org_id"] or 0) or {}
        g["parent_org"]["name_alternates"] = alt.get("name_alternates") or []
        g["parent_org"]["url_alternates"] = alt.get("url_alternates") or []

    findings = {
        "meta": {
            "company": config.get("company", ""),
            "checks": checks,
            "has_crm_counts": bool(account_counts),
            "has_crm_meta": bool(accounts_meta),
            "accounts_total": len(rows),
            "accounts_matched": len(matched),
            "accounts_unmatched": len(unmatched),
            "duplicate_clusters": len(duplicates),
            "duplicate_accounts": sum(len(d["accounts"]) for d in duplicates),
            "duplicate_categories": {
                c: sum(1 for d in duplicates if d["category"] == c)
                for c in DUP_CATEGORIES
            },
            "parent_sub_findings": len(parent_sub),
            "parents_not_in_crm": len(parent_not_in_crm),
        },
        "duplicates": duplicates,
        "parent_sub": parent_sub,
        "parent_not_in_crm": parent_not_in_crm,
        "unmatched": [account_payload(r) for r in unmatched],
    }
    (output_root / "findings.json").write_text(json.dumps(findings, indent=2))
    write_findings_csv(output_root / "findings.csv", findings)

    m = findings["meta"]
    print(
        f"[analyze] {m['accounts_total']} accounts ({m['accounts_matched']} matched): "
        f"{m['duplicate_clusters']} duplicate clusters covering "
        f"{m['duplicate_accounts']} accounts, {m['parent_sub_findings']} "
        f"parent/subsidiary findings, {m['parents_not_in_crm']} parent orgs "
        f"missing from the CRM, {m['accounts_unmatched']} unmatched."
    )
    print(f"[analyze] wrote {output_root / 'findings.json'} and findings.csv")


if __name__ == "__main__":
    main()
