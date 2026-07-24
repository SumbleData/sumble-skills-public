"""Generate fictitious territory-planning demo inputs (then run the pipeline).

Accounts (real public companies + demo signals) come from the account-scoring
example's data.csv; REPS and ACTIVITY are fictitious, so nothing here exposes a
real customer's book. Deterministic (hash-based pseudo-random, no RNG), so the
demo rebuilds byte-identically.

Writes into <out>/_raw/: score.csv, ownership.csv, reps.csv, activity/meetings.csv,
spec.json — the same inputs the real pipeline consumes. `build.sh` then copies the
stdlib app from the skill template and runs the pipeline over these.

Usage:  python3 make_demo.py --out /abs/demo/dir --data /abs/account-scoring/data.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

ENTERPRISE_MIN = 500  # sales_people >= this -> Enterprise
COMPANY = {"name": "Northwind", "url": "northwind.example", "folder_slug": "northwind"}
COMPANY_DOMAIN = "northwind.example"

ENTERPRISE_REPS = [
    "Avery Brooks",
    "Chen Wei",
    "Fatima Khan",
    "Marcus Bell",
    "Sofia Romano",
    "Dev Ramesh",
    "Grace Okafor",
    "Liam Novak",
    "Yuki Tanaka",
    "Rosa Alvarez",
]
COMMERCIAL_REPS = [
    "Alex Rivera",
    "Jordan Lee",
    "Sam Patel",
    "Priya Nair",
    "Diego Castro",
    "Maya Cohen",
    "Noah Schmidt",
    "Aisha Bello",
    "Ravi Menon",
    "Elena Petrova",
]


def h01(*parts: object) -> float:
    """Deterministic pseudo-random in [0,1) from a salt tuple."""
    key = ":".join(str(p) for p in parts)
    return int(hashlib.md5(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def num(v: object) -> float:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return 0.0


def email(name: str) -> str:
    return name.lower().replace(" ", ".") + "@" + COMPANY_DOMAIN


def write_csv(path: Path, rows: list[dict], cols: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--data", required=True)
    args = ap.parse_args()
    out = Path(args.out).expanduser().resolve()
    raw = out / "_raw"

    src = list(csv.DictReader(open(args.data, encoding="utf-8")))
    # Keep real accounts with an org id, a domain, and a size signal; drop the
    # source's whitespace rows (net-new, not owned) — the demo is about a book.
    accts = [
        r
        for r in src
        if r.get("org_id")
        and r.get("url")
        and str(r.get("account_category")) != "whitespace"
    ]

    reps_seg = {n: "enterprise" for n in ENTERPRISE_REPS}
    reps_seg.update({n: "commercial" for n in COMMERCIAL_REPS})

    # Book-share weights per rep: stars carry bigger, stronger books; ramping
    # reps carry little. This drives the Capture spread, and strong accounts skew
    # toward the heavier reps (concentration), so the metrics tell a story.
    # Enterprise is a small segment (few hundred accounts / 10 reps), so keep its
    # weights close together — otherwise the tail reps end up with 1-2 accounts.
    ent_weight = dict(
        zip(ENTERPRISE_REPS, [1.8, 1.6, 1.4, 1.3, 1.2, 1.1, 1.0, 0.95, 0.9, 0.85])
    )
    com_weight = dict(
        zip(COMMERCIAL_REPS, [2.2, 1.9, 1.6, 1.4, 1.2, 1.0, 0.9, 0.8, 0.7, 0.6])
    )

    def pick(weights: dict, oid: str, score: float) -> str:
        items = [(n, w * (1 + (w - 1) * (score / 100.0) * 0.4)) for n, w in weights.items()]
        total = sum(w for _, w in items)
        x = h01("pick", oid) * total
        acc = 0.0
        for n, w in items:
            acc += w
            if x <= acc:
                return n
        return items[-1][0]

    # ---- score.csv + ownership.csv ------------------------------------------
    score_rows, own_rows = [], []
    for r in accts:
        oid = r["org_id"]
        sp = num(r.get("sales_people"))
        emp = num(r.get("employee_count_int"))
        seg = "enterprise" if sp >= ENTERPRISE_MIN else "commercial"

        # Synthetic ICP score: size-correlated + deterministic variety, 3-98.
        base = 30 + 9 * math.log10(sp + 1) + 5 * math.log10(emp + 1)
        score = max(3.0, min(98.0, base + 22 * h01("score", oid) - 6))

        # Ownership: enterprise reps hold most enterprise accounts; commercial
        # reps a slice of the much larger commercial pool; the rest unallocated.
        weights = ent_weight if seg == "enterprise" else com_weight
        keep_prob = 0.94 if seg == "enterprise" else 0.42
        owner, owner_email, is_customer = "", "", 0
        if h01("own", oid) < keep_prob:
            owner = pick(weights, oid, score)
            # ~5% misfit: hand it to a rep from the OTHER segment.
            if h01("misfit", oid) < 0.05:
                owner = pick(com_weight if seg == "enterprise" else ent_weight, oid, score)
            owner_email = email(owner)
            is_customer = 1 if h01("cust", oid) < 0.06 else 0

        category = "customer" if is_customer else ("allocated" if owner else "unallocated")
        dom = str(r["url"]).strip().lower()
        crm_id = f"NW{int(oid):07d}"
        slug = r.get("slug") or ""
        score_rows.append(
            {
                "org_id": oid,
                "name": r.get("name") or "",
                "url": dom,
                "account_category": category,
                "score": round(score, 2),
                "sales_people": int(sp),
                "employee_count_int": int(emp),
                "sumble_url": f"https://sumble.com/orgs/{slug}" if slug else "",
                "crm_account_id": crm_id,
            }
        )
        own_rows.append(
            {
                "crm_account_id": crm_id,
                "name": r.get("name") or "",
                "domain": dom,
                "owner": owner,
                "owner_email": owner_email,
                "owner_is_queue": 0,
                "is_customer": is_customer,
            }
        )

    # A couple of double-allocations: same org under a second rep.
    dupes = [
        r for r in own_rows if r["owner"] and reps_seg.get(r["owner"]) == "enterprise"
    ][:3]
    extra_owner = {0: "Marcus Bell", 1: "Sofia Romano", 2: "Chen Wei"}
    for i, base in enumerate(dupes):
        if base["owner"] == extra_owner[i]:
            continue
        d = dict(base)
        d["crm_account_id"] = base["crm_account_id"] + "B"
        d["owner"] = extra_owner[i]
        d["owner_email"] = email(extra_owner[i])
        own_rows.append(d)

    write_csv(
        raw / "score.csv",
        score_rows,
        [
            "org_id",
            "name",
            "url",
            "account_category",
            "score",
            "sales_people",
            "employee_count_int",
            "sumble_url",
            "crm_account_id",
        ],
    )
    write_csv(
        raw / "ownership.csv",
        own_rows,
        [
            "crm_account_id",
            "name",
            "domain",
            "owner",
            "owner_email",
            "owner_is_queue",
            "is_customer",
        ],
    )

    # ---- reps.csv -----------------------------------------------------------
    reps = [
        {
            "name": n,
            "email": email(n),
            "segment": s,
            "is_rep": 1,
            "capacity": "",
            "in_balance": 1,
        }
        for n, s in reps_seg.items()
    ]
    write_csv(
        raw / "reps.csv",
        reps,
        ["name", "email", "segment", "is_rep", "capacity", "in_balance"],
    )

    # ---- activity/meetings.csv ----------------------------------------------
    # Reps work their stronger accounts more; per-rep effort varies so coverage
    # (Activation) spreads across the team, and a few barely work their books.
    score_by_crm = {s["crm_account_id"]: s["score"] for s in score_rows}
    rep_effort = {n: 0.28 + 0.5 * h01("effort", n) for n in reps_seg}
    rep_effort["Grace Okafor"] = 0.03  # ramping enterprise rep - near-idle book
    rep_effort["Chen Wei"] = 0.10  # big book, barely worked (sitting on value)
    rep_effort["Alex Rivera"] = 0.80  # star commercial rep - high activation
    events = []
    for o in own_rows:
        if not o["owner"]:
            continue
        s = score_by_crm.get(o["crm_account_id"], 0)
        p = rep_effort[o["owner"]] * (0.4 + 0.9 * (s / 100.0))  # stronger = likelier
        if h01("work", o["crm_account_id"], o["owner"]) < p:
            n_meet = 1 + int(h01("nm", o["crm_account_id"]) * 3)
            for k in range(n_meet):
                day = 1 + int(h01("day", o["crm_account_id"], k) * 89)
                mon = 6 if day <= 30 else 7
                dom_day = ((day - 1) % 30) + 1
                events.append(
                    {
                        "source": "google_calendar",
                        "rep_email": o["owner_email"],
                        "account_domain": o["domain"],
                        "kind": "meeting",
                        "ts": f"2026-{mon:02d}-{dom_day:02d}",
                    }
                )
    write_csv(
        raw / "activity" / "meetings.csv",
        events,
        ["source", "rep_email", "account_domain", "kind", "ts"],
    )

    # ---- spec.json ----------------------------------------------------------
    spec = {
        "schema_version": 1,
        "company": COMPANY,
        "score_source": {
            "kind": "custom",
            "path": str(raw / "score.csv"),
            "note": "Fictitious demo: real public companies + synthetic scores.",
        },
        "segments": [
            {
                "key": "commercial",
                "label": "Commercial",
                "order": 1,
                "default_capacity": 150,
            },
            {
                "key": "enterprise",
                "label": "Enterprise",
                "order": 2,
                "default_capacity": 50,
            },
        ],
        "boundary": {
            "metric": "jf_people:Sales",
            "column": "sales_people",
            "label": "Sales headcount",
            "thresholds": [{"segment": "enterprise", "min": ENTERPRISE_MIN}],
        },
        "activity": {
            "window_days": 90,
            "sources": ["google_calendar"],
            "company_domain": COMPANY_DOMAIN,
        },
        "whitespace_top_n": 0,
        "strong_cutoff": 500,
        "tier_decile_weight": 2,
    }
    with open(raw / "spec.json", "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2)

    cats: dict[str, int] = {}
    for s in score_rows:
        cats[s["account_category"]] = cats.get(s["account_category"], 0) + 1
    owned = sum(1 for o in own_rows if o["owner"])
    na, nm = len(score_rows), len(events)
    print(f"[demo] accounts: {na:,}   owned: {owned:,}   meetings: {nm:,}")
    print(f"[demo] categories: {cats}")
    ne, nc = len(ENTERPRISE_REPS), len(COMMERCIAL_REPS)
    print(f"[demo] reps: {ne} enterprise + {nc} commercial")


if __name__ == "__main__":
    main()
