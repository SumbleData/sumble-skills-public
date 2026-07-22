"""Shared helpers for the territory-planning pipeline.

Single source of truth for the things every `_build/` script has to agree on:
how a domain is normalised, which column carries the segment-boundary metric,
how a size value maps to a segment, how activity events roll up per
(rep, account), and how per-rep book balance is measured.

`calibrate_split.py`, `merge_territory.py`, `build_plan.py`, and
`suggest_moves.py` all import from here, so the threshold the user confirms,
the segments written into `territory.csv`, and the moves proposed against them
can never disagree.

Stdlib only — the generated app must run on a stock Python 3.10+.
"""

from __future__ import annotations

import csv
import datetime as _dt
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Policy constants (not chosen per run — same inputs → same output)
# ---------------------------------------------------------------------------

# Book-balance labels, keyed off the coefficient of variation of per-rep total
# score. CV is scale-free, so it reads the same for a 5-account book and a
# 5,000-account one; a raw max/min ratio would not.
CV_BALANCED = 0.15
CV_UNEVEN = 0.35

# Free-mail and consumer domains never identify an account. Activity to these is
# dropped before matching so a rep emailing their own gmail can't mark an
# account "worked".
FREEMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
    "yahoo.com", "yahoo.co.uk", "ymail.com", "icloud.com", "me.com", "mac.com",
    "aol.com", "proton.me", "protonmail.com", "pm.me", "gmx.com", "gmx.de",
    "zoho.com", "yandex.com", "mail.com", "msn.com", "qq.com", "163.com",
    "fastmail.com", "hey.com", "duck.com", "example.com",
}

# Human-readable thresholds the calibrator snaps to. A boundary of "1,000
# employees" is a number a sales leader can defend in a QBR; "1,043" is not, and
# the extra precision is noise at this sample size.
HUMAN_THRESHOLDS = [50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000]

# A rep needs at least this many matched accounts before their median account
# size is evidence of which segment they sell to.
MIN_ACCOUNTS_FOR_SEGMENT_GUESS = 3

# Share of accounts below the proposed boundary that may read zero on the chosen
# job-function metric before we warn that the function is too granular. Above
# this, the metric is mostly measuring "we have no data on this company", not
# size — the failure mode that makes "# of DevOps engineers" a bad boundary.
MAX_ZERO_FRACTION_BELOW = 0.30

ACTIVITY_KINDS = ("meeting", "call", "email_out", "email_in")

# Activity that counts as the rep actually working the account. Inbound email
# alone is the prospect doing the work, so it is tracked but does not clear the
# "not being worked" flag on its own.
OUTBOUND_KINDS = ("meeting", "call", "email_out")

# Categories included in book-balance maths. Customers are excluded by default:
# a rep is not "overloaded" because they own renewals, and moving a customer
# breaks a live relationship.
DEFAULT_BALANCE_CATEGORIES = ["allocated", "unallocated"]

# Move-search policy.
CV_STOP = 0.10          # stop rebalancing once the segment is this even
MAX_MOVE_FRAC = 0.15    # never churn more than this share of a segment's book
DEFAULT_WHITESPACE_TOP_N = 50

TERRITORY_COLUMNS = [
    "org_id", "name", "domain", "crm_account_id", "account_category",
    "score", "score_source", "size_metric", "size_metric_name",
    "account_segment", "owner", "owner_email", "rep_segment",
    "unallocated", "double_allocated", "other_owners", "segment_misfit",
    "worked", "strong_idle",
    "meetings", "calls", "emails_out", "emails_in",
    "last_activity_date", "activity_sources",
    "pipeline_value", "sumble_url",
    "proposed_owner", "proposal_reason", "proposal_status",
]


# ---------------------------------------------------------------------------
# Small IO / coercion helpers
# ---------------------------------------------------------------------------


def read_csv(path: Path) -> list[dict[str, str]]:
    """Read a CSV to a list of dicts. Missing file → empty list (every input
    except the ownership list is optional)."""
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in columns})
    tmp.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def to_float(v: Any, default: float = 0.0) -> float:
    if v in (None, "", "null", "None"):
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def to_int(v: Any, default: int = 0) -> int:
    return int(to_float(v, default))


def truthy(v: Any) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "y", "t")


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")


# ---------------------------------------------------------------------------
# Domain + email normalisation — the join key for everything
# ---------------------------------------------------------------------------

_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)


def norm_domain(value: Any) -> str:
    """Bare lowercase registrable domain: strips scheme, `www.`, path, port,
    and a leading `@`. Everything joins on this, so it must be applied
    identically to CRM domains, calendar attendee addresses, and Sumble urls."""
    s = str(value or "").strip().lower()
    if not s:
        return ""
    s = s.lstrip("@")
    s = _SCHEME.sub("", s)
    s = s.split("/")[0].split("?")[0].split("#")[0]
    s = s.split(":")[0]
    if s.startswith("www."):
        s = s[4:]
    return s.strip(".")


def email_domain(value: Any) -> str:
    s = str(value or "").strip().lower()
    if "@" in s:
        s = s.rsplit("@", 1)[1]
    return norm_domain(s)


def norm_email(value: Any) -> str:
    return str(value or "").strip().lower()


def is_account_domain(domain: str, own_domains: Iterable[str]) -> bool:
    """A domain worth matching an account on: not blank, not free-mail, and not
    the seller's own domain (internal meetings are not account activity)."""
    d = norm_domain(domain)
    if not d or "." not in d:
        return False
    if d in FREEMAIL_DOMAINS:
        return False
    return d not in {norm_domain(o) for o in own_domains if o}


# ---------------------------------------------------------------------------
# Segment boundary
# ---------------------------------------------------------------------------


def resolve_size_column(spec: dict[str, Any], header: Iterable[str]) -> str:
    """Which column in the account table carries the segment-boundary metric.

    `boundary.column` wins when the agent set it explicitly. Otherwise the
    metric string decides:
      total_employees   -> employee_count_int
      jf_people:<Name>  -> jf_people, else <slug-of-name>_people (the column an
                           account-scoring run already emits for that persona)
      custom:<column>   -> that column verbatim
    """
    boundary = spec.get("boundary") or {}
    explicit = str(boundary.get("column") or "").strip()
    cols = list(header)
    if explicit:
        return explicit
    metric = str(boundary.get("metric") or "total_employees").strip()
    if metric.startswith("custom:"):
        return metric.split(":", 1)[1].strip()
    if metric.startswith("jf_people:"):
        name = metric.split(":", 1)[1].strip()
        for cand in ("jf_people", f"{slugify(name)}_people"):
            if cand in cols:
                return cand
        return "jf_people"
    return "employee_count_int"


def segment_for_size(value: float, boundary: dict[str, Any], segments: list[dict[str, Any]]) -> str:
    """Map a size value to a segment key.

    Thresholds are `{segment, min}` and inclusive: a company sitting exactly on
    the boundary lands in the LARGER segment (>= min), which is what a hard-line
    rule like "enterprise is 1,000+ employees" means. With no threshold matched,
    the lowest-order (smallest) segment wins.
    """
    thresholds = sorted(
        (boundary.get("thresholds") or []),
        key=lambda t: to_float(t.get("min"), 0.0),
        reverse=True,
    )
    for t in thresholds:
        if value >= to_float(t.get("min"), 0.0):
            return str(t.get("segment") or "")
    ordered = sorted(segments, key=lambda s: to_int(s.get("order"), 0))
    return str(ordered[0].get("key")) if ordered else ""


def segment_labels(segments: list[dict[str, Any]]) -> dict[str, str]:
    return {str(s.get("key")): str(s.get("label") or s.get("key")) for s in segments}


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile (p in 0..1). Deterministic, no interpolation."""
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(round(p * (len(s) - 1)))))
    return s[idx]


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def coefficient_of_variation(values: list[float]) -> float:
    """Population CV (stdev / mean) — the balance index. 0 = every rep carries
    an identical book. Returns 0.0 for <2 reps or a zero mean (nothing to
    compare)."""
    vals = [v for v in values]
    if len(vals) < 2:
        return 0.0
    mean = sum(vals) / len(vals)
    if mean <= 0:
        return 0.0
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    return math.sqrt(var) / mean


def balance_label(cv: float) -> str:
    if cv <= CV_BALANCED:
        return "balanced"
    if cv <= CV_UNEVEN:
        return "uneven"
    return "imbalanced"


def snap_to_human(value: float) -> int:
    """Snap a computed threshold to the nearest defensible round number.
    Ratio distance, not absolute: 700 is closer to 500 than to 1000 on a log
    scale, which is how company sizes actually distribute."""
    if value <= 0:
        return HUMAN_THRESHOLDS[0]
    best = HUMAN_THRESHOLDS[0]
    best_dist = float("inf")
    for t in HUMAN_THRESHOLDS:
        dist = abs(math.log(value / t))
        if dist < best_dist:
            best, best_dist = t, dist
    return best


# ---------------------------------------------------------------------------
# Activity roll-up
# ---------------------------------------------------------------------------


def parse_date(value: Any) -> _dt.date | None:
    s = str(value or "").strip()
    if not s:
        return None
    s = s.replace("Z", "").split("T")[0].split(" ")[0]
    try:
        return _dt.date.fromisoformat(s[:10])
    except ValueError:
        return None


def load_activity(
    raw: Path,
    window_days: int = 90,
    today: _dt.date | None = None,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Roll `_raw/activity/*.csv` up to per-(rep_email, account_domain) counts.

    Every event file has the same shape: `source,rep_email,account_domain,kind,ts`.
    The agent already pulls inside the window; the cutoff here is a backstop so a
    wider pull can't silently inflate "worked". An unparseable timestamp is
    COUNTED (better to over-credit activity than to wrongly propose moving an
    account someone is actively working) but contributes no last-activity date.
    """
    today = today or _dt.date.today()
    cutoff = today - _dt.timedelta(days=max(1, int(window_days)))
    out: dict[tuple[str, str], dict[str, Any]] = {}
    act_dir = raw / "activity"
    if not act_dir.exists():
        return out
    for path in sorted(act_dir.glob("*.csv")):
        default_source = path.stem
        for row in read_csv(path):
            rep = norm_email(row.get("rep_email"))
            dom = norm_domain(row.get("account_domain"))
            kind = str(row.get("kind") or "").strip().lower()
            if not rep or not dom or kind not in ACTIVITY_KINDS:
                continue
            ts = parse_date(row.get("ts"))
            if ts is not None and ts < cutoff:
                continue
            key = (rep, dom)
            bucket = out.setdefault(
                key,
                {k: 0 for k in ACTIVITY_KINDS} | {"last_activity_date": "", "sources": set()},
            )
            bucket[kind] += 1
            bucket["sources"].add(str(row.get("source") or default_source))
            if ts is not None:
                prev = bucket["last_activity_date"]
                iso = ts.isoformat()
                if not prev or iso > prev:
                    bucket["last_activity_date"] = iso
    return out


def activity_for(
    activity: dict[tuple[str, str], dict[str, Any]],
    rep_email: str,
    domains: Iterable[str],
) -> dict[str, Any]:
    """Sum one rep's activity across every domain an account is known by (a CRM
    duplicate or a Sumble-matched url can give the same org two domains)."""
    totals: dict[str, Any] = {k: 0 for k in ACTIVITY_KINDS}
    totals["last_activity_date"] = ""
    sources: set[str] = set()
    rep = norm_email(rep_email)
    if rep:
        for dom in {norm_domain(d) for d in domains if d}:
            bucket = activity.get((rep, dom))
            if not bucket:
                continue
            for k in ACTIVITY_KINDS:
                totals[k] += int(bucket.get(k, 0))
            sources |= set(bucket.get("sources") or ())
            last = bucket.get("last_activity_date") or ""
            if last > totals["last_activity_date"]:
                totals["last_activity_date"] = last
    totals["activity_sources"] = "|".join(sorted(sources))
    totals["outbound_total"] = sum(int(totals[k]) for k in OUTBOUND_KINDS)
    return totals


# ---------------------------------------------------------------------------
# Book balance
# ---------------------------------------------------------------------------


def book_stats(
    rows: list[dict[str, Any]],
    reps: list[dict[str, Any]],
    include_categories: Iterable[str] = DEFAULT_BALANCE_CATEGORIES,
    owner_field: str = "owner",
) -> dict[str, dict[str, Any]]:
    """Per-segment balance stats keyed by segment → {reps: {...}, cv, label}.

    `owner_field` lets a caller measure the book AFTER proposed moves (pass the
    effective-owner field) without duplicating the maths.
    """
    cats = set(include_categories)
    by_segment: dict[str, dict[str, Any]] = {}
    rep_segment = {norm_email(r.get("email")): str(r.get("segment") or "") for r in reps}
    rep_name_segment = {str(r.get("name") or ""): str(r.get("segment") or "") for r in reps}

    for r in reps:
        if not truthy(r.get("is_rep", "1")):
            continue
        seg = str(r.get("segment") or "")
        if not seg:
            continue
        entry = by_segment.setdefault(seg, {"reps": {}, "cv": 0.0, "label": "balanced"})
        entry["reps"][str(r.get("name") or "")] = {
            "name": str(r.get("name") or ""),
            "email": norm_email(r.get("email")),
            "n_accounts": 0,
            "sum_score": 0.0,
            "worked": 0,
            "top_quartile": 0,
            "sum_pipeline": 0.0,
        }

    scored = [to_float(r.get("score")) for r in rows if str(r.get("account_category") or "") in cats]
    p75 = percentile(scored, 0.75)

    for row in rows:
        if str(row.get("account_category") or "") not in cats:
            continue
        owner = str(row.get(owner_field) or "")
        if not owner:
            continue
        seg = rep_name_segment.get(owner) or rep_segment.get(norm_email(row.get("owner_email"))) or ""
        entry = by_segment.get(seg)
        if not entry or owner not in entry["reps"]:
            continue
        book = entry["reps"][owner]
        score = to_float(row.get("score"))
        book["n_accounts"] += 1
        book["sum_score"] += score
        book["sum_pipeline"] += to_float(row.get("pipeline_value"))
        if truthy(row.get("worked")):
            book["worked"] += 1
        if score >= p75:
            book["top_quartile"] += 1

    for entry in by_segment.values():
        sums = [b["sum_score"] for b in entry["reps"].values()]
        entry["cv"] = coefficient_of_variation(sums)
        entry["label"] = balance_label(entry["cv"])
        entry["mean_sum_score"] = (sum(sums) / len(sums)) if sums else 0.0
        entry["max_min_ratio"] = (max(sums) / min(sums)) if sums and min(sums) > 0 else 0.0
        for b in entry["reps"].values():
            b["sum_score"] = round(b["sum_score"], 3)
            b["worked_pct"] = round(100.0 * b["worked"] / b["n_accounts"], 1) if b["n_accounts"] else 0.0
    return by_segment
