"""Sumble account scorer — portable, public-API, zero-dependency.

Re-implements the calibrated score from `account-scoring-weights.json` (or
`account-whitespace-weights.json`) against Sumble's unified REST endpoint
`POST https://api.sumble.com/v6/organizations`, which matches AND enriches a
batch of accounts in one call. Runs anywhere with Python 3.10+ and internet
access — no MCP, no internal Sumble access.

Usage:
    export SUMBLE_API_KEY=...            # from sumble.com/account
    python score_accounts.py --accounts my_accounts.csv --out scored_accounts.csv

`my_accounts.csv` needs a `domain` and/or `name` column (domain preferred).

Every signal flagged `api_supported: false` in the config (e.g. tech-team
concentration, which the endpoint can't reproduce — no org-total team count) is
SKIPPED and its weight re-normalised across the survivors. So scores
rank-correlate strongly with the web app's full model but aren't byte-identical.
Tune in the app; scale with this.

Stdlib only: argparse, csv, datetime, json, math, os, sys, urllib.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import getpass
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlencode

APP_DIR = Path(__file__).resolve().parent
API_URL = os.environ.get("SUMBLE_API_BASE", "https://api.sumble.com/v6") + "/organizations"
BATCH = 1000  # endpoint accepts up to 1000 orgs per call

SPEC_CANDIDATES = ("account-scoring-weights.json", "account-whitespace-weights.json")
# Base firmographics fetched for every account (penalties, concentration, display).
BASE_ATTRIBUTES = [
    "id",
    "slug",
    "name",
    "url",
    "employee_count",
    "jobs_count",
    "teams_count",
    "industry",
    "headquarters_country",
    "tags",
]


def resolve_spec_path() -> Path:
    for name in SPEC_CANDIDATES:
        p = APP_DIR / name
        if p.exists():
            return p
    return APP_DIR / SPEC_CANDIDATES[0]


SPEC_PATH = resolve_spec_path()

_KEY_CONFIG = Path.home() / ".config" / "sumble" / "api_key"


def resolve_api_key() -> str | None:
    """Find the key: env var → saved key file → interactive prompt (saved on entry).

    Checks SUMBLE_API_KEY, then SUMBLE_API_KEY_FILE / ~/.config/sumble/api_key /
    $TMPDIR/sumble_api_key / ./.sumble_api_key. If none and stdin is a TTY, asks
    once via getpass and saves to ~/.config/sumble/api_key for next time.
    """
    key = os.environ.get("SUMBLE_API_KEY")
    if key:
        return key.strip()
    candidates = []
    explicit = os.environ.get("SUMBLE_API_KEY_FILE")
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(_KEY_CONFIG)
    tmp = os.environ.get("TMPDIR")
    if tmp:
        candidates.append(Path(tmp) / "sumble_api_key")
    candidates.append(Path(".sumble_api_key"))
    for p in candidates:
        if p.exists() and p.read_text().strip():
            return p.read_text().strip()
    if sys.stdin.isatty():
        entered = getpass.getpass("Paste your Sumble API key (input hidden): ").strip()
        if entered:
            _KEY_CONFIG.parent.mkdir(parents=True, exist_ok=True)
            _KEY_CONFIG.write_text(entered + "\n")
            _KEY_CONFIG.chmod(0o600)
            sys.stderr.write(f"[key] saved to {_KEY_CONFIG}\n")
            return entered
    return None


# ---------- Endpoint helpers -------------------------------------------------


def since_3mo() -> str:
    return (_dt.date.today() - _dt.timedelta(days=90)).isoformat()


_BAND_NUM = re.compile(r"[\d,]+")


def emp_band_to_int(band: str | None) -> int:
    if not band:
        return 0
    nums = [int(n.replace(",", "")) for n in _BAND_NUM.findall(band)]
    if not nums:
        return 0
    if len(nums) == 1:
        return int(nums[0] * 1.5) if str(band).strip().endswith("+") else nums[0]
    return (nums[0] + nums[1]) // 2


def _exact_employee_count(attrs: dict) -> int:
    """Exact org headcount from the `employee_count` attribute.

    The endpoint returns `employee_count` as an exact integer (e.g. 2615). For
    resilience we also accept the older band-string form ("1,001 - 5,000") and
    map it to a midpoint; a missing value yields 0.
    """
    val = attrs.get("employee_count")
    if isinstance(val, bool):
        return 0
    if isinstance(val, (int, float)):
        return int(val) if val > 0 else 0
    if isinstance(val, str):
        return emp_band_to_int(val)
    return 0


def metric_scale(metric: str) -> float:
    # Growth comes back as a percent (e.g. 50.0); the model uses a ratio.
    return 0.01 if metric.endswith("growth_1y") else 1.0


def post(api_key: str, body: dict, *, retries: int = 4) -> dict | None:
    data = json.dumps(body).encode("utf-8")
    for attempt in range(retries):
        req = urllib.request.Request(API_URL, data=data, method="POST")
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2**attempt)
                continue
            sys.stderr.write(f"[api] HTTP {e.code}: {e.read()[:300]!r}\n")
            return None
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries - 1:
                time.sleep(2**attempt)
                continue
            sys.stderr.write(f"[api] error: {e}\n")
            return None
    return None


# ---------- Build the `select` payload from the config -----------------------


def is_api_supported(sig: dict[str, Any]) -> bool:
    return bool(sig.get("api_supported", sig.get("source", {}).get("kind") != "sumble_sql"))


def _entity_key(entity: dict) -> tuple[Any, Any]:
    return (entity.get("type"), entity.get("term"))


def collect_select(signals_scored: dict[str, dict]) -> dict:
    """Union of every entity/attribute needed by the api_supported signals.

    `since` entities are refreshed to (today − 3 months) so the window tracks
    the scorer's run date rather than the build date stored in the config.
    """
    entities: dict[tuple[str, str], dict] = {}
    since = since_3mo()

    def add_entity(entity: dict) -> None:
        ent = dict(entity)
        if "since" in ent:
            ent["since"] = since
        key = _entity_key(ent)
        cur = entities.get(key)
        if cur is None:
            entities[key] = {
                "type": ent["type"],
                "term": ent["term"],
                "metrics": list(ent.get("metrics") or []),
                **({"since": ent["since"]} if "since" in ent else {}),
                # Required by the endpoint for technology_category, rejected for
                # every other type — so carry it through exactly as configured.
                **({"granularity": ent["granularity"]} if ent.get("granularity") else {}),
            }
        else:
            for m in ent.get("metrics") or []:
                if m not in cur["metrics"]:
                    cur["metrics"].append(m)

    extra_attrs: set[str] = set()
    for sig in signals_scored.values():
        src = sig.get("source", {})
        api = src.get("api")
        if api and api.get("select_entity"):
            add_entity(api["select_entity"])
        if api and api.get("select_attribute"):
            extra_attrs.add(api["select_attribute"])
        for inp in (src.get("derivation", {}) or {}).get("inputs", []):
            if inp.get("select_entity"):
                add_entity(inp["select_entity"])
            if inp.get("select_attribute"):
                extra_attrs.add(inp["select_attribute"])
    # Attributes referenced by signals (e.g. funding_*) on top of the baseline,
    # so a funding-enabled config pulls them and a plain config doesn't.
    attributes = list(BASE_ATTRIBUTES) + [
        a for a in sorted(extra_attrs) if a not in BASE_ATTRIBUTES
    ]
    return {"attributes": attributes, "entities": list(entities.values())}


# ---------- Per-account value resolution -------------------------------------


def _input_value(inp: dict, ents: dict, attrs: dict) -> float:
    if inp.get("select_entity"):
        ent = inp["select_entity"]
        metric = inp.get("read") or (ent.get("metrics") or [""])[0]
        e = ents.get(_entity_key(ent), {})
        return float(e.get(metric) or 0) * metric_scale(metric)
    attribute = inp.get("select_attribute")
    if attribute in ("employee_count_int", "employee_count"):
        return float(_exact_employee_count(attrs))
    val = attrs.get(attribute)
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return 0.0


def _days_since_attr(src: dict, attrs: dict) -> float:
    """Days since the date attribute the recency signal references (min 1), or 0
    when absent/unparseable — so the portable scorer reproduces the recency raw
    from the API `funding_last_round_date` attribute."""
    name = (src.get("api") or {}).get("select_attribute")
    if not name:
        for inp in (src.get("derivation", {}) or {}).get("inputs", []):
            if inp.get("select_attribute"):
                name = inp["select_attribute"]
                break
    raw = attrs.get(name) if name else None
    if not raw:
        return 0.0
    try:
        d = _dt.date.fromisoformat(str(raw)[:10])
    except ValueError:
        return 0.0
    return float(max(1, (_dt.date.today() - d).days))


# The endpoint's native concentration metrics. Both sides of each ratio are
# hierarchy rollups, so a parent org's share can never exceed 100%.
CONCENTRATION_METRICS = ("people_concentration", "job_post_concentration")

CONFIDENCE_Z = 1.96


def wilson_lb_pct(numerator: float, denominator: float) -> float:
    """Concentration percentage as the Wilson 95% lower confidence bound — the
    lowest share that could plausibly explain what we observed. Mirrors
    `sumble_v6._share` exactly so this scorer and the app agree.

    A raw ratio scores 1/1 and 900/900 identically at 100%, letting orgs we know
    almost nothing about saturate the signal; the lower bound shrinks thin
    evidence toward 0 and leaves well-measured orgs essentially untouched.
    """
    if numerator <= 0 or denominator <= 0:
        return 0.0
    z, n = CONFIDENCE_Z, max(denominator, numerator)
    p = numerator / n
    z2 = z * z
    lb = (
        p + z2 / (2 * n) - z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    ) / (1 + z2 / n)
    return round(max(100.0 * lb, 0.0), 3)


def concentration_metric(sig: dict) -> str | None:
    """The native concentration metric a signal's derivation inverts, if any."""
    deriv = (sig.get("source") or {}).get("derivation")
    if not isinstance(deriv, dict):
        return None
    inputs = deriv.get("inputs") or []
    if len(inputs) < 2:
        return None
    read = inputs[1].get("read") or ""
    return read if read in CONCENTRATION_METRICS else None


def recover_totals(
    config: dict, eff: dict[str, float], ents: dict, attrs: dict
) -> dict[str, float]:
    """metric -> the org-wide concentration DENOMINATOR, recovered by inversion.

    WORKAROUND — delete once /v6/organizations exposes hierarchy-scoped counts
    as attributes (flagged to the API team). The concentration metrics return a
    ratio only, but the Wilson bound needs the sample size, so we invert:
    `denominator = count / ratio`. The ratio is rounded to 4dp, so precision
    degrades as the share shrinks — every signal sharing a metric also shares one
    org-wide denominator, so recover it once from the LARGEST count available
    (the best-conditioned pair) and reuse it. Mirrors `sumble_v6.recover_total`.
    """
    best: dict[str, tuple[float, float]] = {}
    for key in eff:
        metric = concentration_metric(config["signals"][key])
        if not metric:
            continue
        inputs = config["signals"][key]["source"]["derivation"]["inputs"]
        count = _input_value(inputs[0], ents, attrs)
        ratio = _input_value(inputs[1], ents, attrs)
        if ratio > 0 and count > best.get(metric, (0.0, 0.0))[0]:
            best[metric] = (count, count / ratio)
    return {m: round(total) for m, (_, total) in best.items()}


def signal_raw(
    sig: dict, ents: dict, attrs: dict, totals: dict[str, float] | None = None
) -> float:
    src = sig.get("source", {})
    if sig.get("transform") == "recency":
        return _days_since_attr(src, attrs)
    api = src.get("api")
    if api and api.get("select_entity"):
        ent = api["select_entity"]
        metric = api.get("read") or (ent.get("metrics") or [""])[0]
        e = ents.get(_entity_key(ent), {})
        return float(e.get(metric) or 0) * metric_scale(metric)
    deriv = src.get("derivation")
    if isinstance(deriv, dict):
        inputs = deriv.get("inputs") or []
        # Concentration: count + native ratio -> Wilson bound over the org-wide
        # denominator recovered once per org.
        metric = concentration_metric(sig)
        if metric:
            num = _input_value(inputs[0], ents, attrs)
            return wilson_lb_pct(num, (totals or {}).get(metric, 0.0))
        # Older configs express a concentration as a plain 100 * num / denom.
        if len(inputs) >= 2:
            num = _input_value(inputs[0], ents, attrs)
            den = _input_value(inputs[1], ents, attrs)
            return 100.0 * num / den if den else 0.0
        if len(inputs) == 1:
            return _input_value(inputs[0], ents, attrs)
    return 0.0


# ---------- Normalisation / weights (unchanged maths) ------------------------


def normalise(raw: float, transform: str, p99: float) -> float:
    if transform == "recency":
        # lower days-since = higher; never financed (raw<=0) = 0. Mirrors app.py.
        if raw <= 0:
            return 0.0
        denom = math.log1p(max(float(p99 or 0), 1.0))
        if denom <= 0:
            return 0.0
        return max(0.0, min(1.0 - math.log1p(raw) / denom, 1.0))
    x = raw if transform == "linear" else math.log1p(max(raw, 0.0))
    p99 = max(float(p99 or 0), 1e-9)
    arg = min(-x / p99, 700.0)
    n = (1.0 - math.exp(arg)) / (1.0 - math.exp(-1.0))
    return max(0.0, min(n, 1.0))


def effective_weights(config: dict) -> tuple[dict[str, float], list[str]]:
    signals = {k: v for k, v in config["signals"].items() if isinstance(v, dict)}
    categories = config.get("categories", {})
    sections = config.get("sections", {})
    has_sections = bool(sections)

    scored = {k: s for k, s in signals.items() if is_api_supported(s)}
    dropped = [k for k in signals if k not in scored]

    within_sum: dict[str, float] = {}
    for s in scored.values():
        cat = s.get("category", "first_party")
        within_sum[cat] = within_sum.get(cat, 0.0) + float(s.get("default_within") or 0)

    live_cats = {c for c in within_sum if within_sum[c] > 0}
    sec_of = {c: categories.get(c, {}).get("section") for c in categories}

    def cat_pool(cat: str) -> list[str]:
        if not has_sections:
            return list(live_cats)
        return [c for c in live_cats if sec_of.get(c) == sec_of.get(cat)]

    live_secs = {sec_of.get(c) for c in live_cats} if has_sections else set()
    sec_sum = sum(
        float(sections[s].get("default_pct") or 0) for s in live_secs if s in sections
    )

    eff: dict[str, float] = {}
    for k, s in scored.items():
        cat = s.get("category", "first_party")
        if within_sum.get(cat, 0) <= 0:
            continue
        within_frac = float(s.get("default_within") or 0) / within_sum[cat]
        pool = cat_pool(cat)
        cat_sum = sum(float(categories.get(c, {}).get("default_pct") or 0) for c in pool)
        cat_frac = (
            float(categories.get(cat, {}).get("default_pct") or 0) / cat_sum
            if cat_sum
            else 0.0
        )
        if has_sections:
            sec = sec_of.get(cat)
            sec_frac = (
                float(sections[sec].get("default_pct") or 0) / sec_sum
                if (sec in sections and sec_sum)
                else 0.0
            )
        else:
            sec_frac = 1.0
        eff[k] = sec_frac * cat_frac * within_frac
    return eff, dropped


def score_row(row: dict, config: dict, eff: dict[str, float]) -> tuple[float, float, str]:
    """Return (base_score 0-100, adjustment_factor, adjustment_detail).

    final score = base_score * adjustment_factor. The boost/penalty factor and
    its human-readable detail are returned separately so the output shows the
    profile adjustment explicitly instead of folding it into the contributions.
    """
    signals = config["signals"]
    base = 0.0
    for key, frac in eff.items():
        sig = signals[key]
        norm = normalise(
            float(row.get(sig["column"]) or 0),
            sig.get("transform", "log"),
            sig.get("p99", 1e-9),
        )
        base += frac * norm
    factor = 1.0
    bits: list[str] = []
    for m in config.get("multipliers", []):
        pct = float(m.get("default_pct") or 0) / 100.0
        if pct > 0 and row.get(m["column"]):
            factor *= 1 - pct
            bits.append(f"{m.get('label') or m['column']} -{round(pct * 100)}%")
    row_tags = {t.strip() for t in str(row.get("tags") or "").split("|") if t.strip()}
    for entry in config.get("tag_multipliers", []):
        tag = entry.get("tag")
        pct = float(entry.get("pct") or 0) / 100.0
        if tag and pct > 0 and tag in row_tags:
            boost = entry.get("direction") == "boost"
            factor *= (1 + pct) if boost else (1 - pct)
            bits.append(f"{tag} {'+' if boost else '-'}{round(pct * 100)}%")
    return base * 100.0, factor, "; ".join(bits)


# ---------- Per-account pipeline ---------------------------------------------


def sumble_link(base: str, slug: str, spec: dict | None) -> str:
    """Per-org Sumble deep link for a signal's sumble_link spec — same URL
    shape as the app's buildSumbleLink (filters → advanced-search `as=` JSON)."""
    if not spec or not slug:
        return ""
    path = spec.get("path", "") or ""
    url = f"{base}{slug}{path}"
    raw_filters = {
        field: values
        for field, values in (spec.get("filters") or {}).items()
        if isinstance(values, list) and values
    }
    # technology + technology_category share ONE OR group: an ICP "tech" can
    # be an individual tool or a predefined Sumble category, and the page
    # should match jobs hitting either — separate groups would AND them.
    groups: list[dict] = []
    tech_done = False
    for field, values in raw_filters.items():
        if field in ("technology", "technology_category"):
            if tech_done:
                continue
            groups.append(
                {
                    "operator": "OR",
                    "fields": {
                        k: {"include": raw_filters[k], "exclude": []}
                        for k in ("technology", "technology_category")
                        if k in raw_filters
                    },
                }
            )
            tech_done = True
            continue
        groups.append(
            {"operator": "OR", "fields": {field: {"include": values, "exclude": []}}}
        )
    if not groups:
        return url
    params: list[tuple[str, str]] = []
    if "people" in path:
        params += [("sort", "Sumble Lead Score"), ("desc", "1")]
    params.append(
        ("as", json.dumps({"operator": "AND", "children": groups}, separators=(",", ":")))
    )
    return url + "?" + urlencode(params, quote_via=quote_plus)


def build_row(account: dict, resp_org: dict, config: dict, eff: dict[str, float]) -> dict:
    attrs = resp_org.get("attributes") or {}
    ents = {(_entity_key(e)): e for e in (resp_org.get("entities") or [])}
    industry = attrs.get("industry") or ""
    # professional_services is a native Sumble org tag (no industry synthesis).
    tags = list(attrs.get("tags") or [])

    slug = attrs.get("slug") or ""
    link_base = config.get("sumble_url_base", "https://sumble.com/orgs/")

    row: dict[str, Any] = dict(account)
    row["matched_org_id"] = attrs.get("id")
    row["matched_domain"] = attrs.get("url")
    row["name"] = attrs.get("name") or account.get("name") or ""
    row["industry"] = industry
    # Always carried (blank when unmatched) — part of the score-sheet contract.
    row["headquarters_country"] = attrs.get("headquarters_country") or ""
    row["employee_count_int"] = _exact_employee_count(attrs)
    row["jobs_count"] = int(attrs.get("jobs_count") or 0)
    row["teams_count"] = int(attrs.get("teams_count") or 0)
    row["tags"] = "|".join(tags)
    row["is_it_services"] = 1 if "it_services" in tags else 0
    row["is_professional_services"] = 1 if "professional_services" in tags else 0
    # Deep links: the org page, plus one per signal that carries a sumble_link
    # spec — so the scored output is clickable, like the app's score.csv.
    row["sumble_url"] = f"{link_base}{slug}" if slug else ""

    # One recovered denominator per concentration metric, shared by every signal
    # that uses it (see recover_totals).
    totals = recover_totals(config, eff, ents, attrs)
    for key in eff:
        sig = config["signals"][key]
        row[sig["column"]] = signal_raw(sig, ents, attrs, totals)
        if sig.get("sumble_link"):
            row[f"{sig['column']}_link"] = sumble_link(
                link_base, slug, sig.get("sumble_link")
            )

    if attrs.get("id"):
        base_score, factor, detail = score_row(row, config, eff)
    else:
        base_score, factor, detail = 0.0, 1.0, ""
    row["base_score"] = round(base_score, 4)
    row["profile_adjustment"] = round(factor, 4)
    row["profile_adjustment_detail"] = detail
    row["score"] = round(base_score * factor, 4)
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description="Score accounts via the Sumble public API.")
    ap.add_argument("--accounts", required=True, help="CSV with name and/or domain columns")
    ap.add_argument("--out", default="scored_accounts.csv", help="output CSV path")
    ap.add_argument("--limit", type=int, default=0, help="score only the first N (0 = all)")
    args = ap.parse_args()

    api_key = resolve_api_key()
    if not api_key:
        sys.exit(
            "No Sumble API key found. `export SUMBLE_API_KEY=...` (or run this in a "
            "terminal to be prompted). Get a key at sumble.com/account."
        )
    if not SPEC_PATH.exists():
        sys.exit(f"{SPEC_PATH.name} not found next to this script.")

    config = json.loads(SPEC_PATH.read_text())
    eff, dropped = effective_weights(config)
    scored_signals = {k: config["signals"][k] for k in eff}
    if dropped:
        names = ", ".join(config["signals"][k].get("label", k) for k in dropped)
        sys.stderr.write(
            f"[scorer] {len(dropped)} signal(s) not available via public API "
            f"(dropped, weights re-normalised): {names}\n"
        )

    select = collect_select(scored_signals)

    with Path(args.accounts).open(newline="", encoding="utf-8") as f:
        accounts = list(csv.DictReader(f))
    if args.limit:
        accounts = accounts[: args.limit]

    scored: list[dict] = []
    calls = 0
    for bi in range(0, len(accounts), BATCH):
        chunk = accounts[bi : bi + BATCH]
        orgs = [
            {"name": a.get("name") or "", "url": a.get("domain") or a.get("url") or ""}
            for a in chunk
        ]
        resp = post(api_key, {"organizations": orgs, "select": select})
        calls += 1
        resp_orgs = (resp or {}).get("organizations") or [{} for _ in chunk]
        for a, ro in zip(chunk, resp_orgs):
            scored.append(build_row(a, ro, config, eff))
        sys.stderr.write(
            f"[scorer] {min(bi + BATCH, len(accounts))}/{len(accounts)} scored "
            f"({calls} API calls)\n"
        )

    scored.sort(key=lambda r: r.get("score", 0), reverse=True)
    for rank, r in enumerate(scored, 1):
        r["rank"] = rank
    fieldnames: list[str] = ["rank"]
    for r in scored:
        for k in r:
            if k not in fieldnames:
                fieldnames.append(k)
    with Path(args.out).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(scored)
    sys.stderr.write(
        f"[scorer] wrote {len(scored)} rows to {args.out} ({calls} API calls)\n"
    )


if __name__ == "__main__":
    main()
