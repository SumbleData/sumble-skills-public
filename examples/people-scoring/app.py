"""Sumble people-scoring app — zero-dependency.

Runs on any stock Python 3.10+ install: `python app.py` and it's up.
No pip install, no venv. Stdlib only: csv, json, os, sys, http.server.

Reads config.json + data.csv at startup. Scoring is computed client-side
in JS so every slider change is instant.

The Save button POSTs the current slider state to /api/save-weights; the
server writes `people-scoring-weights.json` — a self-describing scoring
spec (formula + tuned weights + column mappings) that a coding agent can
read to re-implement the score in a production pipeline. config.json is
never modified; on the next startup the app overlays the saved weights
so it re-opens with the last saved state.

Per-customer customisation lives in config.json; this file stays generic.
"""

from __future__ import annotations

import csv
import gzip
import json
import os
import sys
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any

import score_sheet  # sibling module: regenerates score.csv on Save/startup

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
DATA_PATH = APP_DIR / "data.csv"
STATIC_DIR = APP_DIR / "static"

# Self-describing weights file: written by the Save button, re-read on
# startup so the app re-opens with the last saved weights. It is also a
# stand-alone scoring spec — it carries the formula, every tuned weight,
# the per-JF ranges and the 1P signal column mappings — so a coding agent
# can read it and re-implement the score elsewhere.
WEIGHTS_PATH = APP_DIR / "people-scoring-weights.json"
WEIGHTS_TMP_PATH = APP_DIR / "people-scoring-weights.json.tmp"


# ---------- CSV loading ----------------------------------------------------


def _coerce(v: str | None) -> Any:
    if v is None:
        return None
    s = v.strip()
    if s == "":
        return None
    if s.lower() in ("true", "t"):
        return True
    if s.lower() in ("false", "f"):
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


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as f:
        return [{k: _coerce(v) for k, v in row.items()} for row in csv.DictReader(f)]


# ---------- Self-describing weights file -----------------------------------


SCORING_FORMULA: dict[str, Any] = {
    "summary": (
        "total_score = w_jf * jf_score + w_seniority * seniority_score "
        "+ w_skills * skill_score + sum over 1P signals of "
        "(w_signal * signal_norm). Each weight is a fraction of 100 and "
        "the weights sum to 100; total_score lands in [0, 1] and the UI "
        "displays it x100."
    ),
    "factors": {
        "jf_score": (
            "seniority_frac = job_level_rank / max_job_level_rank; "
            "jf_score = jf_range[slug].min + (jf_range[slug].max - "
            "jf_range[slug].min) * seniority_frac. jf_range falls back to "
            "default_jf_range for job-function slugs not listed."
        ),
        "seniority_score": "job_level_rank / max_job_level_rank.",
        "skill_score": "min(skill_count, skill_cap) / skill_cap.",
        "one_p_signal": (
            "Each 1P signal contributes its <norm_column> value directly "
            "(already 0-1). norm is computed once at data.csv build time: "
            "x = ln(1 + max(raw, 0)); p99 = 99th percentile of x over rows "
            "where raw > 0; norm = clamp((1 - exp(-x / p99)) / "
            "(1 - exp(-1)), 0, 1)."
        ),
    },
    "reference": "notebooks/apps_mini/company_research/people_lead_score.py",
}


def _factor_meta(key: str, config: dict[str, Any]) -> dict[str, Any]:
    """Describe one scoring factor for the saved weights file."""
    one_p = {s.get("weight_key"): s for s in config.get("one_p_signals", [])}
    if key == "jf":
        return {
            "factor": "job_function",
            "description": (
                "Job-function fit interpolated between the per-JF min "
                "(score at IC) and max (score at CXO) by the person's "
                "seniority fraction — see job_function_ranges."
            ),
        }
    if key == "seniority":
        return {
            "factor": "seniority",
            "description": "job_level_rank / max_job_level_rank.",
        }
    if key == "skills":
        return {
            "factor": "skills",
            "description": "min(skill_count, skill_cap) / skill_cap.",
        }
    if key in one_p:
        sig = one_p[key]
        return {
            "factor": "one_p_signal",
            "description": (
                "First-party signal. Contributes the norm_column value "
                "directly (already 0-1, p99 log-saturation normalised at "
                "data.csv build time)."
            ),
            "raw_column": sig.get("raw_column"),
            "norm_column": sig.get("norm_column"),
            "transform": "p99_log_saturation",
            "unit": sig.get("unit"),
        }
    return {"factor": "unknown", "description": ""}


def build_weights_file(config: dict[str, Any]) -> dict[str, Any]:
    """Assemble the self-describing people-scoring-weights.json payload
    from the (slider-updated) config posted by the UI."""
    weights_out: list[dict[str, Any]] = []
    for key, spec in (config.get("weights") or {}).items():
        cur = spec.get("current", spec.get("default", 0))
        entry: dict[str, Any] = {
            "key": key,
            "label": spec.get("label", key),
            "weight_pct": round(float(cur or 0), 2),
        }
        entry.update(_factor_meta(key, config))
        weights_out.append(entry)
    return {
        "_comment": (
            "Saved people-scoring weights, generated by the "
            "sumble-people-scoring skill. This file is the source of truth "
            "for the scoring formula and tuned weights: a coding agent can "
            "read it to re-implement the score in a production pipeline. "
            "The app re-opens with these weights."
        ),
        "schema_version": 1,
        "company_name": config.get("customer_name", ""),
        "score_label": config.get("score_label", "Score"),
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "id_column": config.get("id_column", "person_id"),
        "scoring_formula": SCORING_FORMULA,
        "weights": weights_out,
        "job_function_ranges": config.get("job_function_ranges", {}),
        "default_jf_range": config.get("default_jf_range", {}),
        "skill_cap": config.get("skill_cap", 5),
        "seniority": config.get("seniority", {}),
        "one_p_signals": config.get("one_p_signals", []),
        "flags": config.get("flags", {}),
        "filters_applied": config.get("filters_applied", {}),
    }


def _apply_saved_weights(config: dict[str, Any]) -> str | None:
    """Overlay people-scoring-weights.json (if present) onto config so the
    app re-opens with the last saved weights. Returns saved_at or None."""
    if not WEIGHTS_PATH.exists():
        return None
    try:
        saved = json.loads(WEIGHTS_PATH.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"[weights] ignoring unreadable {WEIGHTS_PATH.name}: {e}", file=sys.stderr)
        return None
    weights = config.get("weights", {})
    for w in saved.get("weights", []):
        key = w.get("key")
        if key in weights and w.get("weight_pct") is not None:
            weights[key]["current"] = w["weight_pct"]
    jfr = config.get("job_function_ranges", {})
    for slug, rng in (saved.get("job_function_ranges") or {}).items():
        if slug in jfr:
            if rng.get("min") is not None:
                jfr[slug]["min"] = rng["min"]
            if rng.get("max") is not None:
                jfr[slug]["max"] = rng["max"]
    return saved.get("saved_at")


def save_weights(config: dict[str, Any]) -> dict[str, Any]:
    """Write people-scoring-weights.json atomically and return the payload."""
    payload = build_weights_file(config)
    WEIGHTS_TMP_PATH.write_text(json.dumps(payload, indent=2, default=str))
    os.replace(WEIGHTS_TMP_PATH, WEIGHTS_PATH)
    return payload


# ---------- Bootstrap ------------------------------------------------------


def _load_state() -> dict[str, Any]:
    config = json.loads(CONFIG_PATH.read_text())
    saved_at = _apply_saved_weights(config)
    rows = _read_csv(DATA_PATH)
    return {"config": config, "rows": rows, "saved_at": saved_at}


STATE = _load_state()


# ---------- HTTP server ----------------------------------------------------


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            self.path = "/index.html"
            return super().do_GET()
        if self.path == "/api/data":
            return self._send_json(STATE)
        if self.path == "/score.csv":
            return self._send_score_csv()
        return super().do_GET()

    def _send_score_csv(self) -> None:
        """Serve the score sheet (regenerated on every Save and at startup)."""
        path = APP_DIR / "score.csv"
        if not path.exists():
            self.send_error(404, "score.csv not generated yet — Save first")
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="score.csv"')
        if "gzip" in (self.headers.get("Accept-Encoding") or ""):
            body = gzip.compress(body)
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/save-weights":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError) as e:
            self.send_error(400, f"bad request: {e}")
            return
        try:
            payload = save_weights(body)
        except OSError as e:
            self.send_error(500, f"could not write weights file: {e}")
            return
        STATE["config"] = body
        STATE["saved_at"] = payload["saved_at"]
        # Regenerate the score sheet from the just-saved weights so score.csv
        # always matches what the user sees (data.csv stays untouched).
        try:
            sheet = score_sheet.build_score_sheet(APP_DIR, body)
            rows_scored = sheet.get("rows", 0)
        except (OSError, ValueError, KeyError) as e:
            print(f"[score_sheet] regeneration failed: {e}", file=sys.stderr)
            rows_scored = 0
        print(f"[weights] saved {WEIGHTS_PATH.name}", file=sys.stderr)
        return self._send_json(
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
        # gzip when the client accepts it: the full /api/data sheet can exceed
        # Cloud Run's ~32 MB HTTP/1 response cap uncompressed (and it's faster).
        if "gzip" in (self.headers.get("Accept-Encoding") or ""):
            body = gzip.compress(body)
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        sys.stderr.write(f"  {self.address_string()} {format % args}\n")


def main() -> None:
    port = int(os.environ.get("PORT", sys.argv[1] if len(sys.argv) > 1 else "8002"))
    host = os.environ.get("HOST", "127.0.0.1")
    # Regenerate score.csv at startup so the sheet matches the (possibly
    # overlay-restored) weights even before the first Save.
    try:
        score_sheet.build_score_sheet(APP_DIR, STATE["config"])
    except (OSError, ValueError, KeyError) as e:
        print(f"[score_sheet] skipped at startup: {e}", file=sys.stderr)
    config = STATE["config"]
    name = config.get("customer_name", "")
    rows = STATE["rows"]
    n = len(rows)
    flags = config.get("flags", {})
    crm_col = flags.get("crm_contact_column", "is_crm_contact")
    gold_col = flags.get("gold_column", "is_icp_gold")
    crm = sum(1 for r in rows if r.get(crm_col) in (1, True, "1"))
    gold = sum(1 for r in rows if r.get(gold_col) in (1, True, "1"))
    one_p = len(config.get("one_p_signals", []))
    print(
        f"[people-scoring] {name} · {n:,} people · "
        f"{crm:,} CRM contacts · {gold:,} gold · {one_p} 1P signal(s)",
        file=sys.stderr,
    )
    if STATE.get("saved_at"):
        print(
            f"[people-scoring] re-opened with weights saved {STATE['saved_at']}",
            file=sys.stderr,
        )
    print(f"[people-scoring] http://{host}:{port}/", file=sys.stderr)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
