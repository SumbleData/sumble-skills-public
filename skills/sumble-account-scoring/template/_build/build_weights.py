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

POLICY CONSTANTS (intentionally fixed defaults; the user can override the
segment taxonomy in the interview via spec["section_plan"]):
- PERSONA_DECAY = 0.98, TECH_KEY_DECAY = 0.98, TECH_OTHER_DROP = 0.6
- DEFAULT_SECTIONS — three orthogonal segments: Size, Concentration, and
  Growth & momentum (blend 50/30/20). The old ACV/Intent blend is gone.
- DEFAULT_CATEGORY_SECTION / CATEGORY_META below — which segment each category
  lands in by default, and its label + within-segment weight.

Segments are user-customizable. spec["section_plan"] can rename / reweight /
reassign segments (e.g. a per-business-unit breakdown like Oracle OCI vs Apps),
and the existing spec["first_party_categories"] / spec["first_party_signals"]
hooks weave 1P (or repeated Sumble) signals into any segment. A signal may
appear in MORE THAN ONE segment — app.py scores each signal from its `column`,
so a duplicate key with the same `column` simply repeats the element.
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

# Default three-segment taxonomy. The score blends three orthogonal segments;
# the user can rename / reweight / reassign them (or define entirely custom
# segments, e.g. per business unit) in the interview via spec["section_plan"].
DEFAULT_SECTIONS = [
    {"key": "size", "label": "Size (how big is the opportunity)", "default_pct": 50},
    {
        "key": "growth_momentum",
        "label": "Growth & momentum (is now the time)",
        "default_pct": 30,
    },
    {
        "key": "concentration",
        "label": "Concentration (how strong / focused the fit)",
        "default_pct": 20,
    },
]
# category_key -> default segment key.
DEFAULT_CATEGORY_SECTION = {
    "icp_persona_count": "size",
    "relevant_tech_team_count": "size",
    "intent_project_tech_count": "size",
    "intent_project_persona_count": "size",
    "funding": "size",
    "icp_persona_concentration": "concentration",
    "relevant_tech_team_concentration": "concentration",
    "icp_persona_growth": "growth_momentum",
    "funding_momentum": "growth_momentum",
}
# category_key -> {label, default_pct}. default_pct is the WITHIN-segment weight
# before per-segment renormalisation (categories absent for this spec drop out
# and the rest renormalise to 100). Funding categories appear only when
# spec["include_funding"]; intent_project_* only when the spec has projects.
CATEGORY_META = {
    "icp_persona_count": {"label": "Persona headcount", "default_pct": 45.0},
    "relevant_tech_team_count": {"label": "Tech teams", "default_pct": 30.0},
    "intent_project_tech_count": {
        "label": "Project × tech jobs (recent)",
        "default_pct": 15.0,
    },
    "intent_project_persona_count": {
        "label": "Project × persona jobs (recent)",
        "default_pct": 10.0,
    },
    "funding": {"label": "Funding (total raised)", "default_pct": 12.0},
    "icp_persona_concentration": {
        "label": "Persona concentration",
        "default_pct": 60.0,
    },
    "relevant_tech_team_concentration": {
        "label": "Tech team concentration",
        "default_pct": 40.0,
    },
    "icp_persona_growth": {"label": "Persona growth (YoY)", "default_pct": 100.0},
    "funding_momentum": {"label": "Funding momentum", "default_pct": 30.0},
}


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

    intent_active = bool(projects)
    funding_active = bool(spec.get("include_funding"))

    # --- Segment taxonomy (default three segments, user-overridable) ---
    plan = spec.get("section_plan") or {}
    sections_list = plan.get("sections") or DEFAULT_SECTIONS
    section_assign = dict(DEFAULT_CATEGORY_SECTION)
    section_assign.update(plan.get("category_section") or {})
    cat_overrides = plan.get("category_meta") or {}

    sections: dict[str, dict] = {}
    for s in sections_list:
        sections[s["key"]] = {
            "label": s.get("label", s["key"].replace("_", " ").title()),
            "default_pct": float(s.get("default_pct", 0)),
        }
    default_section = sections_list[0]["key"]

    def _cat_active(ck: str) -> bool:
        if ck in ("intent_project_tech_count", "intent_project_persona_count"):
            return intent_active
        if ck in ("funding", "funding_momentum"):
            return funding_active
        return True  # persona + tech categories are always present

    categories: dict[str, dict] = {}
    for ck, meta in CATEGORY_META.items():
        if not _cat_active(ck):
            continue
        sec = section_assign.get(ck, default_section)
        if sec not in sections:  # a custom plan dropped this segment → fall back
            sec = default_section
        ov = cat_overrides.get(ck, {})
        categories[ck] = {
            "label": ov.get("label", meta["label"]),
            "section": sec,
            "default_pct": float(ov.get("default_pct", meta["default_pct"])),
        }

    # Optional 1P (or repeated-Sumble) categories from spec — placed in any
    # segment (default: the first). Lets the user weave first-party signals or
    # business-unit breakdowns into the taxonomy.
    for cat in spec.get("first_party_categories", []) or []:
        sec = cat.get("section", default_section)
        if sec not in sections:
            sec = default_section
        categories[cat["key"]] = {
            "label": cat.get("label", cat["key"].replace("_", " ").title()),
            "section": sec,
            "default_pct": float(cat.get("default_pct", 0)),
        }

    # Drop any segment that ended up with no categories, then renormalise the
    # surviving segments' blend to 100.
    live_sections = {cv["section"] for cv in categories.values()}
    sections = {k: v for k, v in sections.items() if k in live_sections}
    sec_total = sum(v["default_pct"] for v in sections.values())
    if sec_total > 0:
        for v in sections.values():
            v["default_pct"] = round(v["default_pct"] * 100 / sec_total, 4)

    # Re-normalise each segment's category weights to sum to 100 (keeps the
    # invariant when categories are added/removed per spec).
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

    # Tech signals × 2 categories. A tech can be an individual technology or a
    # predefined Sumble technology CATEGORY (kind=="category") — the entity type +
    # deep-link field differ, but the column/score shape is identical.
    for idx, t in enumerate(techs_all):
        slug, label = t["slug"], t["label"]
        is_cat = t.get("kind") == "category"
        etype = "technology_category" if is_cat else "technology"
        link_field = "technology_category" if is_cat else "technology"
        kind_word = "category" if is_cat else "tool"
        add_signal(
            key=f"relevant_tech_team_count_{slug}",
            column=f"{slug}_teams",
            label=f"Teams using {label}",
            category="relevant_tech_team_count",
            transform="log",
            within=tech_decay[idx],
            api_supported=True,
            source={
                "why": f"Teams using the {label} {kind_word} prove active, in-production adoption.",
                "kind": "sumble_api",
                "api": _api_block(etype, slug, "team_count"),
            },
            sumble_link={"path": "/teams", "filters": {link_field: [slug]}},
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
                        _entity_input(f"{slug}_teams", etype, slug, "team_count"),
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
    if funding_active:
        # total raised → "Funding (total raised)" (Size by default); recency +
        # last-round → "Funding momentum" (Growth & momentum by default). The
        # growth_momentum segment always exists (persona growth), so funding
        # momentum no longer depends on whether the spec has projects.
        momentum_cat = "funding_momentum"
        total_within = 100.0
        momentum_within = 50.0
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
            tech_term = sumble_v6.intent_tech_query(pslug, techs)
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

    # Optional 1P (or repeated-Sumble) signals from spec. By default each is a
    # first-party signal (api_supported:false). To REPEAT a Sumble column in a
    # second segment, point `column` at the existing data.csv column and set
    # `api_supported:true` with a `source` block — its p99 is recomputed from
    # data.csv like any Sumble signal.
    for sig in spec.get("first_party_signals", []) or []:
        key = sig["key"]
        api_supported = bool(sig.get("api_supported", False))
        entry: dict = {
            "label": sig.get("label", key.replace("_", " ").title()),
            "column": sig.get("column", key),
            "category": sig.get("category", "third_party_intent"),
            "transform": sig.get("transform", "log"),
            "default_within": float(sig.get("default_within", 0)),
            "p99": float(sig.get("p99", 1.0)),
            "api_supported": api_supported,
            "source": sig.get(
                "source", {"kind": "sumble_api" if api_supported else "first_party"}
            ),
        }
        if not api_supported:
            entry["api_unsupported_reason"] = sig.get(
                "api_unsupported_reason",
                "First-party signal — not in Sumble's public API.",
            )
        if sig.get("sumble_link"):
            entry["sumble_link"] = sig["sumble_link"]
        signals[key] = entry

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
        # Apply the gold-lift calibration BY DEFAULT (attribute + industry
        # boosts/penalties) — the app opens with them active and the user can
        # tune or remove any in the per-tag widget. tag_multipliers_defaults keeps
        # the same list so Reset restores the calibrated starting point.
        "tag_multipliers": audit.get("multipliers_defaults", []),
        "tag_multipliers_defaults": audit.get("multipliers_defaults", []),
        "_tag_calibration_audit": {
            "attrs": audit.get("attrs", {}),
            "industries": audit.get("industries", {}),
        },
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
