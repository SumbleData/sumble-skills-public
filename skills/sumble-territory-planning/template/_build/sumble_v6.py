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
        sys.stderr.write(
            "\nGet your Sumble API key at https://sumble.com/account "
            "(Account → API key).\n"
        )
        entered = getpass.getpass(
            "Paste it here (hidden; saved for next time): "
        ).strip()
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


# Additive smoothing for concentration ratios (see `_share`). A share is
# computed as num / (den + k), so an org must have a real denominator before it
# can report an extreme concentration. Policy constants — not chosen per run.
#   TEAM_SHARE_SMOOTHING  denominator is `teams_count` (median ~31; 19% of a
#     typical pull have <=5 teams, and a 1-team org reading "100% design" was
#     saturating the p99 and squashing everyone else). k=5 maps 1/1 -> 17%,
#     9/9 -> 64%, 17/17 -> 77%, and leaves 266/3630 at 7.3% (unchanged).
#   PEOPLE_SHARE_SMOOTHING  denominator is `employee_count`, which carries a
#     min-employee floor and is far larger, so it needs a bigger prior to have
#     any effect: k=25 maps 28/50 -> 37% (was 56%) and leaves 500/22251 at 2.2%.
TEAM_SHARE_SMOOTHING = 5.0
PEOPLE_SHARE_SMOOTHING = 25.0


def _share(
    numerator: float, denominator: float, smoothing: float = 0.0
) -> tuple[float, bool]:
    """A smoothed concentration percentage, plus whether it is TRUSTWORTHY.

    Returns `(pct, ok)`. `ok` is False when the two sides are not measuring the
    same population, in which case `pct` is 0.0 and the caller should treat the
    concentration as UNKNOWN rather than low.

    The scopes genuinely differ. An entity metric (`{tech}_teams`,
    `{persona}_people`) is aggregated across the org HIERARCHY, while the
    denominator attribute (`teams_count`, `employee_count`) counts the matched
    entity ALONE. Verified on the endpoint: Advance (a holding company) reports
    `teams_count=6` and `jobs_count=39` of its own, but 252 Design teams and 645
    Design job posts across its subsidiaries. `granularity` accepts only
    'aggregate' | 'exploded' — neither restricts scope — and no hierarchy-wide
    team/job total is exposed, so the ratio simply cannot be computed for these
    orgs.

    Numerator > denominator is the detector: a share cannot exceed 100%, so it
    proves the denominator is out of scope.

    Do NOT "fix" this by clamping to 100. That pins every holding company at the
    MAXIMUM possible concentration — awarding full marks on a signal we cannot
    compute — which promotes them over genuinely dense mid-market accounts. 0.0
    with ok=False awards nothing instead; the raw counts still score through the
    Size segment, so a large holdco is not erased, only barred from unearned
    concentration credit.

    SMOOTHING (the opposite failure, at the small end). A raw ratio treats 1/1
    and 900/900 as identically "100% concentrated", so orgs with almost no
    measured data saturate the signal: on a 4,884-row pull, 192 orgs read
    >=99% design share and their MEDIAN `teams_count` was 1. Because the p99
    normaliser is fitted to those, a well-measured org's genuine 7% share
    normalises to ~0.07 — the signal ends up ranking how LITTLE we know about an
    org. Dividing by `denominator + smoothing` shrinks thin evidence toward 0
    while leaving well-measured orgs untouched, and caps the attainable share
    below 100% so only orgs with a real denominator approach the top. Preferred
    over a hard minimum-denominator cutoff, which would discard genuinely small
    design shops outright.

    Detection runs on the RAW ratio and smoothing only shapes the reported
    value — otherwise smoothing could pull a scope-mismatched ratio back under
    100% and hide it.
    """
    if denominator <= 0:
        # No measured population. With no numerator either, 0% is the true
        # answer (nothing of anything) — only a positive numerator over an
        # empty denominator proves the scopes disagree.
        return 0.0, numerator <= 0
    if numerator > denominator:
        return 0.0, False
    pct = 100.0 * numerator / (denominator + smoothing)
    return round(max(pct, 0.0), 3), True


def tech_members(t: dict) -> list[str]:
    """Member technology slugs of a SYNTHETIC category (kind == 'synthetic').

    A synthetic category is an agent-authored set treated as ONE deduped signal,
    used when no *predefined* Sumble technology_category expresses the ICP
    grouping. `members` are individual technology slugs; a synthetic category may
    ALSO absorb whole predefined categories via `member_categories`.
    """
    return [str(s) for s in (t.get("members") or [])]


def tech_member_categories(t: dict) -> list[str]:
    """Predefined technology_category slugs absorbed by a SYNTHETIC category.

    Lets a synthetic category extend a predefined one rather than restate it:
    `member_categories: ["generative-ai-tools"]` plus `members: [...]` scores the
    whole category OR the extra slugs as a single deduped signal. Absorbing the
    category (instead of hand-expanding its members) keeps the signal in sync
    when Sumble later adds a technology to that category.
    """
    return [str(s) for s in (t.get("member_categories") or [])]


def synthetic_tech_query(t: dict) -> str:
    """DSL term for a synthetic category, e.g. `technology IN ('a', 'b')` or
    `(technology IN ('a') OR technology_category IN ('c'))`.

    Sent as an `advanced_query` entity. Its `team_count` is the DEDUPED count of
    teams using ANY member — the same counter the endpoint uses for a predefined
    `technology_category` aggregate, so a synthetic category and a predefined one
    have identical semantics; only the membership is authored rather than looked
    up. A team using three members still counts once.

    NB: `granularity` is rejected by the endpoint on `advanced_query` (it is
    valid only for `technology_category`), so `tech_entity` leaves it None — the
    dedupe is intrinsic to the query, not a granularity setting.
    """
    parts = []
    if tech_members(t):
        parts.append(f"technology IN {_in_list(tech_members(t))}")
    if tech_member_categories(t):
        parts.append(f"technology_category IN {_in_list(tech_member_categories(t))}")
    if not parts:
        return ""
    return parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"


def expand_tech_slugs(techs: list[dict]) -> list[str]:
    """Every INDIVIDUAL technology slug implied by `techs`, order-preserved and
    deduped: plain techs plus the members of each synthetic category. Predefined
    categories are excluded (they live under `technology_category`)."""
    out: list[str] = []
    for t in techs:
        kind = t.get("kind")
        if kind == "category":
            continue
        out.extend(tech_members(t) if kind == "synthetic" else [t["slug"]])
    seen: set[str] = set()
    return [s for s in out if not (s in seen or seen.add(s))]


def expand_tech_categories(techs: list[dict]) -> list[str]:
    """Every predefined technology_category slug implied by `techs`, order-preserved
    and deduped: `kind == 'category'` entries plus the `member_categories` absorbed
    by each synthetic category."""
    out: list[str] = []
    for t in techs:
        kind = t.get("kind")
        if kind == "category":
            out.append(t["slug"])
        elif kind == "synthetic":
            out.extend(tech_member_categories(t))
    seen: set[str] = set()
    return [s for s in out if not (s in seen or seen.add(s))]


def tech_clause(techs: list[dict]) -> str:
    """DSL clause matching any of the techs — individual slugs via `technology IN`,
    predefined categories (kind == 'category') via `technology_category IN`, and
    synthetic categories (kind == 'synthetic') by expanding their member slugs
    into the individual `technology IN` list and their absorbed
    `member_categories` into the `technology_category IN` list."""
    cats = expand_tech_categories(techs)
    indiv = expand_tech_slugs(techs)
    parts = []
    if indiv:
        parts.append(f"technology IN {_in_list(indiv)}")
    if cats:
        parts.append(f"technology_category IN {_in_list(cats)}")
    if not parts:
        return ""
    return parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"


def tech_entity(t: dict) -> dict[str, Any]:
    """How ONE ICP tech is selected on the endpoint: `{type, term, granularity}`.

    Three kinds, one column shape (`{slug}_teams`) — the single place that maps
    a spec tech to an entity selection, so `entity_plan` (what we fetch) and
    `build_weights` (what the config records) can never disagree:
      plain      -> technology / slug
      category   -> technology_category / slug, granularity=aggregate
      synthetic  -> advanced_query / `technology IN (members)` OR'd with
                    `technology_category IN (member_categories)`
    """
    kind = t.get("kind")
    if kind == "synthetic":
        return {"type": "advanced_query", "term": synthetic_tech_query(t), "granularity": None}
    if kind == "category":
        return {"type": "technology_category", "term": t["slug"], "granularity": "aggregate"}
    return {"type": "technology", "term": t["slug"], "granularity": None}


def intent_tech_query(project_slug: str, techs: list[dict]) -> str:
    return f"project EQ {_q(project_slug)} AND {tech_clause(techs)}"


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
                **tech_entity(t),
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
                    "term": intent_tech_query(proj["slug"], techs),
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
    gran: dict[tuple[str, str, str | None], str | None] = {}
    order: list[tuple[str, str, str | None]] = []
    for item in plan:
        key = (item["type"], item["term"], item["since"])
        if key not in by_key:
            by_key[key] = set()
            order.append(key)
        by_key[key].add(item["metric"])
        if item.get("granularity"):
            gran[key] = item["granularity"]

    entities: list[dict[str, Any]] = []
    for etype, term, since_val in order:
        ent: dict[str, Any] = {
            "type": etype,
            "term": term,
            "metrics": sorted(by_key[(etype, term, since_val)]),
        }
        if since_val:
            ent["since"] = since_val
        if gran.get((etype, term, since_val)):
            ent["granularity"] = gran[(etype, term, since_val)]
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
    the skill-specific columns (is_icp_gold, list_type, crm_*).
    `professional_services` is a native Sumble org tag (it arrives in
    `attributes.tags` like `it_services`) — no industry-based synthesis.
    """
    attrs = resp_row.get("attributes") or {}
    org_id = attrs.get("id")
    if not org_id:
        return None
    plan = plan if plan is not None else entity_plan(spec)
    personas = spec["personas"]
    techs = spec["techs"]
    industry = attrs.get("industry") or ""
    # Calibration runs purely over the org's Sumble tags — industries are
    # intentionally NOT synthesized into tags (professional_services included:
    # it is a native org tag the endpoint returns in attributes.tags).
    tags = list(attrs.get("tags") or [])
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
        "is_professional_services": 1 if "professional_services" in tags else 0,
        "tags": "|".join(tags),
    }
    for slug in ATTR_FLAGS_FROM_TAGS:
        target_key = slug if slug == "is_ai_native" else f"is_{slug}"
        row[target_key] = 1 if slug in tags else 0

    for item in plan:
        ent = ents.get((item["type"], item["term"]), {})
        row[item["col"]] = round(_f(ent.get(item["metric"])) * item["scale"], 6)
        # The endpoint returns a canonical deep link beside each metric
        # ({metric}_url); carry it so links point at the real Sumble listing
        # rather than a hand-built URL.
        row[f"{item['col']}_link"] = ent.get(f"{item['metric']}_url") or ""

    # Concentration signals. `_share` returns (pct, ok); ok=False means the
    # denominator attribute is entity-scoped while the numerator is
    # hierarchy-scoped (typical of holding companies), so the ratio is UNKNOWN,
    # not low. We record 0.0 and flag the row rather than clamping to 100 —
    # see `_share` for why clamping actively misranks holdcos.
    scope_ok = True
    for p in personas:
        people = _f(row.get(f"{p['slug']}_people"))
        pct, ok = _share(people, employee_count, PEOPLE_SHARE_SMOOTHING)
        row[f"{p['slug']}_pct"] = pct
        scope_ok &= ok
        # Concentration reuses the persona's /people deep link.
        row[f"{p['slug']}_pct_link"] = row.get(f"{p['slug']}_people_link", "")
    # Tech team concentration uses the org-total team count (teams_count
    # attribute), so it's a true share-of-teams and fully API-reproducible.
    for t in techs:
        teams = _f(row.get(f"{t['slug']}_teams"))
        pct, ok = _share(teams, org_teams, TEAM_SHARE_SMOOTHING)
        row[f"{t['slug']}_team_pct"] = pct
        scope_ok &= ok
        # Concentration reuses the tech's /teams deep link.
        row[f"{t['slug']}_team_pct_link"] = row.get(f"{t['slug']}_teams_link", "")
    # Visible/filterable so a suppressed concentration is never mistaken for a
    # genuinely diffuse org.
    row["concentration_scope_ok"] = 1 if scope_ok else 0

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
