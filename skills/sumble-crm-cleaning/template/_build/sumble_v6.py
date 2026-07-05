"""Shared helpers for the unified Sumble `POST /v6/organizations` endpoint.

CRM-cleaning slice of the account-scoring helper: API key resolution (same
key file, `~/.config/sumble/api_key`), the retrying `post()` wrapper, and the
minimal attribute set the cleaning pipeline needs. No entity selections —
cleaning is attributes-only, so the per-org credit cost stays small.

The endpoint is documented in api/app/routers/paid_api/organizations.py
(`enrich_organizations_unified`). Input rows match by name/url, or identify a
Sumble org directly via `id`/`slug` (used for parent-org lookups).
"""

from __future__ import annotations

import getpass
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API_URL = "https://api.sumble.com/v6/organizations"

# Attributes pulled for every CRM account. id/name/slug/url/sumble_url are
# free; the rest cost 1 credit each per matched org (~5 credits/org total).
CLEANING_ATTRIBUTES = [
    "id",
    "slug",
    "name",
    "url",
    "sumble_url",
    "employee_count",
    "headquarters_country",
    "parent_id",
    "subsidiary_ids",
]

# Attributes pulled when resolving parent orgs by id (free ids + the same
# paid set, so a parent row carries everything the findings UI shows), plus
# `tags` so the analyzer can exclude PE-firm parents by default
# (`is_private_equity_firm`). +1 credit per parent org — parents are a small
# fraction of the run.
PARENT_ATTRIBUTES = [*CLEANING_ATTRIBUTES, "tags"]

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


def load_api_key(env_file: str | None = None) -> str:
    key = resolve_api_key(env_file, allow_prompt=sys.stdin.isatty())
    if not key:
        sys.exit(
            "No Sumble API key found. Run `python3 set_api_key.py` (prompts for the "
            "key and saves it), or `export SUMBLE_API_KEY=...`, or pass "
            "--env-file path/to/.env, then re-run."
        )
    return key


def post(api_key: str, body: dict, *, retries: int = 4, fatal: bool = True) -> dict | None:
    """POST to the unified endpoint with exponential-backoff retries."""
    data = json.dumps(body).encode("utf-8")
    for attempt in range(retries):
        req = urllib.request.Request(API_URL, data=data, method="POST")
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2**attempt)
                continue
            if not fatal:
                print(f"[fetch] HTTP {e.code} (non-fatal): {detail}")
                return None
            sys.exit(f"[fetch] HTTP {e.code}: {detail}")
        except (
            urllib.error.URLError,
            TimeoutError,
            http.client.IncompleteRead,
            http.client.HTTPException,
            ConnectionError,
            OSError,
        ) as e:
            if attempt < retries - 1:
                time.sleep(2**attempt)
                continue
            if not fatal:
                return None
            sys.exit(f"[fetch] network error: {e}")
    if fatal:
        raise SystemExit("[fetch] exhausted retries")
    return None


def exact_employee_count(attrs: dict) -> int:
    """Exact org headcount from the endpoint's `employee_count` attribute.

    The endpoint returns an exact integer (e.g. 2615); a legacy band string
    ("1,001 - 5,000") maps to its midpoint; missing → 0.
    """
    val = attrs.get("employee_count")
    if isinstance(val, bool):
        return 0
    if isinstance(val, (int, float)):
        return int(val) if val > 0 else 0
    if isinstance(val, str):
        return _emp_band_to_int(val)
    return 0


def _emp_band_to_int(band: str) -> int:
    import re

    nums = [int(n.replace(",", "")) for n in re.findall(r"[\d,]+", band)]
    if not nums:
        return 0
    if len(nums) == 1:
        return int(nums[0] * 1.5) if band.strip().endswith("+") else nums[0]
    return (nums[0] + nums[1]) // 2
