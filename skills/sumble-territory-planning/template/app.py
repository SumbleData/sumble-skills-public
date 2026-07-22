"""Sumble territory-planning app — zero-dependency.

Runs on any stock Python 3.10+: `python3 app.py` and it's up. No pip install,
no venv. Stdlib only (csv, json, http.server) plus the sibling `territory_lib`
module, which is itself stdlib-only.

Reads territory-plan.json + territory.csv at startup and serves a single-page UI.
Balance maths runs client-side so accepting a move updates the bars instantly;
the server's job is to persist decisions and export them.

Per-customer customisation lives in territory-plan.json + territory.csv; this
file is identical across customers.
"""

from __future__ import annotations

import base64
import csv
import gzip
import hmac
import io
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any

import territory_lib as tl

APP_DIR = Path(__file__).resolve().parent
PLAN_PATH = APP_DIR / "territory-plan.json"
STATIC_DIR = APP_DIR / "static"

# Statuses the UI may set. "suggested" is the pipeline's own output and is not
# settable from the app — a user either accepts it, rejects it, or overrides the
# owner by hand (which records "manual").
VALID_STATUSES = {"accepted", "rejected", "manual", ""}

_LOCK = threading.Lock()


class State:
    """The plan + sheet, kept in memory and written through on every decision."""

    def __init__(self) -> None:
        if not PLAN_PATH.exists():
            raise FileNotFoundError(
                f"{PLAN_PATH.name} not found at {PLAN_PATH}. "
                "Generate it via the sumble-territory-planning skill."
            )
        self.plan: dict[str, Any] = tl.read_json(PLAN_PATH)
        self.csv_path = APP_DIR / (self.plan.get("territory_csv") or "territory.csv")
        if not self.csv_path.exists():
            raise FileNotFoundError(
                f"{self.csv_path.name} not found — run merge_territory.py first."
            )
        self.rows: list[dict[str, Any]] = tl.read_csv(self.csv_path)
        self.by_id: dict[str, dict[str, Any]] = {
            str(r.get("org_id")): r for r in self.rows
        }

    # -- persistence -------------------------------------------------------

    def save(self) -> None:
        tl.write_csv(self.csv_path, self.rows, tl.TERRITORY_COLUMNS)

    def decide(self, org_id: str, status: str, proposed_owner: str | None) -> dict[str, Any]:
        row = self.by_id.get(str(org_id))
        if row is None:
            raise KeyError(org_id)
        if status not in VALID_STATUSES:
            raise ValueError(f"unknown status: {status!r}")

        if status == "manual":
            # A hand-picked owner. Blank means "put it back" — clear the whole
            # proposal rather than recording a move to nobody.
            owner = (proposed_owner or "").strip()
            if not owner or owner == str(row.get("owner") or ""):
                row["proposed_owner"] = ""
                row["proposal_reason"] = ""
                row["proposal_status"] = ""
            else:
                row["proposed_owner"] = owner
                row["proposal_reason"] = "manual"
                row["proposal_status"] = "manual"
        elif status == "":
            # Undo back to the pipeline's suggestion, if there still is one.
            row["proposal_status"] = "suggested" if row.get("proposed_owner") else ""
        else:
            row["proposal_status"] = status
        self.save()
        return row

    # -- export ------------------------------------------------------------

    def actions_csv(self) -> bytes:
        """Every approved change, as a CRM-ready sheet. Accepted suggestions and
        manual overrides both count — they are the same instruction to the CRM."""
        cols = [
            "org_id", "name", "domain", "crm_account_id", "account_segment",
            "from_owner", "to_owner", "reason", "score", "size_metric",
            "meetings", "calls", "emails_out",
        ]
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in self.rows:
            if str(r.get("proposal_status")) not in ("accepted", "manual"):
                continue
            if not str(r.get("proposed_owner") or ""):
                continue
            w.writerow({
                "org_id": r.get("org_id"),
                "name": r.get("name"),
                "domain": r.get("domain"),
                "crm_account_id": r.get("crm_account_id"),
                "account_segment": r.get("account_segment"),
                "from_owner": r.get("owner") or "(unassigned)",
                "to_owner": r.get("proposed_owner"),
                "reason": r.get("proposal_reason"),
                "score": r.get("score"),
                "size_metric": r.get("size_metric"),
                "meetings": r.get("meetings"),
                "calls": r.get("calls"),
                "emails_out": r.get("emails_out"),
            })
        return buf.getvalue().encode("utf-8")


STATE = State()


# ---------- HTTP server ----------------------------------------------------

# Optional HTTP Basic Auth: enabled only when BASIC_AUTH_PASS is set (e.g. in a
# deployed container). Left unset locally so `python3 app.py` stays open.
BASIC_AUTH_USER = os.environ.get("BASIC_AUTH_USER", "sumble")
BASIC_AUTH_PASS = os.environ.get("BASIC_AUTH_PASS")
_EXPECTED_AUTH = (
    "Basic " + base64.b64encode(f"{BASIC_AUTH_USER}:{BASIC_AUTH_PASS}".encode()).decode()
    if BASIC_AUTH_PASS
    else None
)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def _require_auth(self) -> bool:
        if _EXPECTED_AUTH is None:
            return True
        if hmac.compare_digest(self.headers.get("Authorization", ""), _EXPECTED_AUTH):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Territory planning"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def do_GET(self) -> None:  # noqa: N802 (stdlib name)
        if not self._require_auth():
            return
        if self.path in ("/", "/index.html"):
            self.path = "/index.html"
            return super().do_GET()
        if self.path == "/api/plan":
            with _LOCK:
                return self._send_json({"plan": STATE.plan, "rows": STATE.rows})
        if self.path == "/api/export":
            with _LOCK:
                body = STATE.actions_csv()
            return self._send_file(body, "actions.csv")
        if self.path == "/api/territory.csv":
            with _LOCK:
                body = STATE.csv_path.read_bytes()
            return self._send_file(body, "territory.csv")
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 (stdlib name)
        if not self._require_auth():
            return
        if self.path != "/api/decide":
            self.send_error(404, "not found")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError) as e:
            self.send_error(400, f"bad request: {e}")
            return
        try:
            with _LOCK:
                row = STATE.decide(
                    str(body.get("org_id") or ""),
                    str(body.get("status") or ""),
                    body.get("proposed_owner"),
                )
        except KeyError:
            self.send_error(404, "org not found")
            return
        except ValueError as e:
            self.send_error(400, str(e))
            return
        except OSError as e:
            self.send_error(500, f"could not write territory.csv: {e}")
            return
        self._send_json({"ok": True, "row": row})

    def _send_json(self, data: Any) -> None:
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if "gzip" in (self.headers.get("Accept-Encoding") or ""):
            body = gzip.compress(body)
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, body: bytes, filename: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self) -> None:
        # Force static assets to revalidate so edits take effect on a refresh.
        if self.command == "GET" and not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache, max-age=0, must-revalidate")
        super().end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        sys.stderr.write(f"  {self.address_string()} {format % args}\n")


def main() -> None:
    port = int(os.environ.get("PORT", sys.argv[1] if len(sys.argv) > 1 else "8002"))
    host = os.environ.get("HOST", "127.0.0.1")
    company = (STATE.plan.get("company") or {}).get("name") or "Territory"
    reps = sum(1 for r in STATE.plan.get("reps", []) if r.get("is_rep"))
    proposals = sum(1 for r in STATE.rows if r.get("proposed_owner"))
    print(
        f"{company} territory plan · {len(STATE.rows):,} accounts · {reps} reps · "
        f"{proposals:,} proposed moves",
        file=sys.stderr,
    )
    print(f"http://{host}:{port}/", file=sys.stderr)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
