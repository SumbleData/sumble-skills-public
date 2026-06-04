"""Stage 3 — emit account-scoring-weights.json from spec.json + calibration.

Reads:
- ../_raw/spec.json
- ../_raw/_calibration_audit.json   (from merge_data.py — Step 4(a) tag-lift)
- ../data.csv                       (for p99 computation)

Writes:
- ../account-scoring-weights.json

Every Sumble-sourced signal's `source` block points at the unified endpoint
`POST https://api.sumble.com/v6/organizations` and carries the exact `select`
slice (entity selection or attribute) plus the field to `read`. A coding agent —
or the shipped score_accounts.py — can reproduce each column from the source
block alone. The entity selections are produced by sumble_v6.entity_plan(), the
same function fetch_data.py used to pull the data, so they cannot drift.

POLICY CONSTANTS (intentionally fixed):
- PERSONA_DECAY = 0.98, TECH_KEY_DECAY = 0.98, TECH_OTHER_DROP = 0.6
- SECTION_BLEND = {"acv": 60, "intent": 40} (fixed; Intent categories present
  whenever the spec has projects).
- CATEGORY_WEIGHTS_ACV / CATEGORY_WEIGHTS_INTENT below.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import sumble_v6

PERSONA_DECAY = 0.98
TECH_KEY_DECAY = 0.98
TECH_OTHER_DROP = 0.6

ENDPOINT = "POST https://api.sumble.com/v6/organizations"

SECTION_BLEND = {"acv": 60, "intent": 40}
CATEGORY_WEIGHTS_ACV = {
    "icp_persona_count": 39.0,
    "icp_persona_growth": 16.25,
    "icp_persona_concentration": 9.75,
    "relevant_tech_team_count": 24.5,
    "relevant_tech_team_concentration": 10.5,
}
CATEGORY_WEIGHTS_INTENT = {
    "intent_project_tech_count": 60.0,
    "intent_project_persona_count": 40.0,
}
# Funding categories (added only when spec["include_funding"]); section category
# weights are renormalised to sum to 100 afterwards. "Funding (size)" sits in
# ACV (total raised); "Funding momentum" sits in Intent (recency + last round).
FUNDING_CATEGORY_PCT = 12.0
FUNDING_INTENT_PCT = 30.0


def decay_weights(n: int, decay: float = PERSONA_DECAY) -> list[float]:
    if n <= 0:
        return []
    raw = [decay**i for i in range(n)]
    total = sum(raw)
    return [round(100 * w / total, 2) for w in raw]


def tier_split_weights(
    n_key: int,
    n_other: int,
    key_decay: float = TECH_KEY_DECAY,
    drop: float = TECH_OTHER_DROP,
) -> list[float]:
    raw_key = [key_decay**i for i in range(n_key)]
    last_key = raw_key[-1] if raw_key else 1.0
    raw_other = [last_key * (key_decay ** (i + 1)) * drop for i in range(n_other)]
    raw = raw_key + raw_other
    total = sum(raw) or 1.0
    return [round(100 * w / total, 2) for w in raw]


def compute_p99(values: list[float], transform: str) -> float:
    if not values:
        return 1.0
    if transform == "log":
        xs = [math.log1p(max(v, 0.0)) for v in values if v > 0]
    else:
        # "linear" and "recency" both percentile over raw positive values;
        # the recency normaliser applies its own log1p decay at score time.
        xs = [v for v in values if v > 0]
    if not xs:
        return 1.0
    xs.sort()
    idx = max(0, min(len(xs) - 1, int(0.99 * len(xs))))
    return round(max(xs[idx], 1e-9), 6)


def _entity(etype: str, term: str, metric: str, since: str | None = None) -> dict:
    ent: dict = {"type": etype, "term": term, "metrics": [metric]}
    if since:
        ent["since"] = since
    return ent


def _api_block(etype: str, term: str, metric: str, since: str | None = None) -> dict:
    """A `source.api` block: the endpoint, the `select` entity to send, the
    metric to read, and a human-readable extract path. `since` (when present)
    is a 3-month window the scorer recomputes to (run date − 3 months)."""
    block: dict = {
        "endpoint": ENDPOINT,
        "select_entity": _entity(etype, term, metric, since),
        "read": metric,
        "extract": f"organizations[].entities[type={etype!r},term={term!r}].{metric}",
    }
    if since:
        block["since_note"] = "3-month window; recompute `since` to run date − 3 months."
    return block


def _attr_input(name: str, attribute: str, read: str) -> dict:
    return {"name": name, "endpoint": ENDPOINT, "select_attribute": attribute, "read": read}


def _entity_input(name: str, etype: str, term: str, metric: str) -> dict:
    return {
        "name": name,
        "endpoint": ENDPOINT,
        "select_entity": _entity(etype, term, metric),
        "read": metric,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build account-scoring-weights.json.")
    parser.add_argument("--raw", default="../_raw")
    args = parser.parse_args()
    raw = Path(args.raw).resolve()
    output_root = raw.parent
    spec = json.loads((raw / "spec.json").read_text())
    audit_path = raw / "_calibration_audit.json"
    audit = (
        json.loads(audit_path.read_text())
        if audit_path.exists()
        else {"attrs": {}, "multipliers_defaults": []}
    )

    sections_pct = SECTION_BLEND

    personas = spec["personas"]
    techs = spec["techs"]
    projects = spec.get("projects") or []
    techs_key = [t for t in techs if t.get("tier") != "other"]
    techs_other = [t for t in techs if t.get("tier") == "other"]
    techs_all = techs_key + techs_other
    tech_slugs = [t["slug"] for t in techs]
    persona_names = [p["name"] for p in personas]
    since = sumble_v6.since_3mo()

    persona_decay = decay_weights(len(personas))
    tech_decay = tier_split_weights(len(techs_key), len(techs_other))
    project_decay = [round(100 / len(projects), 2) for _ in projects] if projects else []

    sections: dict[str, dict] = {
        "acv": {"label": "ACV (size + fit)", "default_pct": sections_pct.get("acv", 60)},
        "intent": {
            "label": "Intent (buying window)",
            "default_pct": sections_pct.get("intent", 40),
        },
    }
    categories: dict[str, dict] = {}
    for k, pct in CATEGORY_WEIGHTS_ACV.items():
        label = k.replace("_", " ").replace("icp", "ICP").title()
        categories[k] = {"label": label, "section": "acv", "default_pct": pct}
    intent_active = bool(projects)
    if intent_active:
        for k, pct in CATEGORY_WEIGHTS_INTENT.items():
            label = k.replace("_", " ").title()
            categories[k] = {"label": label, "section": "intent", "default_pct": pct}
    if spec.get("include_funding"):
        categories["funding"] = {
            "label": "Funding (size)",
            "section": "acv",
            "default_pct": FUNDING_CATEGORY_PCT,
        }
        if intent_active:
            categories["funding_momentum"] = {
                "label": "Funding momentum",
                "section": "intent",
                "default_pct": FUNDING_INTENT_PCT,
            }

    # Optional 1P categories from spec (e.g. product_usage in the intent section).
    for cat in spec.get("first_party_categories", []) or []:
        categories[cat["key"]] = {
            "label": cat.get("label", cat["key"].replace("_", " ").title()),
            "section": cat.get("section", "intent"),
            "default_pct": float(cat.get("default_pct", 0)),
        }

    # Re-normalise each section's category weights to sum to 100 (keeps the
    # invariant when 1P categories are appended to the intent section).
    by_section: dict[str, list[str]] = {}
    for ck, cv in categories.items():
        by_section.setdefault(cv["section"], []).append(ck)
    for cks in by_section.values():
        tot = sum(categories[ck]["default_pct"] for ck in cks)
        if tot > 0:
            for ck in cks:
                categories[ck]["default_pct"] = round(
                    categories[ck]["default_pct"] * 100 / tot, 4
                )

    signals: dict[str, dict] = {}

    def add_signal(
        key: str,
        column: str,
        label: str,
        category: str,
        transform: str,
        within: float,
        api_supported: bool,
        source: dict,
        sumble_link: dict | None = None,
        api_unsupported_reason: str | None = None,
    ) -> None:
        sig: dict = {
            "label": label,
            "column": column,
            "category": category,
            "transform": transform,
            "default_within": within,
            "p99": 1.0,
            "api_supported": api_supported,
            "source": source,
        }
        if sumble_link is not None:
            sig["sumble_link"] = sumble_link
        if api_unsupported_reason:
            sig["api_unsupported_reason"] = api_unsupported_reason
        signals[key] = sig

    # Persona signals × 3 categories
    for idx, p in enumerate(personas):
        slug, name, label = p["slug"], p["name"], p["label"]
        add_signal(
            key=f"icp_persona_count_{slug}",
            column=f"{slug}_people",
            label=f"{label} headcount",
            category="icp_persona_count",
            transform="log",
            within=persona_decay[idx],
            api_supported=True,
            source={
                "why": f"{label} is a target persona — more {label}s = bigger ACV.",
                "kind": "sumble_api",
                "api": _api_block("job_function", name, "people_count"),
            },
            sumble_link={"path": "/people", "filters": {"job_function": [name]}},
        )
        add_signal(
            key=f"icp_persona_concentration_{slug}",
            column=f"{slug}_pct",
            label=f"{label} % of company",
            category="icp_persona_concentration",
            transform="linear",
            within=persona_decay[idx],
            api_supported=True,
            source={
                "why": f"Concentration filters out big orgs with a {label} per division.",
                "kind": "sumble_derived",
                "derivation": {
                    "formula": f"100 * {slug}_people / employee_count_int",
                    "inputs": [
                        _entity_input(
                            f"{slug}_people", "job_function", name, "people_count"
                        ),
                        _attr_input(
                            "employee_count_int",
                            "employee_count",
                            "exact org headcount (employee_count is an integer; "
                            "legacy band strings map to a midpoint)",
                        ),
                    ],
                },
            },
        )
        add_signal(
            key=f"icp_persona_growth_{slug}",
            column=f"{slug}_growth_yoy",
            label=f"{label} YoY growth",
            category="icp_persona_growth",
            transform="linear",
            within=persona_decay[idx],
            api_supported=True,
            source={
                "why": (
                    f"Persona growth is a buying-window proxy — orgs growing "
                    f"{label} are scaling that function."
                ),
                "kind": "sumble_api",
                "api": {
                    **_api_block("job_function", name, "people_count_growth_1y"),
                    "transform_note": (
                        "endpoint returns a percent (e.g. 50.0); data.csv stores it "
                        "as a ratio (× 0.01)."
                    ),
                },
            },
            sumble_link={
                "path": "/trends/job_functions_people",
                "filters": {"job_function": [name]},
            },
        )

    # Tech signals × 2 categories
    for idx, t in enumerate(techs_all):
        slug, label = t["slug"], t["label"]
        add_signal(
            key=f"relevant_tech_team_count_{slug}",
            column=f"{slug}_teams",
            label=f"Teams using {label}",
            category="relevant_tech_team_count",
            transform="log",
            within=tech_decay[idx],
            api_supported=True,
            source={
                "why": f"Teams using {label} prove active, in-production adoption.",
                "kind": "sumble_api",
                "api": _api_block("technology", slug, "team_count"),
            },
            sumble_link={"path": "/teams", "filters": {"technology": [slug]}},
        )
        add_signal(
            key=f"relevant_tech_team_concentration_{slug}",
            column=f"{slug}_team_pct",
            label=f"{label} team share",
            category="relevant_tech_team_concentration",
            transform="linear",
            within=tech_decay[idx],
            api_supported=True,
            source={
                "why": f"% of teams using {label} signals broad vs one-team adoption.",
                "kind": "sumble_derived",
                "derivation": {
                    "formula": f"100 * {slug}_teams / teams_count",
                    "inputs": [
                        _entity_input(f"{slug}_teams", "technology", slug, "team_count"),
                        _attr_input(
                            "teams_count",
                            "teams_count",
                            "org-total team count (concentration denominator)",
                        ),
                    ],
                },
            },
        )

    # Funding signals (only when requested). Modelled as single-input attribute
    # derivations so score_accounts.py reproduces them straight from the API
    # `funding_*` attributes (no entity call). Both log-transformed (USD scale).
    if spec.get("include_funding"):
        # total raised → ACV "Funding (size)"; recency + last-round → Intent
        # "Funding momentum" (or all three in ACV "Funding" when there are no
        # projects, so no Intent section).
        momentum_cat = "funding_momentum" if intent_active else "funding"
        total_within = 100.0 if intent_active else 34.0
        momentum_within = 50.0 if intent_active else 33.0
        add_signal(
            key="funding_total_raised",
            column="funding_total_raised",
            label="Total funding raised",
            category="funding",
            transform="log",
            within=total_within,
            api_supported=True,
            source={
                "why": (
                    "More capital raised = a bigger budget and a faster hiring "
                    "ramp — more interviews to run."
                ),
                "kind": "sumble_derived",
                "derivation": {
                    "formula": "funding_total_raised",
                    "inputs": [
                        _attr_input(
                            "funding_total_raised",
                            "funding_total_raised",
                            "total funding raised across all rounds, whole USD",
                        ),
                    ],
                },
            },
        )
        add_signal(
            key="funding_days_since_last_round",
            column="funding_days_since_last_round",
            label="Days since last financing",
            category=momentum_cat,
            transform="recency",
            within=momentum_within,
            api_supported=True,
            source={
                "why": (
                    "A recent financing round means fresh capital and an imminent "
                    "hiring ramp — an open buying window. Score decays as the last "
                    "round ages; never-financed scores 0."
                ),
                "kind": "sumble_derived",
                "derivation": {
                    "formula": (
                        "days between funding_last_round_date and today, "
                        "recency-scored (fewer days = higher; none = 0)"
                    ),
                    "inputs": [
                        _attr_input(
                            "funding_last_round_date",
                            "funding_last_round_date",
                            "date of the latest funding round (ISO YYYY-MM-DD)",
                        ),
                    ],
                },
            },
        )
        add_signal(
            key="funding_last_round_raised",
            column="funding_last_round_raised",
            label="Latest round size",
            category=momentum_cat,
            transform="log",
            within=momentum_within,
            api_supported=True,
            source={
                "why": (
                    "A large most-recent round means fresh capital — an active "
                    "hiring/buying window."
                ),
                "kind": "sumble_derived",
                "derivation": {
                    "formula": "funding_last_round_raised",
                    "inputs": [
                        _attr_input(
                            "funding_last_round_raised",
                            "funding_last_round_raised",
                            "amount raised in the latest funding round, whole USD",
                        ),
                    ],
                },
            },
        )

    # Intent signals (when the spec has projects) — 3-month windowed via `since`
    if projects:
        for idx, proj in enumerate(projects):
            pslug, plabel = proj["slug"], proj["label"]
            tech_term = sumble_v6.intent_tech_query(pslug, tech_slugs)
            persona_term = sumble_v6.intent_persona_query(pslug, persona_names)
            add_signal(
                key=f"intent_project_tech_count_{pslug}",
                column=f"{pslug}_x_relevant_tech_jobposts",
                label=f"{plabel} × ICP tech jobs (3mo)",
                category="intent_project_tech_count",
                transform="log",
                within=project_decay[idx],
                api_supported=True,
                source={
                    "why": (
                        f"Recent jobs hitting {plabel} AND an ICP tool signal an "
                        "active, in-flight initiative — open buying window."
                    ),
                    "kind": "sumble_api",
                    "api": _api_block("advanced_query", tech_term, "job_post_count", since),
                },
                sumble_link={
                    "path": "/jobs",
                    "filters": {
                        "project": [pslug],
                        "technology": tech_slugs,
                        "hiring_period": ["3mo"],
                    },
                },
            )
            add_signal(
                key=f"intent_project_persona_count_{pslug}",
                column=f"{pslug}_x_relevant_persona_jobposts",
                label=f"{plabel} × ICP persona jobs (3mo)",
                category="intent_project_persona_count",
                transform="log",
                within=project_decay[idx],
                api_supported=True,
                source={
                    "why": (
                        f"Recent {plabel} jobs for an ICP persona show who is "
                        "staffing the project — buying-window + fit."
                    ),
                    "kind": "sumble_api",
                    "api": _api_block(
                        "advanced_query", persona_term, "job_post_count", since
                    ),
                },
                sumble_link={
                    "path": "/jobs",
                    "filters": {
                        "project": [pslug],
                        "job_function": persona_names,
                        "hiring_period": ["3mo"],
                    },
                },
            )

    # Optional 1P signals from spec — appended verbatim, first_party
    for sig in spec.get("first_party_signals", []) or []:
        key = sig["key"]
        signals[key] = {
            "label": sig.get("label", key.replace("_", " ").title()),
            "column": sig.get("column", key),
            "category": sig.get("category", "third_party_intent"),
            "transform": sig.get("transform", "log"),
            "default_within": float(sig.get("default_within", 0)),
            "p99": float(sig.get("p99", 1.0)),
            "api_supported": False,
            "api_unsupported_reason": "First-party signal — not in Sumble's public API.",
            "source": sig.get("source", {"kind": "first_party"}),
        }

    # p99 computation from data.csv
    universe_rows: list[dict] = []
    data_csv = output_root / "data.csv"
    if data_csv.exists():
        with data_csv.open() as fh:
            universe_rows.extend(csv.DictReader(fh))
    for sig in signals.values():
        if (
            sig.get("source", {}).get("kind") == "first_party"
            and sig.get("p99", 1.0) != 1.0
        ):
            continue
        col = sig["column"]
        vals: list[float] = []
        for r in universe_rows:
            try:
                vals.append(float(r.get(col) or 0))
            except ValueError:
                vals.append(0.0)
        sig["p99"] = compute_p99(vals, sig["transform"])

    # Table identity columns shown in the app: Sumble name + url + headcount only.
    # CRM identity (crm_account_id / crm_account_name / crm_url) stays in data.csv
    # for the full export but is NOT shown — duplicated CRM records would
    # otherwise surface the same Sumble org multiple times; the app dedups to
    # unique org_id. hq country is intentionally omitted.
    table_columns = ["name", "url", "employee_count_int"]

    company = spec.get("company", {})
    config: dict = {
        "schema_version": 1,
        "_comment": (
            "Account-scoring config — generated deterministically from "
            "_raw/spec.json by template/_build/build_weights.py. Every Sumble "
            "signal's source.api points at POST /v6/organizations with the exact "
            "select slice; score_accounts.py reproduces each column from it. "
            "Slider changes auto-save to this file in place."
        ),
        "provenance_guide": {
            "endpoint": ENDPOINT,
            "source_kinds": {
                "sumble_api": "one entity/attribute on /v6/organizations (source.api).",
                "sumble_derived": "arithmetic over endpoint inputs (source.derivation).",
                "first_party": "joined in by account; not from Sumble.",
            },
            "api_block": (
                "source.api = {endpoint, select_entity|select_attribute, read, extract}. "
                "select_entity is the exact select.entities[] item to send; read is the "
                "metric to take off the EntityResult. since entities are a 3-month window "
                "the scorer recomputes to (run date − 3 months)."
            ),
            "api_supported": (
                "true if score_accounts.py can reproduce the column from the public API. "
                "false (tech concentration) stays in the app for tuning but is dropped + "
                "weight-renormalised by the portable scorer."
            ),
        },
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "customer_name": f"{company.get('name', 'Unknown')} — Scoring",
        "score_label": "Account Score",
        "id_column": "org_id",
        "name_column": "name",
        "slug_column": "slug",
        "sumble_url_base": "https://sumble.com/orgs/",
        "data_csv": "data.csv",
        "table_columns": table_columns,
        "data_sources": spec.get("data_sources", {}),
        "sections": sections,
        "categories": categories,
        "signals": signals,
        "multipliers": [],
        "tag_multipliers": [],
        "tag_multipliers_defaults": audit.get("multipliers_defaults", []),
        "_tag_calibration_audit": audit.get("attrs", {}),
    }
    out_path = output_root / "account-scoring-weights.json"
    out_path.write_text(json.dumps(config, indent=2))
    print(
        f"Wrote {out_path}: {len(sections)} sections, {len(categories)} "
        f"categories, {len(signals)} signals, "
        f"{len(audit.get('multipliers_defaults', []))} default tag multipliers."
    )


if __name__ == "__main__":
    main()
