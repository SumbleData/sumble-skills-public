"""Stage 2/3 — merge `POST /v6/organizations` responses into data.csv + audit.

Reads (in `../_raw/`):
- spec.json
- responses/resp_*.json        (raw endpoint responses from fetch_data.py)
- fetch_index.json             (per-org {crm_account_id, is_gold}, list mode)

Writes:
- ../data.csv                  (one row per matched org, is_icp_gold flagged)
- ../_raw/_calibration_audit.json   (per-attribute tag-lift + multipliers_defaults)

No SQL anywhere. Every Sumble column comes from the unified endpoint via the
entity plan in sumble_v6.entity_plan(); employee_count_int is the endpoint's
exact headcount attribute, falling back to the employee_count band midpoint
only when the exact value is absent.

POLICY CONSTANTS (unchanged from the SQL pipeline):
- TAG_LIFT_GOLD_MIN = 3, TAG_LIFT_UNIVERSE_MIN = 5
- ZERO_AND_HIGH_BASELINE = 0.10
- BOOST_SCALE = 30, BOOST_CAP = 50, PENALTY_SCALE = 50, PENALTY_CAP = 50
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import sumble_v6

# --- Policy constants ---
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


def load_responses(raw: Path) -> list[dict]:
    """Flatten every response's `organizations` in fetch order."""
    orgs: list[dict] = []
    for path in sorted((raw / "responses").glob("resp_*.json")):
        payload = json.loads(path.read_text())
        orgs.extend(payload.get("organizations") or [])
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
            note = f"0 gold in attr, baseline {universe_rate:.0%} — strong penalty"
        elif gold_pos < TAG_LIFT_GOLD_MIN:
            note = f"too few gold positives ({gold_pos}<{TAG_LIFT_GOLD_MIN}) — neutral"
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge endpoint responses into data.csv.")
    parser.add_argument("--raw", default="../_raw")
    args = parser.parse_args()
    raw = Path(args.raw).resolve()
    output_root = raw.parent
    spec = json.loads((raw / "spec.json").read_text())

    plan = sumble_v6.entity_plan(spec)

    resp_orgs = load_responses(raw)
    if not resp_orgs:
        raise SystemExit("_raw/responses/resp_*.json missing — run fetch_data.py first.")

    index_path = raw / "fetch_index.json"
    fetch_index: list[dict] = (
        json.loads(index_path.read_text()) if index_path.exists() else []
    )

    def build_row(resp_row: dict, meta: dict) -> dict | None:
        row = sumble_v6.build_data_row(resp_row, spec, plan)
        if row is None:
            return None  # unmatched input — no Sumble data to score
        row["crm_account_id"] = meta.get("crm_account_id") or ""
        # The CRM's own account name + url (from sample.csv), shown alongside the
        # Sumble-matched name/url so a mismatch is visible in the table.
        row["crm_account_name"] = meta.get("crm_account_name") or ""
        row["crm_url"] = meta.get("crm_url") or ""
        row["is_icp_gold"] = int(meta.get("is_gold") or 0)
        return row

    all_rows: list[dict] = []
    for i, resp_row in enumerate(resp_orgs):
        meta = fetch_index[i] if i < len(fetch_index) else {}
        built = build_row(resp_row, meta)
        if built is not None:
            all_rows.append(built)

    if not all_rows:
        raise SystemExit("No matched orgs in responses — nothing to write.")

    gold_rows = [r for r in all_rows if r["is_icp_gold"]]
    field_order = list(all_rows[0].keys())

    audit, multipliers_defaults = calibrate(all_rows, gold_rows)
    (raw / "_calibration_audit.json").write_text(
        json.dumps({"attrs": audit, "multipliers_defaults": multipliers_defaults}, indent=2)
    )

    data_csv = output_root / "data.csv"
    with data_csv.open("w", newline="") as f_out:
        w = csv.DictWriter(f_out, fieldnames=field_order)
        w.writeheader()
        w.writerows(all_rows)

    print(
        f"Built {len(all_rows)} matched rows ({len(gold_rows)} gold). "
        f"Calibration emitted {len(multipliers_defaults)} multipliers."
    )
    print(f"Wrote {data_csv}")


if __name__ == "__main__":
    main()
