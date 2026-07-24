"""CRM-cleaning review app — zero-dependency local web server.

No pip install, no venv. Stdlib only: csv, json, http.server.

Serves the findings produced by `_build/analyze.py` (findings.json) and lets
the user review each one: accept / reject / skip, and for duplicates choose
per record whether to keep it as the primary, merge it into the primary, or
delete it outright. Decisions persist to decisions.json on every action, and
the Export button produces actions.csv — one row per CRM change to make
(merge, delete, set parent, create parent account).

Run from the output directory:
  python3 app.py            # http://localhost:8002
  python3 app.py 9002       # custom port (or PORT=9002 python3 app.py)
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FINDINGS_PATH = ROOT / "findings.json"
DECISIONS_PATH = ROOT / "decisions.json"
ACTIONS_PATH = ROOT / "actions.csv"

_lock = threading.Lock()


def load_findings() -> dict:
    if not FINDINGS_PATH.exists():
        sys.exit(f"Missing {FINDINGS_PATH} — run the _build pipeline first.")
    return json.loads(FINDINGS_PATH.read_text())


def load_decisions() -> dict:
    if DECISIONS_PATH.exists():
        return json.loads(DECISIONS_PATH.read_text())
    return {}


def save_decisions(decisions: dict) -> None:
    DECISIONS_PATH.write_text(json.dumps(decisions, indent=2))


ACTION_COLS = [
    "action",
    "finding_id",
    "confidence",
    "account_id",
    "account_name",
    "target_account_id",
    "target_account_name",
    "suggested_new_account_name",
    "suggested_new_account_domain",
    "note",
]


def build_actions(findings: dict, decisions: dict) -> list[dict]:
    """One row per CRM change implied by the ACCEPTED findings."""
    actions: list[dict] = []

    def base(fid: str, conf: str) -> dict:
        d = decisions.get(fid) or {}
        return {c: "" for c in ACTION_COLS} | {
            "finding_id": fid,
            "confidence": conf,
            "note": d.get("note", ""),
        }

    for dup in findings.get("duplicates", []):
        d = decisions.get(dup["id"]) or {}
        if d.get("dismissed"):
            continue
        # A duplicate is resolved by picking a primary (no accept/reject/skip).
        # Per-record actions: {crm_id: "primary" | "merge" | "delete"}. Picking
        # a primary defaults every other record to "merge"; flip any to delete.
        record_actions = d.get("record_actions") or {}
        primary_id = next(
            (cid for cid, act in record_actions.items() if act == "primary"), None
        )
        if not primary_id:
            continue  # not yet resolved
        primary = next(
            (a for a in dup["accounts"] if a["crm_account_id"] == primary_id),
            dup["accounts"][0],
        )
        for a in dup["accounts"]:
            cid = a["crm_account_id"]
            if cid == primary["crm_account_id"]:
                continue
            row = base(dup["id"], dup["confidence"])
            if record_actions.get(cid) == "delete":
                row.update(
                    action="delete",
                    account_id=cid,
                    account_name=a["crm_name"],
                )
            else:
                row.update(
                    action="merge",
                    account_id=cid,
                    account_name=a["crm_name"],
                    target_account_id=primary["crm_account_id"],
                    target_account_name=primary["crm_name"],
                )
            actions.append(row)

    for p in findings.get("parent_sub", []):
        d = decisions.get(p["id"]) or {}
        if d.get("decision") != "accept":
            continue
        row = base(p["id"], p["confidence"])
        row.update(
            action="set_parent",
            account_id=p["child"]["crm_account_id"],
            account_name=p["child"]["crm_name"],
            target_account_id=p["suggested_parent"]["crm_account_id"],
            target_account_name=p["suggested_parent"]["crm_name"],
        )
        actions.append(row)

    for g in findings.get("parent_not_in_crm", []):
        d = decisions.get(g["id"]) or {}
        if d.get("decision") != "accept":
            continue
        for child in g["children"]:
            row = base(g["id"], g["confidence"])
            row.update(
                action="create_parent_and_link",
                account_id=child["crm_account_id"],
                account_name=child["crm_name"],
                suggested_new_account_name=g["parent_org"]["name"],
                suggested_new_account_domain=g["parent_org"]["domain"],
            )
            actions.append(row)
    return actions


def actions_csv(findings: dict, decisions: dict) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=ACTION_COLS)
    w.writeheader()
    for row in build_actions(findings, decisions):
        w.writerow(row)
    return buf.getvalue()


class Handler(SimpleHTTPRequestHandler):
    findings: dict = {}

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (stdlib name)
        if self.path in ("/", "/index.html"):
            self.path = "/index.html"
            return super().do_GET()
        if self.path == "/api/data":
            with _lock:
                return self._json(
                    {"findings": self.findings, "decisions": load_decisions()}
                )
        if self.path == "/api/actions":
            # The exact rows actions.csv will contain, as JSON — so the app can
            # inventory every approved change in a review tab before download.
            with _lock:
                return self._json(
                    {"actions": build_actions(self.findings, load_decisions())}
                )
        if self.path == "/api/export":
            with _lock:
                csv_text = actions_csv(self.findings, load_decisions())
                ACTIONS_PATH.write_text(csv_text)
            body = csv_text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Content-Disposition", "attachment; filename=actions.csv")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 (stdlib name)
        if self.path != "/api/decide":
            return self._json({"error": "unknown endpoint"}, 404)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._json({"error": "bad JSON"}, 400)
        fid = payload.get("finding_id")
        decision = payload.get("decision")
        if not fid or decision not in ("accept", "reject", "skip", None):
            return self._json({"error": "finding_id + decision required"}, 400)
        with _lock:
            decisions = load_decisions()
            entry = decisions.get(fid) or {}
            if decision is None:
                entry.pop("decision", None)
            else:
                entry["decision"] = decision
            if "survivor_crm_id" in payload:
                entry["survivor_crm_id"] = payload["survivor_crm_id"]
            if "record_actions" in payload:
                ra = payload["record_actions"] or {}
                if ra:
                    entry["record_actions"] = ra
                else:
                    entry.pop("record_actions", None)
            if "dismissed" in payload:
                if payload["dismissed"]:
                    entry["dismissed"] = True
                else:
                    entry.pop("dismissed", None)
            if "note" in payload:
                entry["note"] = payload["note"]
            # Drop entries that carry nothing (toggled off with no extras).
            keys = ("decision", "survivor_crm_id", "record_actions", "dismissed", "note")
            if any(entry.get(k) for k in keys):
                decisions[fid] = entry
            else:
                decisions.pop(fid, None)
            save_decisions(decisions)
        return self._json({"ok": True, "decisions": decisions})

    def translate_path(self, path: str) -> str:
        # Serve static/ files from the app's own directory regardless of CWD.
        rel = path.lstrip("/").split("?")[0]
        candidate = ROOT / "static" / rel
        if candidate.is_file():
            return str(candidate)
        return str(ROOT / rel)

    def log_message(self, format: str, *args) -> None:  # noqa: A002 (stdlib name)
        if self.command == "GET" and not self.path.startswith("/api/"):
            return
        super().log_message(format, *args)


def main() -> None:
    port = int(os.environ.get("PORT", sys.argv[1] if len(sys.argv) > 1 else "8002"))
    Handler.findings = load_findings()
    # Bind localhost by default; containers (Cloud Run) set HOST=0.0.0.0.
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"CRM cleaning review app → http://localhost:{port}")
    print("Ctrl-C to stop. Decisions save to decisions.json on every click.")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
