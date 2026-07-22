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
import math
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


# z for the Wilson score interval (see `_share`). 1.96 = 95% confidence — the
# standard choice, not tuned per run. Raise to 2.58 (99%) if a pull's thin-data
# tail still saturates the p99 normaliser.
CONFIDENCE_Z = 1.96


def _share(numerator: float, denominator: float) -> float:
    """Concentration percentage as the WILSON 95% lower confidence bound.

    Plain English: the lowest share that could plausibly explain what we
    observed. 1 team of 1 using the tech is consistent with a company that's
    only ~21% concentrated, so it scores 21 — while 266 of 3630 is pinned tight
    and scores 6.5, essentially its raw 7.3%.

    Why not the raw ratio: it treats 1/1 and 900/900 as identically "100%", so
    orgs we know almost nothing about saturate the signal. On a 4,884-row pull
    192 orgs read >=99% design share with a MEDIAN denominator of 1; the p99
    normaliser then fits to those and a well-measured org's genuine 7% share
    normalises to ~0.07 — the signal ends up ranking how LITTLE data an org has.
    The lower bound shrinks thin evidence toward 0 and leaves well-measured orgs
    essentially untouched, with one standard constant instead of a tuned prior.

    Deliberately conservative: every share reads slightly below its raw value.
    That's uniform enough not to disturb ranking among well-measured orgs.
    """
    if numerator <= 0 or denominator <= 0:
        return 0.0
    # max() guards the rounding artifacts of a recovered denominator (see
    # `recover_total`); a proportion above 1 is not meaningful.
    z, n = CONFIDENCE_Z, max(denominator, numerator)
    p = numerator / n
    z2 = z * z
    lb = (
        p + z2 / (2 * n) - z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    ) / (1 + z2 / n)
    return round(max(100.0 * lb, 0.0), 3)


def recover_total(pairs: list[tuple[float, float]]) -> float:
    """Recover the org-wide concentration DENOMINATOR from (count, ratio) pairs.

    WORKAROUND — delete once /v6/organizations exposes hierarchy-scoped counts
    as attributes (`hp_jobs_count` / `hp_people_count` / `hp_teams_count` already
    exist on the `organizations` table; flagged to the API team). The endpoint
    returns `people_concentration` / `job_post_concentration` as a RATIO only, but
    the Wilson bound in `_share` needs the sample size, so we invert:
    `denominator = count / ratio`.

    The ratio is rounded to 4dp, so precision degrades as the share gets small
    (at a 0.02% share the recovered total is ~25% off; below ~0.005% the ratio
    rounds to 0.0 and is unrecoverable). Every persona shares ONE denominator
    (org-wide people) and every tech shares ONE denominator (org-wide job posts),
    so we recover it a single time from the pair with the LARGEST count — the
    best-conditioned one available — and reuse it across all signals. A tech with
    500 posts at 0.0250 pins the total to 20,000 +/-0.2%.

    Returns 0.0 when nothing is recoverable (every count 0, or every ratio
    rounded away). `_share` then reads 0.0, which is the right answer in both
    cases: no measured presence, or a share too small to register.
    """
    best_total = 0.0
    best_count = 0.0
    for count, ratio in pairs:
        if count > best_count and ratio > 0:
            best_count = count
            best_total = count / ratio
    return round(best_total)


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


def tech_query(t: dict) -> str:
    """DSL term matching ONE ICP tech, whichever kind it is:
      plain      -> `technology EQ 'slug'`
      category   -> `technology_category EQ 'slug'`
      synthetic  -> the authored membership union (`synthetic_tech_query`)
    """
    kind = t.get("kind")
    if kind == "synthetic":
        return synthetic_tech_query(t)
    if kind == "category":
        return f"technology_category EQ {_q(t['slug'])}"
    return f"technology EQ {_q(t['slug'])}"


def tech_entity(t: dict) -> dict[str, Any]:
    """How ONE ICP tech is selected on the endpoint: `{type, term, granularity}`.

    ALL three kinds go out as `advanced_query`, so every tech has one column
    shape (`{slug}_teams`, `{slug}_jobs`) and one metric set. This is the single
    place mapping a spec tech to an entity selection, so `entity_plan` (what we
    fetch) and `build_weights` (what the config records) can never disagree.

    Why advanced_query for a PREDEFINED category too, rather than the
    `technology_category` type: only `advanced_query` supports
    `job_post_concentration`, the same-scope concentration metric the score needs
    (the `technology_category` type does not). It costs nothing semantically —
    the endpoint implements a `technology_category` aggregate by building exactly
    `technology_category EQ '<slug>'` and running it through the same
    advanced-query counter, so the deduped counts are identical.

    `granularity` is None for every kind: it is valid only on the
    `technology_category` TYPE and the endpoint rejects it on advanced_query.
    """
    return {"type": "advanced_query", "term": tech_query(t), "granularity": None}


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
        # Native same-scope concentration (people in function / people in org,
        # both hierarchy rollups) — the denominator the score actually needs.
        # `build_data_row` inverts it to recover that denominator.
        plan.append(
            {
                "col": f"{p['slug']}_people_conc",
                "type": "job_function",
                "term": p["name"],
                "metric": "people_concentration",
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
        ent = tech_entity(t)
        plan.append(
            {
                "col": f"{t['slug']}_teams",
                **ent,
                "metric": "team_count",
                "scale": 1.0,
                "since": None,
            }
        )
        # Job posts + their native same-scope concentration. Tech concentration
        # is a share of HIRING (job posts), not of teams: `job_post_concentration`
        # is the only concentration metric advanced_query exposes, and both sides
        # of it are hierarchy-scoped so parent orgs can't blow past 100%.
        plan.append(
            {
                "col": f"{t['slug']}_jobs",
                **ent,
                "metric": "job_post_count",
                "scale": 1.0,
                "since": None,
            }
        )
        plan.append(
            {
                "col": f"{t['slug']}_jobs_conc",
                **ent,
                "metric": "job_post_concentration",
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
    # midpoint only as a legacy fallback). teams_count / jobs_count are
    # record-scoped org attributes, shown as firmographics only — concentration
    # denominators come from the native concentration metrics instead.
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

    # Concentration signals, from the endpoint's NATIVE concentration metrics.
    # Both sides of those ratios are hierarchy rollups, so the scope mismatch
    # that made entity-count / org-attribute shares exceed 100% for holding
    # companies (Advance: 252 Design teams vs a record-scoped teams_count of 6)
    # cannot arise. The metrics return a ratio only, so `recover_total` inverts
    # the best-conditioned one per org to get the denominator `_share` needs.
    people_total = recover_total(
        [
            (_f(row.get(f"{p['slug']}_people")), _f(row.get(f"{p['slug']}_people_conc")))
            for p in personas
        ]
    )
    # Recovered denominators are kept as columns so a share is always auditable
    # against the counts beside it.
    row["people_total_est"] = people_total
    for p in personas:
        people = _f(row.get(f"{p['slug']}_people"))
        row[f"{p['slug']}_pct"] = _share(people, people_total)
        # Concentration reuses the persona's /people deep link.
        row[f"{p['slug']}_pct_link"] = row.get(f"{p['slug']}_people_link", "")
    jobs_total = recover_total(
        [
            (_f(row.get(f"{t['slug']}_jobs")), _f(row.get(f"{t['slug']}_jobs_conc")))
            for t in techs
        ]
    )
    row["jobs_total_est"] = jobs_total
    for t in techs:
        jobs = _f(row.get(f"{t['slug']}_jobs"))
        row[f"{t['slug']}_job_pct"] = _share(jobs, jobs_total)
        # Concentration reuses the tech's /jobs deep link (it is a hiring share).
        row[f"{t['slug']}_job_pct_link"] = row.get(f"{t['slug']}_jobs_link", "")

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
