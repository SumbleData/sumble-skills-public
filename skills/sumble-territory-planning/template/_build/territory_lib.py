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

# An account is "strong" (for the strong-but-idle / strong-but-unallocated
# attention flags) if it is among the top-N accounts by ICP score. Global, not
# per-segment — "the strongest accounts nobody is working" is a book-wide
# question. Adjustable live in the app; this is the default / CSV baseline.
DEFAULT_STRONG_CUTOFF = 500

# Weight the TOP DECILE of a segment gets, relative to the rest of the top
# quartile (=1), in the Overview's Capture / Activation metrics. 2 = a top-decile
# account counts double. Purely a display metric, computed in the app.
DEFAULT_TIER_DECILE_WEIGHT = 2


def rep_in_balance(rep: dict[str, Any]) -> bool:
    """Whether this rep's book counts toward segment balance.

    Defaults to True. Set `in_balance=0` for a player-coach — a sales leader
    who legitimately owns accounts but whose book should not be measured for
    fairness, nor have accounts moved off it. They stay fully visible
    everywhere else: they still own their accounts, their activity still
    counts, and their accounts are still allocated rather than unallocated.
    """
    return truthy(rep.get("in_balance", "1"))


def effective_capacity(
    rep: dict[str, Any], segments: Iterable[dict[str, Any]]
) -> int | None:
    """Max accounts this rep may hold: their own `capacity`, else their
    segment's `default_capacity`, else unlimited (None).

    Segment-level defaults exist so a cap can be stated the way sales leaders
    actually state it ("enterprise reps carry 50, commercial 150") instead of
    being duplicated onto every rep row and drifting out of sync.
    """
    own = rep.get("capacity")
    if str(own or "").strip():
        return to_int(own)
    seg_key = str(rep.get("segment") or "")
    for seg in segments:
        if str(seg.get("key")) == seg_key:
            default = seg.get("default_capacity")
            if str(default or "").strip():
                return to_int(default)
            break
    return None


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
            # A player-coach stays visible here — their book, coverage and
            # activity are all still reported — but is left out of the CV
            # below, so one deliberately odd-shaped book doesn't read as the
            # segment being unfair.
            "in_balance": rep_in_balance(r),
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
        sums = [b["sum_score"] for b in entry["reps"].values() if b["in_balance"]]
        # A CV over fewer than two books is not a fairness reading — it is 0 by
        # construction. Callers surface `n_in_balance` so "balanced" is never
        # reported for a segment that only has one measured rep.
        entry["n_in_balance"] = len(sums)
        entry["cv"] = coefficient_of_variation(sums)
        entry["label"] = balance_label(entry["cv"])
        entry["mean_sum_score"] = (sum(sums) / len(sums)) if sums else 0.0
        entry["max_min_ratio"] = (max(sums) / min(sums)) if sums and min(sums) > 0 else 0.0
        for b in entry["reps"].values():
            b["sum_score"] = round(b["sum_score"], 3)
            b["worked_pct"] = round(100.0 * b["worked"] / b["n_accounts"], 1) if b["n_accounts"] else 0.0
    return by_segment


# =====================================================================
# Calibration + the move engine
#
# Both live here rather than in `suggest_moves.py` so the CLI and the app
# drive EXACTLY the same code. The app is stdlib-only and imports this module
# as a sibling; duplicating the four phases in JavaScript (or re-shelling to
# the CLI) is how the bars and the export start disagreeing with each other.
# =====================================================================

WHITESPACE_CATEGORIES = {"whitespace", "whitespace_subsidiary"}
FROZEN_STATUSES = {"accepted", "rejected", "manual"}


def recompute_segments(plan: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    """Re-derive every boundary-dependent field, in place.

    Called after the segment threshold changes — from the app's calibration
    panel, or by `merge_territory.py` when the sheet is first built. Sets
    `account_segment`, `segment_misfit` and `strong_idle`.

    `strong_idle` = one of the top-`strong_cutoff` accounts by ICP score
    (a global cutoff, default 500), owned, and not worked — the strongest
    accounts nobody is working. The app recomputes this live from the sidebar
    cutoff; this keeps the exported CSV consistent with the default.
    """
    segments = plan["segments"]
    boundary = plan["boundary"]
    cutoff = to_int(plan.get("strong_cutoff"), DEFAULT_STRONG_CUTOFF) or DEFAULT_STRONG_CUTOFF

    for row in rows:
        row["account_segment"] = segment_for_size(
            to_float(row.get("size_metric")), boundary, segments
        )
        owner = str(row.get("owner") or "")
        rep_seg = str(row.get("rep_segment") or "")
        acct_seg = str(row.get("account_segment") or "")
        row["segment_misfit"] = (
            1 if (owner and rep_seg and acct_seg and rep_seg != acct_seg) else 0
        )
        row["strong_idle"] = 0

    # "Strong" = top-N by score across all real (non-whitespace) accounts.
    ranked = sorted(
        (r for r in rows if str(r.get("account_category") or "") not in WHITESPACE_CATEGORIES),
        key=lambda r: -to_float(r.get("score")),
    )
    strong_ids = {str(r.get("org_id")) for r in ranked[:cutoff]}
    for r in rows:
        if (
            str(r.get("org_id")) in strong_ids
            and str(r.get("owner") or "")
            and not truthy(r.get("worked"))
        ):
            r["strong_idle"] = 1


def effective_owner(row: dict[str, Any]) -> str:
    """Who owns the account once the user's accepted/manual decisions are
    applied — what the balance maths must measure against."""
    if str(row.get("proposal_status") or "") in ("accepted", "manual"):
        return str(row.get("proposed_owner") or "") or str(row.get("owner") or "")
    return str(row.get("owner") or "")


class Books:
    """Per-rep load inside one segment, kept incrementally so a greedy pass
    doesn't rescan the whole sheet after every move."""

    def __init__(
        self,
        reps: list[dict[str, Any]],
        rows: list[dict[str, Any]],
        balance_cats: set[str],
    ) -> None:
        self.reps = {r["name"]: r for r in reps}
        self.sum_score: dict[str, float] = {r["name"]: 0.0 for r in reps}
        self.n_accounts: dict[str, int] = {r["name"]: 0 for r in reps}
        for row in rows:
            owner = effective_owner(row)
            if owner in self.sum_score and str(row.get("account_category")) in balance_cats:
                self.sum_score[owner] += to_float(row.get("score"))
                self.n_accounts[owner] += 1

    def add(self, rep: str, score: float) -> None:
        if rep in self.sum_score:
            self.sum_score[rep] += score
            self.n_accounts[rep] += 1

    def remove(self, rep: str, score: float) -> None:
        if rep in self.sum_score:
            self.sum_score[rep] -= score
            self.n_accounts[rep] -= 1

    def cv(self) -> float:
        return coefficient_of_variation(list(self.sum_score.values()))

    def has_capacity(self, rep: str) -> bool:
        # `effective_capacity` is the rep's own cap falling back to their
        # segment's default; build_plan.py resolves it so every consumer agrees.
        entry = self.reps.get(rep, {})
        cap = entry.get("effective_capacity")
        if cap in (None, "", 0):
            cap = entry.get("capacity")
        if cap in (None, "", 0):
            return True
        return self.n_accounts.get(rep, 0) < to_int(cap)

    def most_underloaded(self) -> str:
        """Lightest book with room. Ties by name → deterministic."""
        candidates = [r for r in sorted(self.sum_score) if self.has_capacity(r)]
        if not candidates:
            return ""
        return min(candidates, key=lambda r: (self.sum_score[r], r))

    def donors_desc(self) -> list[str]:
        return sorted(self.sum_score, key=lambda r: (-self.sum_score[r], r))


def _is_movable(row: dict[str, Any]) -> bool:
    """An already-owned account that may be reassigned by the balancer."""
    return (
        not truthy(row.get("worked"))
        and str(row.get("proposal_status") or "") not in FROZEN_STATUSES
        and not str(row.get("proposed_owner") or "")
        and str(row.get("account_category")) not in WHITESPACE_CATEGORIES
        and str(row.get("account_category")) != "customer"
        and not truthy(row.get("double_allocated"))
        and bool(effective_owner(row))
    )


def _propose(row: dict[str, Any], new_owner: str, reason: str) -> None:
    row["proposed_owner"] = new_owner
    row["proposal_reason"] = reason
    row["proposal_status"] = "suggested"


def suggest_moves(
    plan: dict[str, Any], rows: list[dict[str, Any]], reset: bool = False
) -> dict[str, Any]:
    """Run the four move phases over `rows`, in place. Returns a report.

    Deterministic: same rows + same plan → byte-identical proposals. No RNG;
    every tie breaks on `org_id`.

    Phases run least-disruptive-first — misfit, unallocated, whitespace, then
    rebalance — because moving an account someone already has a relationship
    with costs more than assigning one nobody owns. The hard constraint
    everywhere: an account with activity is NEVER proposed for a move.

    Decisions the user already made (accepted / rejected / manual) survive
    unless `reset`, so re-running after a review session refines the plan
    instead of undoing it.
    """
    segments = plan["segments"]
    all_reps = [r for r in plan["reps"] if r.get("is_rep")]
    # A player-coach owns accounts but is not part of the fairness maths, so
    # they are neither donor nor recipient: excluding them from the books keeps
    # them off both sides of every proposed move.
    reps = [r for r in all_reps if rep_in_balance(r)]
    coach_names = {r["name"] for r in all_reps if not rep_in_balance(r)}
    policy = plan.get("move_policy") or {}
    cv_stop = to_float(policy.get("cv_stop"), CV_STOP)
    max_move_frac = to_float(policy.get("max_move_frac"), MAX_MOVE_FRAC)
    balance_cats = set(
        (plan.get("balance") or {}).get("include_categories", DEFAULT_BALANCE_CATEGORIES)
    )

    for row in rows:
        status = str(row.get("proposal_status") or "")
        if reset or status == "suggested":
            row["proposed_owner"] = ""
            row["proposal_reason"] = ""
            row["proposal_status"] = ""

    reps_by_segment: dict[str, list[dict[str, Any]]] = {}
    for r in reps:
        reps_by_segment.setdefault(str(r.get("segment") or ""), []).append(r)

    books = {
        seg["key"]: Books(reps_by_segment.get(seg["key"], []), rows, balance_cats)
        for seg in segments
    }
    cv_before = {k: b.cv() for k, b in books.items()}
    counts = {"misfit": 0, "assign_unallocated": 0, "assign_whitespace": 0, "rebalance": 0}
    skipped_worked_misfits = 0
    skipped_coach_misfits = 0

    def rows_sorted(pred) -> list[dict[str, Any]]:
        return sorted(
            [r for r in rows if pred(r)],
            key=lambda r: (-to_float(r.get("score")), str(r.get("org_id"))),
        )

    # --- Phase 1: misfits ----------------------------------------------------
    # Customers ARE eligible here, unlike in the rebalance phase. The difference
    # is principled: a misfit move is a correctness fix (an enterprise account
    # sitting with a commercial rep belongs with the enterprise team, and that is
    # as true for a customer as a prospect), while rebalancing is an optimisation
    # — and churning a customer purely to even out a spreadsheet is exactly the
    # move that costs a renewal.
    for row in rows_sorted(lambda r: truthy(r.get("segment_misfit"))):
        if truthy(row.get("worked")):
            skipped_worked_misfits += 1
            continue
        # A player-coach's book is deliberately odd-shaped — that is why they
        # were excluded from balance — so "wrong segment" is not evidence of a
        # mistake there, and stripping their accounts would contradict it.
        if effective_owner(row) in coach_names:
            skipped_coach_misfits += 1
            continue
        if str(row.get("proposal_status") or "") in FROZEN_STATUSES:
            continue
        target_seg = str(row.get("account_segment") or "")
        from_seg = str(row.get("rep_segment") or "")
        target = books.get(target_seg)
        if not target:
            continue
        new_owner = target.most_underloaded()
        old_owner = effective_owner(row)
        if not new_owner or new_owner == old_owner:
            continue
        score = to_float(row.get("score"))
        if str(row.get("account_category")) in balance_cats:
            if from_seg in books:
                books[from_seg].remove(old_owner, score)
            target.add(new_owner, score)
        _propose(row, new_owner, "misfit")
        counts["misfit"] += 1

    # --- Phase 2 + 3: assign unowned accounts, then net-new whitespace -------
    for reason, pred in (
        (
            "assign_unallocated",
            lambda r: truthy(r.get("unallocated"))
            and str(r.get("account_category")) not in WHITESPACE_CATEGORIES,
        ),
        (
            "assign_whitespace",
            lambda r: str(r.get("account_category")) in WHITESPACE_CATEGORIES,
        ),
    ):
        for row in rows_sorted(pred):
            if str(row.get("proposal_status") or "") in FROZEN_STATUSES or row.get(
                "proposed_owner"
            ):
                continue
            seg = str(row.get("account_segment") or "")
            book = books.get(seg)
            if not book:
                continue
            new_owner = book.most_underloaded()
            if not new_owner:
                continue
            score = to_float(row.get("score"))
            # Newly assigned accounts count toward the book immediately, so the
            # next assignment goes to whoever is now lightest — this is what
            # spreads a batch of unowned accounts instead of dumping them all on
            # one rep.
            book.add(new_owner, score)
            _propose(row, new_owner, reason)
            counts[reason] += 1

    # --- Phase 4: rebalance ---------------------------------------------------
    for seg in segments:
        key = seg["key"]
        book = books[key]
        if len(book.sum_score) < 2:
            continue
        seg_rows = [r for r in rows if str(r.get("account_segment")) == key]
        max_moves = int(max_move_frac * len(seg_rows))
        moved = 0
        exhausted: set[str] = set()
        while moved < max_moves and book.cv() > cv_stop:
            donor = next((d for d in book.donors_desc() if d not in exhausted), "")
            recipient = book.most_underloaded()
            if not donor or not recipient or donor == recipient:
                break
            gap = book.sum_score[donor] - book.sum_score[recipient]
            if gap <= 0:
                break
            candidates = [
                r for r in seg_rows if _is_movable(r) and effective_owner(r) == donor
            ]
            if not candidates:
                exhausted.add(donor)
                continue
            # The account that most nearly halves the gap: after the move the
            # difference becomes |gap - 2*score|, so minimise that.
            best = min(
                candidates,
                key=lambda r: (abs(gap - 2 * to_float(r.get("score"))), str(r.get("org_id"))),
            )
            score = to_float(best.get("score"))
            if abs(gap - 2 * score) >= gap:
                # Every remaining account is too big to help — moving it would
                # just invert the imbalance.
                exhausted.add(donor)
                continue
            book.remove(donor, score)
            book.add(recipient, score)
            _propose(best, recipient, "rebalance")
            counts["rebalance"] += 1
            moved += 1

    # Report the after-CV from a full recompute over the proposed allocation,
    # NOT from the incremental `books`. The greedy state deliberately counts
    # newly-assigned whitespace so successive assignments spread across reps,
    # but whitespace is outside the balance categories — so only a clean
    # book_stats pass matches what the app displays.
    proposed_rows = [
        dict(r, owner=(r.get("proposed_owner") or r.get("owner"))) for r in rows
    ]
    # `all_reps` here, not `reps`: book_stats itself drops player-coaches from
    # the CV, but they must still appear in the per-rep breakdown.
    after_stats = book_stats(proposed_rows, all_reps, balance_cats)

    # Unowned accounts the caps refused to place. Silence here would read as
    # "everything found a home", which is the opposite of the truth.
    unrouted: dict[str, int] = {}
    for seg in segments:
        key = seg["key"]
        left = sum(
            1
            for r in rows
            if str(r.get("account_segment")) == key
            and truthy(r.get("unallocated"))
            and not r.get("proposed_owner")
        )
        if left:
            unrouted[key] = left

    return {
        "counts": counts,
        "total": sum(counts.values()),
        "cv_before": cv_before,
        "after_stats": after_stats,
        "skipped_worked_misfits": skipped_worked_misfits,
        "skipped_coach_misfits": skipped_coach_misfits,
        "coach_names": sorted(coach_names),
        "unrouted": unrouted,
        "frozen": sum(
            1 for r in rows if str(r.get("proposal_status") or "") in FROZEN_STATUSES
        ),
    }
