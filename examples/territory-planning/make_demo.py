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

ENTERPRISE_MIN = 150  # sales_people >= this -> Enterprise
COMPANY = {"name": "Northwind", "url": "northwind.example", "folder_slug": "northwind"}
COMPANY_DOMAIN = "northwind.example"

# Target accounts per rep, by segment — the "Target accounts per rep" the
# Calibrate panel shows. The quotas below are built to land every book inside
# +-40% of these, so the target is a number a reviewer can actually hold the
# demo to. The Enterprise line sits at 150 sales people (not 500) so the
# Enterprise pool is deep enough for 10 reps to carry ~50 accounts each.
SEGMENT_CAPACITY = {"commercial": 150, "enterprise": 50}

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
    # Dedupe on org_id: the source carries a handful of repeats (IBM x3, Oracle,
    # …) and crm_account_id is derived from org_id, so a repeat would emit two
    # CRM records for one account — a duplicate the pipeline has no way to tell
    # from the deliberate double-allocations below.
    accts, seen_oids = [], set()
    for r in src:
        oid = r.get("org_id")
        if not oid or not r.get("url"):
            continue
        if str(r.get("account_category")) == "whitespace" or oid in seen_oids:
            continue
        seen_oids.add(oid)
        accts.append(r)

    reps_seg = {n: "enterprise" for n in ENTERPRISE_REPS}
    reps_seg.update({n: "commercial" for n in COMMERCIAL_REPS})

    # Per-rep book quotas. Every rep gets EXACTLY this many accounts, so each
    # book lands inside the +-40% band around its segment target (Enterprise
    # 30-70, Commercial 90-210) instead of falling out of a weighted lottery,
    # where the tail reps ended up at a third of target. The spread within the
    # band is what gives the heatmaps something to show.
    ENT_QUOTA = {
        "Chen Wei": 66,       # biggest book in the segment - and barely worked
        "Dev Ramesh": 47,
        "Avery Brooks": 43,
        "Sofia Romano": 40,
        "Marcus Bell": 38,
        "Fatima Khan": 36,
        "Yuki Tanaka": 34,
        "Liam Novak": 32,
        "Rosa Alvarez": 31,
        "Grace Okafor": 30,   # ramping - at the floor of the band
    }
    COM_QUOTA = {
        "Alex Rivera": 180,   # the star: biggest book, and the best worked
        "Jordan Lee": 128,
        "Sam Patel": 116,
        "Priya Nair": 108,
        "Diego Castro": 100,
        "Maya Cohen": 96,
        "Noah Schmidt": 92,
        "Aisha Bello": 92,
        "Ravi Menon": 91,
        "Elena Petrova": 90,  # near the floor
    }
    # Books are filled strongest-account-first, so a bias > 1 pulls the segment's
    # best accounts onto that rep. This is what separates Capture (share of the
    # best business) from raw book size — without it the two say the same thing.
    STAR_BIAS = {"Chen Wei": 2.0, "Alex Rivera": 2.0, "Dev Ramesh": 1.3}

    MISFIT_RATE = 0.04  # owned accounts handed to a rep in the OTHER segment
    KEEP_PROB = {"enterprise": 0.94, "commercial": 0.80}
    other = {"enterprise": "commercial", "commercial": "enterprise"}

    # ---- score.csv + ownership.csv ------------------------------------------
    # Pass 1: score every account and decide which ones are owned at all, and by
    # which rep POOL. Landing in the other segment's pool is the Wrong segment
    # flag — the balancer proposes handing those back.
    scored = []  # (oid, src_row, seg, score, sales_people, employees)
    pool: dict[str, list[tuple[str, float]]] = {"enterprise": [], "commercial": []}
    for r in accts:
        oid = r["org_id"]
        sp = num(r.get("sales_people"))
        emp = num(r.get("employee_count_int"))
        seg = "enterprise" if sp >= ENTERPRISE_MIN else "commercial"

        # Synthetic ICP score: size-correlated + deterministic variety, 3-98.
        base = 30 + 9 * math.log10(sp + 1) + 5 * math.log10(emp + 1)
        score = max(3.0, min(98.0, base + 22 * h01("score", oid) - 6))
        scored.append((oid, r, seg, score, sp, emp))

        if h01("own", oid) < KEEP_PROB[seg]:
            target = other[seg] if h01("misfit", oid) < MISFIT_RATE else seg
            pool[target].append((oid, score))

    # Pass 2: fill each rep's quota from their pool, strongest account first.
    # Each account goes to a rep drawn in proportion to their REMAINING quota
    # (times their star bias) — a lottery, not "whoever has most quota left",
    # which would hand the biggest book the entire top of the segment in one
    # block and leave every other rep at ~0% Capture. Proportional draw means a
    # rep's share of every score band tracks their book size, and the bias is
    # what tilts the best accounts onto the stars. Quotas are met exactly;
    # whatever the reps don't take (the weakest of the pool) stays unallocated.
    owner_of: dict[str, str] = {}
    for seg_key, quota in (("enterprise", ENT_QUOTA), ("commercial", COM_QUOTA)):
        left = dict(quota)
        for oid, _ in sorted(pool[seg_key], key=lambda t: (-t[1], t[0])):
            live = [
                (n, k * STAR_BIAS.get(n, 1.0)) for n, k in left.items() if k > 0
            ]
            if not live:
                break  # every quota filled - the rest of the pool goes unowned
            x = h01("assign", oid) * sum(w for _, w in live)
            acc, best = 0.0, live[-1][0]
            for n, w in live:
                acc += w
                if x <= acc:
                    best = n
                    break
            owner_of[oid] = best
            left[best] -= 1
        short = {n: k for n, k in left.items() if k > 0}
        if short:
            raise SystemExit(
                f"[demo] the {seg_key} pool cannot fill its quotas - short by {short}. "
                f"Raise KEEP_PROB['{seg_key}'] or lower the quotas."
            )

    score_rows, own_rows = [], []
    for oid, r, seg, score, sp, emp in scored:
        owner = owner_of.get(oid, "")
        owner_email = email(owner) if owner else ""
        is_customer = 1 if (owner and h01("cust", oid) < 0.06) else 0

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

    # Guardrail: the whole point of the quotas. If a book drifts outside +-40%
    # of its segment target, "Target accounts per rep" in the Calibrate panel is
    # describing something the demo data doesn't do — fail the build instead of
    # shipping it.
    books: dict[str, int] = {}
    for o in own_rows:
        if o["owner"]:
            books[o["owner"]] = books.get(o["owner"], 0) + 1
    out_of_band = [
        f"{n} ({seg}): {books.get(n, 0)} vs target {SEGMENT_CAPACITY[seg]}"
        for n, seg in reps_seg.items()
        if not (
            0.6 * SEGMENT_CAPACITY[seg] <= books.get(n, 0) <= 1.4 * SEGMENT_CAPACITY[seg]
        )
    ]
    if out_of_band:
        raise SystemExit(
            "[demo] book sizes outside +-40% of target:\n  " + "\n  ".join(out_of_band)
        )

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
    rep_effort["Dev Ramesh"] = 0.92  # works his whole top tier - Chen Wei's foil
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
                "default_capacity": SEGMENT_CAPACITY["commercial"],
            },
            {
                "key": "enterprise",
                "label": "Enterprise",
                "order": 2,
                "default_capacity": SEGMENT_CAPACITY["enterprise"],
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
    for seg in ("enterprise", "commercial"):
        sizes = sorted(
            (books[n] for n in reps_seg if reps_seg[n] == seg), reverse=True
        )
        cap = SEGMENT_CAPACITY[seg]
        pct = [f"{100 * b // cap}%" for b in sizes]
        print(f"[demo] {seg} books (target {cap}): {sizes} -> {' '.join(pct)}")


if __name__ == "__main__":
    main()
