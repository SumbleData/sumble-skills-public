"""Sumble account-whitespace app — zero-dependency.

Runs on any stock Python 3.10+ install: `python app.py` and it's up.
No pip install, no venv. Stdlib only: csv, json, math, http.server.

Reads account-whitespace-weights.json + data.csv at startup, builds
derived signals, log-normalises each signal, and serves a single-page
UI that recomputes scores client-side on every slider change and auto-
saves the weights back to the same JSON file (debounced, atomic).

This is the standalone whitespace app: a ranked Whitespace table with
sliders + breakdown + CSV download, plus an optional Subsidiaries tab
(rows whose `list_type` is `crm_subsidiary`). No evaluation view, no
first-party-data plumbing.
"""

from __future__ import annotations

import copy
import csv
import json
import math
import os
import sys
from datetime import datetime, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any

import score_sheet  # sibling module: writes data.csv (sorted) + score.csv

APP_DIR = Path(__file__).resolve().parent

# Single config file: the self-describing spec AND the tuned weights.
# Written atomically by the explicit Save button (no auto-save); Save also
# regenerates score.csv (data.csv stays the immutable raw API-pull file).
WEIGHTS_PATH = APP_DIR / "account-whitespace-weights.json"
WEIGHTS_TMP_PATH = APP_DIR / "account-whitespace-weights.json.tmp"


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
        return float(s)
    except (ValueError, TypeError):
        return s


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
#   x_transformed = raw_value if transform=="linear" (growth-like)
#                   else ln(1 + max(raw_value, 0))   (count-like)
#   p99 = 99th percentile of x_transformed across rows where raw_value > 0
#   norm = clamp((1 - exp(-x_transformed / p99)) / (1 - exp(-1)), 0, 1)


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
        is_linear = spec.get("transform", "log") == "linear"
        raws = [float(r.get(col) or 0) for r in rows]
        xs = [v if is_linear else math.log1p(max(v, 0.0)) for v in raws]
        positive_xs = [x for v, x in zip(raws, xs) if v > 0]
        p99 = _p99(positive_xs)
        p99s[key] = p99
        for r, v_raw, x in zip(rows, raws, xs):
            r[f"raw_{key}"] = v_raw
            n = (1.0 - math.exp(-x / p99)) / scale
            r[f"norm_{key}"] = max(0.0, min(n, 1.0))
    return p99s


# ---------- Saved weights (account-whitespace-weights.json) -------------------


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
}


def build_weights_file(config: dict[str, Any], weights: dict[str, Any]) -> dict[str, Any]:
    """Merge slider weights into a deep-copy of the in-memory config and
    return the dict-shape payload that round-trips through load_state.

    Critically, we preserve ALL metadata (p99, source, api_supported,
    sumble_link, transform, etc.) and only update the weight fields
    `default_pct` (sections/categories/multipliers) and `default_within`
    (signals). Tag multipliers replace wholesale from the UI list."""
    sec_pct = weights.get("sections", {}) or {}
    cat_pct = weights.get("categories", {}) or {}
    within_pct = weights.get("signals", {}) or {}
    mult_pct = weights.get("multipliers", {}) or {}
    tag_mult = weights.get("tag_multipliers", []) or []

    payload = copy.deepcopy(config)

    sections_cfg = payload.get("sections") or {}
    for key, spec in sections_cfg.items():
        if isinstance(spec, dict) and key in sec_pct:
            spec["default_pct"] = round(float(sec_pct[key]), 2)

    cats_cfg = payload.get("categories") or {}
    for key, spec in cats_cfg.items():
        if isinstance(spec, dict) and key in cat_pct:
            spec["default_pct"] = round(float(cat_pct[key]), 2)

    sigs_cfg = payload.get("signals") or {}
    for key, spec in sigs_cfg.items():
        if isinstance(spec, dict) and key in within_pct:
            spec["default_within"] = round(float(within_pct[key]), 2)

    for m in payload.get("multipliers") or []:
        if isinstance(m, dict) and m.get("column") in mult_pct:
            m["default_pct"] = round(float(mult_pct[m["column"]]), 2)

    payload["tag_multipliers"] = [
        {
            "tag": str(e.get("tag", "")),
            "pct": round(float(e.get("pct", 0) or 0), 2),
            "direction": e.get("direction", "penalty"),
        }
        for e in tag_mult
        if isinstance(e, dict) and e.get("tag")
    ]

    payload["saved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return payload


def _saved_weights_for_ui() -> dict[str, Any] | None:
    if not WEIGHTS_PATH.exists():
        return None
    try:
        saved = json.loads(WEIGHTS_PATH.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(
            f"[weights] ignoring unreadable {WEIGHTS_PATH.name}: {e}",
            file=sys.stderr,
        )
        return None
    sections_raw = saved.get("sections") or {}
    categories_raw = saved.get("categories") or {}
    signals_raw = saved.get("signals") or {}
    return {
        "sections": {
            k: (s.get("default_pct") or 0)
            for k, s in sections_raw.items()
            if isinstance(s, dict)
        },
        "categories": {
            k: (c.get("default_pct") or 0)
            for k, c in categories_raw.items()
            if isinstance(c, dict)
        },
        "signals": {
            k: (s.get("default_within") or 0)
            for k, s in signals_raw.items()
            if isinstance(s, dict)
        },
        "multipliers": {
            m["column"]: (m.get("default_pct") or 0)
            for m in (saved.get("multipliers") or [])
            if isinstance(m, dict) and "column" in m
        },
        "tag_multipliers": [
            {
                "tag": e.get("tag", ""),
                "pct": e.get("pct", 0),
                "direction": e.get("direction", "penalty"),
            }
            for e in (saved.get("tag_multipliers") or [])
            if isinstance(e, dict) and e.get("tag")
        ],
        "saved_at": saved.get("saved_at"),
    }


def save_weights(config: dict[str, Any], weights: dict[str, Any]) -> dict[str, Any]:
    """Write account-whitespace-weights.json atomically and return the payload."""
    payload = build_weights_file(config, weights)
    WEIGHTS_TMP_PATH.write_text(json.dumps(payload, indent=2, default=str))
    os.replace(WEIGHTS_TMP_PATH, WEIGHTS_PATH)
    return payload


def write_scored_csv(scores: list[dict[str, Any]]) -> int:
    """Persist the app's current scores into data.csv (full data preserved).

    `scores` is [{id, score, rank}, ...] keyed by org_id — the exact values the
    client is showing, so the saved file matches the app. (The portable
    score_accounts.py can differ because it drops non-API signals, so we take the
    client's numbers rather than recomputing.) Adds/updates `score` + `rank`
    columns; row count and all other columns are unchanged."""
    id_col = STATE["config"].get("id_column", "org_id")
    on_disk = json.loads(WEIGHTS_PATH.read_text())
    data_path = APP_DIR / on_disk.get("data_csv", "data.csv")
    if not data_path.exists():
        return 0
    by_id = {str(s.get("id")): s for s in (scores or [])}
    with data_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for col in ("score", "rank"):
        if col not in fieldnames:
            fieldnames.append(col)
    n = 0
    for r in rows:
        s = by_id.get(str(r.get(id_col)))
        if s is not None:
            r["score"] = s.get("score")
            r["rank"] = s.get("rank")
            n += 1
        else:
            r.setdefault("score", "")
            r.setdefault("rank", "")
    tmp = data_path.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, data_path)
    return n


# ---------- Bootstrap ------------------------------------------------------


def _migrate_list_shape_in_place(config: dict[str, Any]) -> None:
    """Migrate old list-shape (key/weight_pct) configs to the new dict shape
    (default_pct/default_within) so app.py keeps working when loading a
    file written by the prior buggy build_weights_file."""

    def _list_to_dict(items: Any, weight_field_old: str, weight_field_new: str) -> dict:
        out: dict[str, dict[str, Any]] = {}
        for item in items or []:
            if not isinstance(item, dict) or "key" not in item:
                continue
            key = item["key"]
            spec = {k: v for k, v in item.items() if k != "key"}
            if weight_field_old in spec:
                spec[weight_field_new] = spec.pop(weight_field_old)
            out[key] = spec
        return out

    if isinstance(config.get("sections"), list):
        config["sections"] = _list_to_dict(config["sections"], "weight_pct", "default_pct")
    if isinstance(config.get("categories"), list):
        config["categories"] = _list_to_dict(
            config["categories"], "within_section_weight_pct", "default_pct"
        )
    if isinstance(config.get("signals"), list):
        config["signals"] = _list_to_dict(
            config["signals"], "within_category_weight_pct", "default_within"
        )
    # Old "penalties" / "tag_penalties" → "multipliers" / "tag_multipliers"
    if "penalties" in config and "multipliers" not in config:
        config["multipliers"] = [
            {
                **{k: v for k, v in p.items() if k != "penalty_pct"},
                "default_pct": p.get("penalty_pct", 0),
            }
            for p in config.pop("penalties") or []
            if isinstance(p, dict)
        ]
    if "tag_penalties" in config and "tag_multipliers" not in config:
        config["tag_multipliers"] = config.pop("tag_penalties")


def load_state() -> dict[str, Any]:
    if not WEIGHTS_PATH.exists():
        raise FileNotFoundError(
            f"account-whitespace-weights.json not found at {WEIGHTS_PATH}. "
            "Generate via the account-whitespace skill."
        )
    config = json.loads(WEIGHTS_PATH.read_text())
    _migrate_list_shape_in_place(config)

    id_col = config.get("id_column", "org_id")
    universe = read_csv(APP_DIR / config.get("data_csv", "data.csv"))

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
        "tags",
        "list_type",
        "crm_parent_name",
        *table_cols,
        *[m["column"] for m in multipliers],
    ]:
        if c and c not in seen and any(c in r for r in universe[:50]):
            passthrough_cols.append(c)
            seen.add(c)

    rows_out = [_row_payload(r, config, passthrough_cols, multipliers) for r in universe]

    # Build the universe-wide tag catalogue. Tag column is a pipe-delimited
    # string ("b2b|b2c|digital_native"); split, count, sort by frequency
    # descending, then alphabetically for ties.
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
            "tag_multipliers": config.get("tag_multipliers", {}),
            "tag_multipliers_defaults": config.get("tag_multipliers_defaults", []),
            "available_tags": available_tags,
            "branding": config.get("branding", {}),
            "data_sources": config.get("data_sources", {}),
        },
        "maxes": maxes,
        "rows": rows_out,
        "saved_weights": _saved_weights_for_ui(),
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
    for key in config["signals"]:
        out[f"norm_{key}"] = float(row.get(f"norm_{key}", 0) or 0)
        out[f"raw_{key}"] = float(row.get(f"raw_{key}", 0) or 0)
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
            rows_scored = score_sheet.build_score_sheet(APP_DIR, WEIGHTS_PATH).get("rows", 0)
        except OSError as e:
            self.send_error(500, f"could not write score.csv: {e}")
            return
        STATE["saved_weights"] = _saved_weights_for_ui()
        print(
            f"[weights] saved {WEIGHTS_PATH.name}; {rows_scored} rows → score.csv (data.csv untouched)",
            file=sys.stderr,
        )
        self._send_json(
            {
                "ok": True,
                "saved_to": WEIGHTS_PATH.name,
                "saved_at": payload["saved_at"],
                "rows_scored": rows_scored,
            }
        )

    def _send_json(self, data: Any) -> None:
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
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
        sys.stderr.write(f"  {self.address_string()} {format % args}\n")


def main() -> None:
    port = int(os.environ.get("PORT", sys.argv[1] if len(sys.argv) > 1 else "8001"))
    host = os.environ.get("HOST", "127.0.0.1")
    customer = STATE["config"].get("customer_name") or "Whitespace"
    n = len(STATE["rows"])
    # Generate data.csv (sorted) + score.csv up front so they exist before any Save.
    try:
        score_sheet.build_score_sheet(APP_DIR, WEIGHTS_PATH)
    except OSError as e:
        print(f"[score_sheet] skipped at startup: {e}", file=sys.stderr)
    print(f"{customer} · {n:,} whitespace accounts", file=sys.stderr)
    print(f"http://{host}:{port}/", file=sys.stderr)
    HTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
