"""Sumble account-scoring app — zero-dependency.

Runs on any stock Python 3.10+ install: `python app.py` and it's up.
No pip install, no venv. Stdlib only: csv, json, math, http.server.

Reads account-scoring-weights.json + data.csv at startup, builds derived
signals, log-normalises each signal, and serves a single-page UI that
recomputes scores client-side on every slider change. The spec is the
single source of truth: the Save button writes slider edits back into it
(and regenerates score.csv; data.csv stays the immutable raw file) — no auto-save.

Per-customer customisation lives in account-scoring-weights.json + data.csv;
this file stays the same across customers.
"""

from __future__ import annotations

import csv
import gzip
import json
import math
import os
import sys
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import score_sheet  # sibling module: writes data.csv (sorted) + score.csv

APP_DIR = Path(__file__).resolve().parent

# Single source of truth: the scoring spec AND the saved weights live in one
# file. Save mutates `default_pct` / `default_within` in place; resetDefaults()
# on the client reads those same fields, so reloading the app shows the last
# saved state without any separate snapshot.
SPEC_PATH = APP_DIR / "account-scoring-weights.json"
SPEC_TMP_PATH = APP_DIR / "account-scoring-weights.json.tmp"


# ---------- CSV loading + type coercion ------------------------------------


def _coerce(v: str | None) -> Any:
    if v is None:
        return None
    s = v.strip()
    if s == "":
        return None
    sl = s.lower()
    if sl in ("true", "t"):
        return True
    if sl in ("false", "f"):
        return False
    try:
        i = int(s)
        if str(i) == s:
            return i
    except (ValueError, TypeError):
        pass
    try:
        f = float(s)
    except (ValueError, TypeError):
        return s
    # Reject non-finite floats: strings like "Infinity"/"inf"/"NaN" are org
    # names (e.g. the company "Infinity"), not numbers. Leaving them as floats
    # makes json.dumps emit bare Infinity/NaN tokens that break JSON.parse.
    return f if math.isfinite(f) else s


def read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")
    with path.open(newline="", encoding="utf-8") as f:
        return [{k: _coerce(v) for k, v in row.items()} for row in csv.DictReader(f)]


# ---------- Derived signals ------------------------------------------------


def apply_derived(rows: list[dict[str, Any]], specs: list[dict[str, Any]]) -> None:
    for spec in specs:
        kind = spec.get("type", "ratio")
        output = spec["output"]
        scale = float(spec.get("scale", 1.0))
        if kind == "ratio":
            num_col, den_col = spec["numerator"], spec["denominator"]
            for r in rows:
                num = float(r.get(num_col) or 0)
                den = float(r.get(den_col) or 0)
                r[output] = (scale * num / den) if den else 0.0
        elif kind == "growth":
            cur_col, base_col = spec["current"], spec["baseline"]
            floor = float(spec.get("floor", 0))
            for r in rows:
                cur = float(r.get(cur_col) or 0)
                base = float(r.get(base_col) or 0)
                diff = max(cur - base, floor)
                r[output] = scale * diff / max(base, 1.0)
        else:
            raise ValueError(f"Unknown derived signal type: {kind}")


# ---------- Normalisation (p99 exponential saturation) ---------------------
#
# Mirrors data-pipeline/data_pipeline/score_accounts.py:
#   x_transformed = raw_value if transform=="linear" (growth-like)
#                   else ln(1 + max(raw_value, 0))   (count-like)
#   p99 = 99th percentile of x_transformed across rows where raw_value > 0
#   norm = clamp((1 - exp(-x_transformed / p99)) / (1 - exp(-1)), 0, 1)
#
# The (1 - exp(-1)) divisor rescales so an org at p99 gets exactly 1.0
# (otherwise it would saturate at 1 - 1/e ~= 0.632). The outer clamp
# handles the ~1% above p99 and any negative growth values.


def _p99(values: list[float]) -> float:
    if not values:
        return 1e-9
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(0.99 * len(s))))
    return max(s[idx], 1e-9)


def normalise(
    rows: list[dict[str, Any]], signals: dict[str, dict[str, Any]]
) -> dict[str, float]:
    p99s: dict[str, float] = {}
    scale = 1.0 - math.exp(-1.0)
    for key, spec in signals.items():
        col = spec["column"]
        transform = spec.get("transform", "log")
        raws = [float(r.get(col) or 0) for r in rows]
        # Recency: a "lower is better" signal (days since last financing). p99 is
        # the 99th percentile of positive raw days; norm decays with log(days) and
        # a non-positive raw (never financed) scores 0.
        if transform == "recency":
            p99 = _p99([v for v in raws if v > 0])
            p99s[key] = p99
            denom = math.log1p(max(p99, 1.0))
            for r, v_raw in zip(rows, raws):
                r[f"raw_{key}"] = v_raw
                if v_raw <= 0 or denom <= 0:
                    r[f"norm_{key}"] = 0.0
                else:
                    n = 1.0 - math.log1p(v_raw) / denom
                    r[f"norm_{key}"] = max(0.0, min(n, 1.0))
            continue
        is_linear = transform == "linear"
        xs = [v if is_linear else math.log1p(max(v, 0.0)) for v in raws]
        positive_xs = [x for v, x in zip(raws, xs) if v > 0]
        p99 = _p99(positive_xs)
        p99s[key] = p99
        for r, v_raw, x in zip(rows, raws, xs):
            r[f"raw_{key}"] = v_raw
            # Cap the exponent so large negative x (linear-transform signals
            # like growth_yoy) doesn't overflow when p99 collapsed to its
            # 1e-9 floor because no positive values exist in the calibration
            # sample. The capped value still produces n << 0, which the outer
            # clamp pins to 0 — same semantic, no OverflowError.
            arg = min(-x / p99, 700.0)
            n = (1.0 - math.exp(arg)) / scale
            r[f"norm_{key}"] = max(0.0, min(n, 1.0))
    return p99s


# ---------- Saved weights (account-scoring-weights.json) -------------------
#
# The Save button POSTs the current slider weights; the server merges them
# with config-derived metadata and writes account-scoring-weights.json. On
# the next startup load_state() re-reads that file so the app re-opens with
# the saved weights. The file is also a stand-alone scoring spec — it carries
# the formula, the per-signal column mapping, and the data-source metadata,
# so a coding agent can read it and re-implement the score elsewhere.


SCORING_FORMULA: dict[str, Any] = {
    "summary": (
        "final_score = 100 * sum over signals of "
        "(norm * section_weight_pct/100 * within_section_weight_pct/100 "
        "* within_category_weight_pct/100) "
        "* product over penalties of (1 - penalty_pct/100)"
    ),
    "normalisation": {
        "method": "p99_exponential_saturation",
        "steps": [
            "transform: x = ln(1 + max(raw, 0)) when transform='log'; "
            "x = raw when transform='linear'",
            "p99 = 99th percentile of x across rows where raw > 0",
            "norm = clamp((1 - exp(-x / p99)) / (1 - exp(-1)), 0, 1)",
        ],
        "notes": (
            "An org at p99 scores exactly 1.0; the outer clamp absorbs the "
            "top ~1% and any negative growth values."
        ),
    },
    "penalty": (
        "Penalties stack multiplicatively: final_multiplier = "
        "product of (1 - penalty_pct/100), always in [0, 1]. Applied only "
        "to rows where the penalty flag column is truthy."
    ),
    "weights": (
        "section_weight_pct values sum to 100 across sections. Inside each "
        "section, within_section_weight_pct values sum to 100 across "
        "categories. Inside each category, within_category_weight_pct "
        "values sum to 100 across signals. effective_weight_pct = "
        "section * within_section * within_category / 10000."
    ),
    "reference_implementation": "data-pipeline/data_pipeline/score_accounts.py",
}


def save_weights(state_config: dict[str, Any], weights: dict[str, Any]) -> dict[str, Any]:
    """Persist the slider weights to account-scoring-weights.json.

    Reads the current on-disk spec (which carries structural fields like
    data_csv / data_sources / scoring_formula that the trimmed in-memory
    state.config doesn't keep), mutates only the weight-bearing fields, and
    atomically writes it back. Then mirrors the same mutations into the
    in-memory state.config so /api/data reflects the saved state without
    a reload."""
    on_disk = json.loads(SPEC_PATH.read_text())

    sec_pct = weights.get("sections", {})
    cat_pct = weights.get("categories", {})
    within_pct = weights.get("signals", {})
    mult_pct = weights.get("multipliers", {})
    tag_mult = weights.get("tag_multipliers", []) or []

    for target in (on_disk, state_config):
        for key, val in sec_pct.items():
            if key in target.get("sections", {}):
                target["sections"][key]["default_pct"] = round(float(val or 0), 2)
        for key, val in cat_pct.items():
            if key in target.get("categories", {}):
                target["categories"][key]["default_pct"] = round(float(val or 0), 2)
        for key, val in within_pct.items():
            if key in target.get("signals", {}):
                target["signals"][key]["default_within"] = round(float(val or 0), 2)
        for m in target.get("multipliers", []):
            col = m.get("column")
            if col in mult_pct:
                m["default_pct"] = round(float(mult_pct[col] or 0), 2)

    normalised_tag_mult = [
        {
            "tag": str(e.get("tag", "")),
            "pct": round(float(e.get("pct", 0) or 0), 2),
            "direction": e.get("direction", "penalty"),
        }
        for e in tag_mult
        if isinstance(e, dict) and e.get("tag")
    ]
    on_disk["tag_multipliers"] = normalised_tag_mult
    state_config["tag_multipliers"] = normalised_tag_mult

    saved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    on_disk["saved_at"] = saved_at
    state_config["saved_at"] = saved_at

    SPEC_TMP_PATH.write_text(json.dumps(on_disk, indent=2, default=str))
    os.replace(SPEC_TMP_PATH, SPEC_PATH)
    return on_disk


# ---------- Bootstrap ------------------------------------------------------


# account_category precedence when the same Sumble org appears more than once
# (duplicate CRM records, or a whitespace candidate that also sits in the CRM):
# keep the most "owned" category so the Evaluation tab keeps its positives and a
# real CRM account never shows up as whitespace.
_CATEGORY_RANK = {
    "customer": 4,
    "allocated": 3,
    "unallocated": 2,
    "whitespace_subsidiary": 1,
    "whitespace": 0,
}


def _category_rank(row: dict[str, Any]) -> int:
    if row.get("is_icp_gold"):
        return _CATEGORY_RANK["customer"]
    return _CATEGORY_RANK.get(str(row.get("account_category") or ""), 0)


def _dedup_by_org(rows: list[dict[str, Any]], id_col: str) -> list[dict[str, Any]]:
    """Collapse rows that resolve to the same Sumble org (duplicate CRM records)
    to one row per org_id, preferring the highest-precedence category (customer >
    allocated > unallocated > whitespace). The on-disk data.csv is untouched (it
    keeps the full data); this only affects what the app loads, scores, and shows."""
    best: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for r in rows:
        key = str(r.get(id_col))
        if key not in best:
            best[key] = r
            order.append(key)
        elif _category_rank(r) > _category_rank(best[key]):
            best[key] = r
    return [best[k] for k in order]


def load_state() -> dict[str, Any]:
    if not SPEC_PATH.exists():
        raise FileNotFoundError(
            f"{SPEC_PATH.name} not found at {SPEC_PATH}. "
            "Generate via the sumble-account-scoring skill."
        )
    config = json.loads(SPEC_PATH.read_text())

    id_col = config.get("id_column", "org_id")
    # The skill emits ONE aggregated CSV (data.csv) — every row is already in
    # the calibration sample, so there's no separate CRM-overlay merge step.
    universe = read_csv(APP_DIR / config["data_csv"])
    # Show unique Sumble matches: duplicated CRM records that map to the same org
    # collapse to one row (data.csv on disk still holds every row).
    universe = _dedup_by_org(universe, id_col)
    # in_crm is derived from account_category (the single source of truth):
    # everything except whitespace is in the CRM. When no CRM was provided
    # (Branch B) account_category is blank for every row → all in_crm True,
    # has_categories False, and the category column/chips stay hidden.
    for r in universe:
        cat = str(r.get("account_category") or "")
        r["account_category"] = cat
        r["in_crm"] = cat in ("customer", "allocated", "unallocated")

    apply_derived(universe, config.get("derived_signals", []))
    maxes = normalise(universe, config["signals"])

    name_col = config.get("name_column", "name")
    slug_col = config.get("slug_column", "slug")
    table_cols = list(config.get("table_columns") or [name_col])
    # url is always shown — auto-inject if the data has it and the config
    # omitted it, so older weight files keep working without manual edits.
    if "url" not in table_cols and any("url" in r for r in universe[:50]):
        table_cols.insert(1, "url") if name_col in table_cols else table_cols.append("url")
    multipliers = config.get("multipliers", [])
    categories = config.get("categories", {})
    sections = config.get("sections", {})

    # `tags` is always passed through to the client so the per-tag multiplier
    # UI can intersect each row's tags against the active picker selections.
    passthrough_cols: list[str] = []
    seen: set[str] = set()
    for c in [
        id_col,
        name_col,
        slug_col,
        "in_crm",
        "is_icp_gold",
        "account_category",
        "tags",
        *table_cols,
        *[m["column"] for m in multipliers],
    ]:
        if c and c not in seen and any(c in r for r in universe[:50]):
            passthrough_cols.append(c)
            seen.add(c)

    rows_out = [_row_payload(r, config, passthrough_cols, multipliers) for r in universe]

    # Which account categories are present (customer/allocated/unallocated/
    # whitespace). The client shows the Category column + filter chips ONLY when
    # ≥2 distinct non-blank categories exist; a single-category (or Branch B
    # blank) run keeps the table clean.
    _cat_order = [
        "customer",
        "allocated",
        "unallocated",
        "whitespace",
        "whitespace_subsidiary",
    ]
    present = {str(r.get("account_category") or "") for r in universe}
    categories_present = [c for c in _cat_order if c in present]
    has_categories = len(categories_present) >= 2

    # Build the universe-wide tag catalogue. Tag column is a pipe-delimited
    # string ("b2b|b2c|digital_native"); split, count, sort by frequency
    # descending, then alphabetically for ties. The client renders this as a
    # datalist for the tag-multiplier picker — users see common tags first.
    tag_freq: dict[str, int] = {}
    for r in universe:
        raw = r.get("tags") or ""
        if not raw:
            continue
        for t in str(raw).split("|"):
            t = t.strip()
            if t:
                tag_freq[t] = tag_freq.get(t, 0) + 1
    available_tags: list[dict[str, Any]] = sorted(
        ({"tag": t, "count": c} for t, c in tag_freq.items()),
        key=lambda x: (-int(x["count"]), str(x["tag"])),
    )

    return {
        "config": {
            "customer_name": config.get("customer_name", ""),
            "score_label": config.get("score_label", "Score"),
            "id_column": id_col,
            "name_column": name_col,
            "slug_column": slug_col,
            "sumble_url_base": config.get("sumble_url_base", "https://sumble.com/orgs/"),
            "table_columns": table_cols,
            "sections": sections,
            "categories": categories,
            "signals": config["signals"],
            "multipliers": multipliers,
            "tag_multipliers": config.get("tag_multipliers", []),
            "available_tags": available_tags,
            "has_crm": True,
            "has_categories": has_categories,
            "categories_present": categories_present,
            "branding": config.get("branding", {}),
            "data_sources": config.get("data_sources", {}),
            "saved_at": config.get("saved_at"),
        },
        "maxes": maxes,
        "rows": rows_out,
    }


def _row_payload(
    row: dict[str, Any],
    config: dict[str, Any],
    passthrough: list[str],
    multipliers: list[dict[str, Any]],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for c in passthrough:
        v = row.get(c)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            out[c] = None
        else:
            out[c] = v
    out["in_crm"] = bool(row.get("in_crm", False))
    # Concentration signals (persona "% of company", tech "team share") have no
    # Sumble page that shows that share view, so they get no deep link — their
    # {column}_link is intentionally not passed through.
    no_link_categories = {
        "icp_persona_concentration",
        "relevant_tech_team_concentration",
    }
    for key, spec in config["signals"].items():
        out[f"norm_{key}"] = float(row.get(f"norm_{key}", 0) or 0)
        out[f"raw_{key}"] = float(row.get(f"raw_{key}", 0) or 0)
        # Per-signal Sumble deep link ({column}_link in data.csv). The client
        # reads row[`${spec.column}_link`] to turn each breakdown row into a
        # link; without this passthrough the columns are stripped and the
        # signals render as plain text.
        if spec.get("category") in no_link_categories:
            continue
        link_col = f"{spec['column']}_link"
        if link_col in row:
            out[link_col] = row.get(link_col) or None
    # Org-level link the breakdown header uses for "Open in Sumble →".
    if "sumble_url" in row:
        out["sumble_url"] = row.get("sumble_url") or None
    for m in multipliers:
        out[m["column"]] = bool(row.get(m["column"]) or False)
    return out


STATE = load_state()


# ---------- HTTP server ----------------------------------------------------


STATIC_DIR = APP_DIR / "static"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self) -> None:  # noqa: N802 (stdlib name)
        if self.path in ("/", "/index.html"):
            self.path = "/index.html"
            return super().do_GET()
        if self.path == "/api/data":
            return self._send_json(STATE)
        if self.path.startswith("/api/row/"):
            org_id = self.path[len("/api/row/") :]
            id_col = STATE["config"]["id_column"]
            for r in STATE["rows"]:
                if str(r.get(id_col)) == org_id:
                    return self._send_json(r)
            self.send_error(404, "org not found")
            return
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 (stdlib name)
        if self.path != "/api/save-weights":
            self.send_error(404, "not found")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError) as e:
            self.send_error(400, f"bad request: {e}")
            return
        try:
            payload = save_weights(STATE["config"], body)
        except OSError as e:
            self.send_error(500, f"could not write weights file: {e}")
            return
        # Explicit Save recomputes the full model server-side from the just-saved
        # weights and (re)writes score.csv (identity + score + rank + per-signal
        # contribution columns, far right, zero-contribution signals dropped).
        # data.csv is the immutable raw API-pull file and is NOT modified.
        rows_scored = 0
        try:
            rows_scored = score_sheet.build_score_sheet(APP_DIR, SPEC_PATH).get("rows", 0)
        except OSError as e:
            self.send_error(500, f"could not write score.csv: {e}")
            return
        print(
            f"[weights] saved {SPEC_PATH.name}; {rows_scored} rows → score.csv",
            file=sys.stderr,
        )
        self._send_json(
            {
                "ok": True,
                "saved_to": SPEC_PATH.name,
                "saved_at": payload["saved_at"],
                "rows_scored": rows_scored,
            }
        )

    def _send_json(self, data: Any) -> None:
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        # gzip when the client accepts it: the full /api/data sheet can exceed
        # Cloud Run's ~32 MB HTTP/1 response cap uncompressed (and it's faster).
        if "gzip" in (self.headers.get("Accept-Encoding") or ""):
            body = gzip.compress(body)
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self) -> None:
        # Force static assets (app.js/style.css/index.html) to revalidate so
        # edits always take effect on a normal refresh — no stale CSS/JS.
        if self.command == "GET" and not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache, max-age=0, must-revalidate")
        super().end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # quieter access log
        sys.stderr.write(f"  {self.address_string()} {format % args}\n")


def main() -> None:
    port = int(os.environ.get("PORT", sys.argv[1] if len(sys.argv) > 1 else "8001"))
    host = os.environ.get("HOST", "127.0.0.1")
    customer = STATE["config"].get("customer_name") or "Account"
    n = len(STATE["rows"])
    crm = sum(1 for r in STATE["rows"] if r["in_crm"])
    # Generate data.csv (sorted) + score.csv up front so they exist before any Save.
    try:
        score_sheet.build_score_sheet(APP_DIR, SPEC_PATH)
    except OSError as e:
        print(f"[score_sheet] skipped at startup: {e}", file=sys.stderr)
    print(f"{customer} scoring · {n:,} rows · {crm:,} in CRM", file=sys.stderr)
    print(f"http://{host}:{port}/", file=sys.stderr)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
