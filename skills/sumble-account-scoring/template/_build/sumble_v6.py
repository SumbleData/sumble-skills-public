"""Shared helpers for the unified Sumble `POST /v6/organizations` endpoint.

Single source of truth for: how each `data.csv` signal column maps to one
entity selection on the endpoint (`entity_plan`), how to assemble the `select`
payload (`build_select`), how to read values back out of a response row
(`index_entities`, `emp_band_to_int`), and the 3-month intent window date
(`since_3mo`). `fetch_data.py`, `merge_data.py`, and `build_weights.py` all
import from here so the fetched payload, the merged columns, and the weights'
`source` blocks can never drift apart.

The endpoint is documented in api/app/routers/paid_api/organizations.py
(`enrich_organizations_unified`). Term formats: technology/project = slug,
job_function = display Name, advanced_query = the Sumble query DSL string.
"""

from __future__ import annotations

import datetime as _dt
import getpass
import os
import re
import sys
from pathlib import Path
from typing import Any

API_URL = "https://api.sumble.com/v6/organizations"

# Where a saved key is read from / written to. First existing wins on read;
# the interactive prompt writes the durable ~/.config path.
_KEY_CONFIG = Path.home() / ".config" / "sumble" / "api_key"


def _key_file_candidates() -> list[Path]:
    paths: list[Path] = []
    explicit = os.environ.get("SUMBLE_API_KEY_FILE")
    if explicit:
        paths.append(Path(explicit))
    paths.append(_KEY_CONFIG)
    tmp = os.environ.get("TMPDIR")
    if tmp:
        paths.append(Path(tmp) / "sumble_api_key")
    paths.append(Path(".sumble_api_key"))
    return paths


def _read_env_file(path: str) -> str | None:
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line.startswith("SUMBLE_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")
    return None


def save_api_key(key: str) -> Path:
    """Write the key to ~/.config/sumble/api_key with 0600 perms."""
    _KEY_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    _KEY_CONFIG.write_text(key.strip() + "\n")
    _KEY_CONFIG.chmod(0o600)
    return _KEY_CONFIG


def saved_key() -> str | None:
    """Return a key persisted to a key file (NOT env) — i.e. one that survives
    across sessions. Used to decide whether a fresh save is still needed."""
    for p in _key_file_candidates():
        if p.exists():
            k = p.read_text().strip()
            if k:
                return k
    return None


def resolve_api_key(env_file: str | None = None, allow_prompt: bool = False) -> str | None:
    """Find the Sumble API key: env var → --env-file → saved key file → prompt.

    `allow_prompt` only triggers an interactive getpass when stdin is a TTY (so
    it never hangs an unattended/agent run); the entered key is saved for reuse.
    """
    key = os.environ.get("SUMBLE_API_KEY")
    if key:
        return key.strip()
    if env_file and Path(env_file).exists():
        k = _read_env_file(env_file)
        if k:
            return k
    file_key = saved_key()
    if file_key:
        return file_key
    if allow_prompt and sys.stdin.isatty():
        entered = getpass.getpass("Paste your Sumble API key (input hidden): ").strip()
        if entered:
            dest = save_api_key(entered)
            sys.stderr.write(f"[key] saved to {dest}\n")
            return entered
    return None

# Attributes pulled for every org. id/name/slug/url/sumble_url are free; the
# rest cost 1 credit each per matched org (see _per_org_credit_cost).
ATTRIBUTES = [
    "id",
    "slug",
    "name",
    "url",
    "employee_count",
    "jobs_count",
    "teams_count",
    "industry",
    "headquarters_country",
    "parent_id",
    "subsidiary_ids",
    "tags",
]

# Funding attributes, requested only when spec["include_funding"] is set. Each
# costs 1 credit per matched org. total/last-round amounts drive the funding
# scoring signals; type/date are carried for context (display, not scored).
FUNDING_ATTRIBUTES = [
    "funding_total_raised",
    "funding_last_round_raised",
    "funding_last_round_type",
    "funding_last_round_date",
]


def since_3mo(today: _dt.date | None = None) -> str:
    """The `since` date (YYYY-MM-DD) ~3 months before `today` for intent signals.

    The endpoint snaps this to its nearest hiring-period bucket, so day-precision
    isn't required; 90 days is a stable stand-in for "last 3 months".
    """
    d = (today or _dt.date.today()) - _dt.timedelta(days=90)
    return d.isoformat()


def days_since(date_str: object, today: _dt.date | None = None) -> object:
    """Whole days between an ISO date string and today (min 1), or "" if absent
    / unparseable. Used for the funding recency signal; "" → 0 → no recency."""
    if not date_str:
        return ""
    try:
        d = _dt.date.fromisoformat(str(date_str)[:10])
    except ValueError:
        return ""
    today = today or _dt.date.today()
    return max(1, (today - d).days)


def _q(value: str) -> str:
    """Single-quote a DSL literal, escaping any embedded single quotes."""
    return "'" + value.replace("'", "''") + "'"


def _in_list(values: list[str]) -> str:
    return "(" + ", ".join(_q(v) for v in values) + ")"


def intent_tech_query(project_slug: str, tech_slugs: list[str]) -> str:
    return f"project EQ {_q(project_slug)} AND technology IN {_in_list(tech_slugs)}"


def intent_persona_query(project_slug: str, persona_names: list[str]) -> str:
    return f"project EQ {_q(project_slug)} AND job_function IN {_in_list(persona_names)}"


def entity_plan(spec: dict, since: str | None = None) -> list[dict[str, Any]]:
    """Map each Sumble-sourced signal column to exactly one entity selection.

    Returns one item per column with keys:
      col      data.csv column the value lands in
      type     entity type (technology | job_function | advanced_query)
      term     entity term (slug / Name / DSL string)
      metric   metric to read off the matched EntityResult
      scale    multiplier applied to the raw value (growth is a % -> ratio)
      since    YYYY-MM-DD window, or None
    `merge_data.py` and `build_weights.py` both iterate this list, so the
    fetched payload and the persisted `source` blocks stay identical.
    """
    since = since or since_3mo()
    personas = spec["personas"]
    techs = spec["techs"]
    projects = spec.get("projects") or []
    tech_slugs = [t["slug"] for t in techs]
    persona_names = [p["name"] for p in personas]

    plan: list[dict[str, Any]] = []
    for p in personas:
        plan.append(
            {
                "col": f"{p['slug']}_people",
                "type": "job_function",
                "term": p["name"],
                "metric": "people_count",
                "scale": 1.0,
                "since": None,
            }
        )
        plan.append(
            {
                "col": f"{p['slug']}_growth_yoy",
                "type": "job_function",
                "term": p["name"],
                "metric": "people_count_growth_1y",
                "scale": 0.01,  # endpoint returns a percent (50.0); store as ratio
                "since": None,
            }
        )
    for t in techs:
        plan.append(
            {
                "col": f"{t['slug']}_teams",
                "type": "technology",
                "term": t["slug"],
                "metric": "team_count",
                "scale": 1.0,
                "since": None,
            }
        )
    if projects:
        for proj in projects:
            plan.append(
                {
                    "col": f"{proj['slug']}_x_relevant_tech_jobposts",
                    "type": "advanced_query",
                    "term": intent_tech_query(proj["slug"], tech_slugs),
                    "metric": "job_post_count",
                    "scale": 1.0,
                    "since": since,
                }
            )
            plan.append(
                {
                    "col": f"{proj['slug']}_x_relevant_persona_jobposts",
                    "type": "advanced_query",
                    "term": intent_persona_query(proj["slug"], persona_names),
                    "metric": "job_post_count",
                    "scale": 1.0,
                    "since": since,
                }
            )
    return plan


def build_select(spec: dict, since: str | None = None) -> dict[str, Any]:
    """Assemble the `select` payload: attributes + the deduped entity list.

    Multiple metrics on the same (type, term, since) collapse into one entity
    selection so the endpoint is asked for each thing exactly once.
    """
    plan = entity_plan(spec, since)
    by_key: dict[tuple[str, str, str | None], set[str]] = {}
    order: list[tuple[str, str, str | None]] = []
    for item in plan:
        key = (item["type"], item["term"], item["since"])
        if key not in by_key:
            by_key[key] = set()
            order.append(key)
        by_key[key].add(item["metric"])

    entities: list[dict[str, Any]] = []
    for etype, term, since_val in order:
        ent: dict[str, Any] = {
            "type": etype,
            "term": term,
            "metrics": sorted(by_key[(etype, term, since_val)]),
        }
        if since_val:
            ent["since"] = since_val
        entities.append(ent)
    attributes = list(ATTRIBUTES)
    if spec.get("include_funding"):
        attributes += FUNDING_ATTRIBUTES
    return {"attributes": attributes, "entities": entities}


def index_entities(resp_row: dict) -> dict[tuple[str, str], dict]:
    """Index a response org's `entities` by (type, term) for value lookup."""
    out: dict[tuple[str, str], dict] = {}
    for ent in resp_row.get("entities") or []:
        out[(ent.get("type"), ent.get("term"))] = ent
    return out


ATTR_FLAGS_FROM_TAGS = ["b2b", "b2c", "digital_native", "is_ai_native"]


def _f(val: object, default: float = 0.0) -> float:
    if val in (None, "", "null"):
        return default
    try:
        return float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def build_data_row(
    resp_row: dict, spec: dict, plan: list[dict[str, Any]] | None = None
) -> dict | None:
    """Common data.csv columns for one matched org from an endpoint response.

    Returns None for an unmatched input (empty `attributes`). The caller adds
    the skill-specific columns (is_icp_gold, list_type, crm_*). The synthetic
    `professional_services` tag is appended here when industry matches, so the
    tag-lift calibration treats it like any other tag.
    """
    attrs = resp_row.get("attributes") or {}
    org_id = attrs.get("id")
    if not org_id:
        return None
    plan = plan if plan is not None else entity_plan(spec)
    personas = spec["personas"]
    techs = spec["techs"]
    industry = attrs.get("industry") or ""
    tags = list(attrs.get("tags") or [])
    if industry == "Professional Services" and "professional_services" not in tags:
        tags.append("professional_services")
    # employee_count is the endpoint's exact integer headcount (band-string
    # midpoint only as a legacy fallback). teams_count / jobs_count are org-total
    # attributes used as concentration denominators and shown as firmographics.
    employee_count = _exact_employee_count(attrs)
    org_teams = int(_f(attrs.get("teams_count")))
    ents = index_entities(resp_row)

    row: dict = {
        "org_id": org_id,
        "slug": attrs.get("slug") or "",
        "name": attrs.get("name") or "",
        "url": attrs.get("url") or "",
        "headquarters_country": attrs.get("headquarters_country") or "",
        "industry": industry,
        "employee_count_int": employee_count,
        "jobs_count": int(_f(attrs.get("jobs_count"))),
        "teams_count": org_teams,
        "is_it_services": 1 if "it_services" in tags else 0,
        "is_professional_services": 1 if industry == "Professional Services" else 0,
        "tags": "|".join(tags),
    }
    for slug in ATTR_FLAGS_FROM_TAGS:
        target_key = slug if slug == "is_ai_native" else f"is_{slug}"
        row[target_key] = 1 if slug in tags else 0

    for item in plan:
        ent = ents.get((item["type"], item["term"]), {})
        row[item["col"]] = round(_f(ent.get(item["metric"])) * item["scale"], 6)

    for p in personas:
        people = _f(row.get(f"{p['slug']}_people"))
        row[f"{p['slug']}_pct"] = (
            round(100.0 * people / employee_count, 3) if employee_count else 0.0
        )
    # Tech team concentration now uses the org-total team count (teams_count
    # attribute), so it's a true share-of-teams and fully API-reproducible.
    for t in techs:
        teams = _f(row.get(f"{t['slug']}_teams"))
        row[f"{t['slug']}_team_pct"] = (
            round(100.0 * teams / org_teams, 3) if org_teams else 0.0
        )

    # Funding columns (only when requested). total/last-round amounts are scored;
    # type/date are display context. Missing values become 0 / "" so the columns
    # are always present and numeric for the scorer.
    if spec.get("include_funding"):
        row["funding_total_raised"] = int(_f(attrs.get("funding_total_raised")))
        row["funding_last_round_raised"] = int(_f(attrs.get("funding_last_round_raised")))
        row["funding_last_round_type"] = attrs.get("funding_last_round_type") or ""
        last_round_date = attrs.get("funding_last_round_date") or ""
        row["funding_last_round_date"] = last_round_date
        # Recency: whole days since the latest round ("" when never financed →
        # scored as 0). The `recency` transform inverts this (fewer days = higher).
        row["funding_days_since_last_round"] = days_since(last_round_date)
    return row


def _exact_employee_count(attrs: dict) -> int:
    """Exact org headcount from the endpoint's `employee_count` attribute.

    The /v6/organizations endpoint returns `employee_count` as an exact integer
    (e.g. 2615). For resilience we also accept the older band-string form
    ("1,001 - 5,000") and map it to a midpoint via `emp_band_to_int`; a missing
    value yields 0.
    """
    val = attrs.get("employee_count")
    if isinstance(val, bool):
        return 0
    if isinstance(val, (int, float)):
        return int(val) if val > 0 else 0
    if isinstance(val, str):
        return emp_band_to_int(val)
    return 0


_BAND_NUM = re.compile(r"[\d,]+")


def emp_band_to_int(band: str | None) -> int:
    """Map an employee-count band string to a representative integer.

    The endpoint returns bands like "1,001 - 5,000" or "10,001+". We use the
    midpoint of a range, or 1.5x the floor for an open-ended "N+" band.
    """
    if not band:
        return 0
    nums = [int(n.replace(",", "")) for n in _BAND_NUM.findall(band)]
    if not nums:
        return 0
    if len(nums) == 1:
        return int(nums[0] * 1.5) if band.strip().endswith("+") else nums[0]
    return (nums[0] + nums[1]) // 2
