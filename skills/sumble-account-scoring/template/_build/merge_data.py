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


def _has_tag(row: dict, tag: str) -> bool:
    return tag in {t for t in str(row.get("tags") or "").split("|") if t}


def passes_universe_filters(row: dict, filters: dict) -> bool:
    """Universe hard-filters applied post-fetch to WHITESPACE candidates only
    (never to the user's own CRM accounts): min employees, HQ-country whitelist,
    the professional-services switch (now tag-based — professional_services is
    a native Sumble org tag, so prefer listing it in hard_exclude_tags for
    free rank-time exclusion), and hard-exclude tags. The rank query already
    pushes most of these, but this is the guaranteed safety net."""
    if int(row.get("employee_count_int") or 0) < int(filters.get("min_employees", 0) or 0):
        return False
    max_emp = int(filters.get("max_employees", 0) or 0)
    if max_emp and int(row.get("employee_count_int") or 0) > max_emp:
        return False
    hq_whitelist = filters.get("hq_country_whitelist") or []
    if hq_whitelist and row.get("headquarters_country") not in hq_whitelist:
        return False
    if filters.get("exclude_professional_services_industry") and row.get(
        "is_professional_services"
    ):
        return False
    # Per-company industry hard-excludes (suggested from the gold set + knowledge,
    # NOT a fixed list) — matched case-insensitively against the org's industry.
    excl_industries = {str(s).strip().lower() for s in (filters.get("exclude_industries") or [])}
    if excl_industries and str(row.get("industry") or "").strip().lower() in excl_industries:
        return False
    excluded = set(filters.get("hard_exclude_tags") or [])
    if excluded & {t for t in str(row.get("tags") or "").split("|") if t}:
        return False
    return True


def calibrate_industries(
    all_rows: list[dict], gold_rows: list[dict], cap: int = 8
) -> tuple[dict, list[dict]]:
    """Gold-lift over the synthesized `industry__<slug>` tags (same policy
    constants as the attribute calibration), so whole industries earn a
    boost/penalty from the customer set. Capped to the `cap` strongest so the
    default multiplier list stays readable."""
    n_universe = len(all_rows)
    n_gold = len(gold_rows)
    industry_tags: set[str] = set()
    for r in all_rows:
        for t in str(r.get("tags") or "").split("|"):
            if t.startswith("industry__"):
                industry_tags.add(t)

    audit: dict[str, dict] = {}
    mults: list[dict] = []
    for tag in sorted(industry_tags):
        universe_pos = sum(1 for r in all_rows if _has_tag(r, tag))
        gold_pos = sum(1 for r in gold_rows if _has_tag(r, tag))
        universe_rate = universe_pos / n_universe if n_universe else 0.0
        gold_rate = gold_pos / n_gold if n_gold else 0.0
        lift = gold_rate / universe_rate if universe_rate > 0 else None

        direction: str | None = None
        pct = 0
        note = ""
        if universe_pos < TAG_LIFT_UNIVERSE_MIN:
            note = f"universe positives <{TAG_LIFT_UNIVERSE_MIN} — neutral"
        elif gold_pos == 0 and universe_rate >= ZERO_AND_HIGH_BASELINE:
            pct, direction = PENALTY_CAP, "penalty"
            note = f"0 customers in industry, baseline {universe_rate:.0%} — strong penalty"
        elif gold_pos < TAG_LIFT_GOLD_MIN:
            note = f"too few customer positives ({gold_pos}<{TAG_LIFT_GOLD_MIN}) — neutral"
        elif lift is None:
            note = "universe rate is zero — neutral"
        elif lift >= NEUTRAL_LIFT_HIGH:
            pct, direction = min(BOOST_CAP, round((lift - 1) * BOOST_SCALE)), "boost"
        elif lift <= NEUTRAL_LIFT_LOW:
            pct, direction = min(PENALTY_CAP, round((1 - lift) * PENALTY_SCALE)), "penalty"
        else:
            note = f"lift {lift:.2f} in neutral band — neutral"

        if direction:
            mults.append({"tag": tag, "pct": pct, "direction": direction})
        audit[tag] = {
            "universe_positives": universe_pos,
            "gold_positives": gold_pos,
            "universe_rate": round(universe_rate, 4),
            "gold_rate": round(gold_rate, 4),
            "lift": round(lift, 3) if lift is not None else None,
            "direction": direction,
            "pct": pct,
            "note": note,
        }
    mults.sort(key=lambda m: -m["pct"])
    return audit, mults[:cap]


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

    # CRM org ids (from the whitespace exclusion resolve) so a whitespace
    # candidate whose PARENT is a CRM account is relabelled `whitespace_subsidiary`
    # (land-and-expand) instead of plain `whitespace`. No separate tab — it's just
    # another filterable category in the one sheet.
    crm_ids: set[int] = set()
    crm_path = raw / "crm_matches.json"
    if crm_path.exists():
        crm_ids = {int(m["org_id"]) for m in json.loads(crm_path.read_text())}

    # Inverse linkage fallback: the endpoint omits `parent_id` on some rows
    # (observed: whitespace candidates), but CRM rows DO carry
    # `subsidiary_ids`. Collect every child id of a CRM org so a whitespace
    # candidate is recognised as a subsidiary from either direction.
    crm_child_ids: set[int] = set()
    if crm_ids:
        for resp_row in resp_orgs:
            attrs = resp_row.get("attributes") or {}
            oid = attrs.get("id")
            if oid is not None and int(oid) in crm_ids:
                for sid in attrs.get("subsidiary_ids") or []:
                    crm_child_ids.add(int(sid))

    def build_row(resp_row: dict, meta: dict) -> dict | None:
        row = sumble_v6.build_data_row(resp_row, spec, plan)
        if row is None:
            return None  # unmatched input — no Sumble data to score
        row["crm_account_id"] = meta.get("crm_account_id") or ""
        # The CRM's own account name + url (from sample.csv), shown alongside the
        # Sumble-matched name/url so a mismatch is visible in the table.
        row["crm_account_name"] = meta.get("crm_account_name") or ""
        row["crm_url"] = meta.get("crm_url") or ""
        # account_category is the single source of truth: customer / allocated /
        # unallocated / whitespace / whitespace_subsidiary ("" in pure Branch B).
        category = meta.get("account_category") or ""
        attrs = resp_row.get("attributes") or {}
        parent_id = attrs.get("parent_id")
        org_id = attrs.get("id")
        if category == "whitespace" and (
            (parent_id and int(parent_id) in crm_ids)
            or (org_id is not None and int(org_id) in crm_child_ids)
        ):
            category = "whitespace_subsidiary"
        row["account_category"] = category
        row["is_icp_gold"] = int(category == "customer" or bool(meta.get("is_gold")))
        return row

    universe_filters = spec.get("universe_filters", {})
    all_rows: list[dict] = []
    dropped = 0
    for i, resp_row in enumerate(resp_orgs):
        meta = fetch_index[i] if i < len(fetch_index) else {}
        built = build_row(resp_row, meta)
        if built is None:
            continue
        # Apply the universe hard-filters to WHITESPACE candidates only — never to
        # the user's own CRM accounts (they keep their seat regardless of size etc.).
        if built["account_category"] in ("whitespace", "whitespace_subsidiary"):
            if not passes_universe_filters(built, universe_filters):
                dropped += 1
                continue
        all_rows.append(built)
    if dropped:
        print(f"Dropped {dropped} whitespace candidate(s) on universe hard-filters.")

    if not all_rows:
        raise SystemExit("No matched orgs in responses — nothing to write.")

    gold_rows = [r for r in all_rows if r["is_icp_gold"]]
    field_order = list(all_rows[0].keys())

    # Calibration is purely over the org's Sumble tags (professional_services
    # is one of them, natively) — industries are not synthesized into tags, so
    # there's no per-industry gold-lift pass.
    audit, multipliers_defaults = calibrate(all_rows, gold_rows)
    (raw / "_calibration_audit.json").write_text(
        json.dumps(
            {
                "attrs": audit,
                "multipliers_defaults": multipliers_defaults,
            },
            indent=2,
        )
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
    # Concentration comes from the endpoint's native same-scope metrics, whose
    # denominator is recovered by inversion (sumble_v6.recover_total). Surface
    # the rows where it could not be recovered at all — their shares read 0.
    n_no_den = sum(
        1
        for r in all_rows
        if str(r.get("people_total_est", "0")) in ("0", "0.0")
        and str(r.get("jobs_total_est", "0")) in ("0", "0.0")
    )
    if n_no_den:
        pct = 100.0 * n_no_den / len(all_rows) if all_rows else 0.0
        print(
            f"No concentration denominator recoverable for {n_no_den} row(s) "
            f"({pct:.1f}%) — no measured persona/tech presence to invert; "
            "their _pct columns read 0."
        )
    print(f"Wrote {data_csv}")


if __name__ == "__main__":
    main()
