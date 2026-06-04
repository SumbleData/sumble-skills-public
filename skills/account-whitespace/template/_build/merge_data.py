"""Stage 2/3 — merge `POST /v6/organizations` responses into data.csv + audit.

Reads (in `../_raw/`):
- spec.json
- responses/resp_*.json          (candidate pool, filter mode)
- customer_responses/resp_*.json  (closed-won customers, for calibration)
- crm_matches.json               ([{org_id, name}] — exclusion + subsidiary parents)

Writes:
- ../data.csv                    (candidate rows only; CRM accounts excluded)
- ../_raw/_customer_calibration.csv
- ../_raw/_calibration_audit.json

No SQL. Firmographics + signals come from the unified endpoint via
sumble_v6.build_data_row(); the universe hard-filters (min employees, HQ
whitelist, excluded tags) are applied here post-fetch.

POLICY CONSTANTS (unchanged from the SQL pipeline):
- TAG_LIFT_GOLD_MIN = 3, TAG_LIFT_UNIVERSE_MIN = 5, ZERO_AND_HIGH_BASELINE = 0.10
- BOOST_SCALE = 30, BOOST_CAP = 50, PENALTY_SCALE = 50, PENALTY_CAP = 50
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import sumble_v6

TAG_LIFT_GOLD_MIN = 3
TAG_LIFT_UNIVERSE_MIN = 5
ZERO_AND_HIGH_BASELINE = 0.10
BOOST_SCALE = 30
BOOST_CAP = 50
PENALTY_SCALE = 50
PENALTY_CAP = 50
NEUTRAL_LIFT_LOW = 0.8
NEUTRAL_LIFT_HIGH = 1.2

CALIBRATE_ATTRS = [
    "is_b2b",
    "is_b2c",
    "is_digital_native",
    "is_ai_native",
    "is_it_services",
    "is_professional_services",
]


def load_responses(path: Path) -> list[dict]:
    orgs: list[dict] = []
    for p in sorted(path.glob("resp_*.json")):
        orgs.extend(json.loads(p.read_text()).get("organizations") or [])
    return orgs


def calibrate(universe: list[dict], gold: list[dict]) -> tuple[dict, list[dict]]:
    audit: dict[str, dict] = {}
    multipliers_defaults: list[dict] = []
    n_universe = len(universe)
    n_gold = len(gold)
    for attr in CALIBRATE_ATTRS:
        universe_pos = sum(r[attr] for r in universe)
        gold_pos = sum(r[attr] for r in gold)
        universe_rate = universe_pos / n_universe if n_universe else 0.0
        gold_rate = gold_pos / n_gold if n_gold else 0.0
        lift = gold_rate / universe_rate if universe_rate > 0 else None

        direction: str | None = None
        pct = 0
        note = ""
        if universe_pos < TAG_LIFT_UNIVERSE_MIN:
            note = f"universe positives <{TAG_LIFT_UNIVERSE_MIN} — neutral"
        elif gold_pos == 0 and universe_rate >= ZERO_AND_HIGH_BASELINE:
            pct = PENALTY_CAP
            direction = "penalty"
            note = f"0 customers in attr, baseline {universe_rate:.0%} — strong penalty"
        elif gold_pos < TAG_LIFT_GOLD_MIN:
            note = f"too few customer positives ({gold_pos}<{TAG_LIFT_GOLD_MIN}) — neutral"
        elif lift is None:
            note = "universe rate is zero — neutral"
        elif lift >= NEUTRAL_LIFT_HIGH:
            pct = min(BOOST_CAP, round((lift - 1) * BOOST_SCALE))
            direction = "boost"
        elif lift <= NEUTRAL_LIFT_LOW:
            pct = min(PENALTY_CAP, round((1 - lift) * PENALTY_SCALE))
            direction = "penalty"
        else:
            note = f"lift {lift:.2f} in neutral band — neutral"

        if direction:
            tag_slug = (
                attr[3:] if attr.startswith("is_") and attr != "is_ai_native" else attr
            )
            multipliers_defaults.append(
                {"tag": tag_slug, "pct": pct, "direction": direction}
            )

        audit[attr] = {
            "universe_positives": universe_pos,
            "universe_n": n_universe,
            "universe_rate": round(universe_rate, 4),
            "gold_positives": gold_pos,
            "gold_n": n_gold,
            "gold_rate": round(gold_rate, 4),
            "lift": round(lift, 3) if lift is not None else None,
            "direction": direction,
            "pct": pct,
            "note": note,
        }
    return audit, multipliers_defaults


def passes_filters(row: dict, filters: dict) -> bool:
    if row["employee_count_int"] < int(filters.get("min_employees", 0) or 0):
        return False
    hq_whitelist = filters.get("hq_country_whitelist") or []
    if hq_whitelist and row["headquarters_country"] not in hq_whitelist:
        return False
    if (
        filters.get("exclude_professional_services_industry")
        and row["is_professional_services"]
    ):
        return False
    excluded = set(filters.get("hard_exclude_tags") or [])
    if excluded & {t for t in row["tags"].split("|") if t}:
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge endpoint responses into data.csv.")
    parser.add_argument("--raw", default="../_raw")
    args = parser.parse_args()
    raw = Path(args.raw).resolve()
    output_root = raw.parent
    spec = json.loads((raw / "spec.json").read_text())
    plan = sumble_v6.entity_plan(spec)
    filters = spec.get("universe_filters", {})

    crm_matches: list[dict] = []
    crm_path = raw / "crm_matches.json"
    if crm_path.exists():
        crm_matches = json.loads(crm_path.read_text())
    crm_ids = {int(m["org_id"]) for m in crm_matches}
    crm_parents = {int(m["org_id"]): m.get("name", "") for m in crm_matches}

    candidate_orgs = load_responses(raw / "responses")
    if not candidate_orgs:
        raise SystemExit("_raw/responses/resp_*.json missing — run fetch_data.py first.")
    customer_orgs = load_responses(raw / "customer_responses")

    candidate_rows: list[dict] = []
    for resp_row in candidate_orgs:
        row = sumble_v6.build_data_row(resp_row, spec, plan)
        if row is None or row["org_id"] in crm_ids:
            continue  # unmatched, or already a CRM account (not whitespace)
        if not passes_filters(row, filters):
            continue
        parent_id = (resp_row.get("attributes") or {}).get("parent_id")
        if parent_id and int(parent_id) in crm_ids:
            row["list_type"] = "crm_subsidiary"
            row["crm_parent_name"] = crm_parents.get(int(parent_id), "")
        else:
            row["list_type"] = "whitespace"
            row["crm_parent_name"] = ""
        row["crm_account_id"] = ""
        row["is_icp_gold"] = 0
        candidate_rows.append(row)

    customer_rows: list[dict] = []
    for resp_row in customer_orgs:
        row = sumble_v6.build_data_row(resp_row, spec, plan)
        if row is None:
            continue
        row["list_type"] = "calibration_customer"
        row["crm_parent_name"] = ""
        row["crm_account_id"] = ""
        row["is_icp_gold"] = 1
        customer_rows.append(row)

    if not candidate_rows:
        raise SystemExit("No candidate rows survived matching/filters — nothing to write.")

    field_order = list(candidate_rows[0].keys())

    audit, multipliers_defaults = calibrate(candidate_rows + customer_rows, customer_rows)
    (raw / "_calibration_audit.json").write_text(
        json.dumps({"attrs": audit, "multipliers_defaults": multipliers_defaults}, indent=2)
    )
    with (raw / "_customer_calibration.csv").open("w", newline="") as f_out:
        w = csv.DictWriter(f_out, fieldnames=field_order)
        w.writeheader()
        w.writerows(customer_rows)

    data_csv = output_root / "data.csv"
    with data_csv.open("w", newline="") as f_out:
        w = csv.DictWriter(f_out, fieldnames=field_order)
        w.writeheader()
        w.writerows(candidate_rows)

    list_counts = Counter(r["list_type"] for r in candidate_rows)
    print(
        f"Built {len(candidate_rows)} candidate + {len(customer_rows)} customer rows. "
        f"list_type: {dict(list_counts)}. "
        f"Calibration emitted {len(multipliers_defaults)} multipliers."
    )
    print(f"Wrote {data_csv}")


if __name__ == "__main__":
    main()
