"""Light Sumble pull for territory planning — `POST /v6/organizations`.

Two jobs, both deliberately small compared with the account-scoring fetch:

  Path B (no account-scoring run) — resolve every CRM account to a Sumble org
  and pull `sumble_score` (Sumble's own account score, the fallback strength
  measure), `employee_count`, and identity/firmographic attributes.

  Path A supplement — an account-scoring run already supplies the strength
  score, but the user chose a segment boundary on a job function that run never
  fetched. `--from-score score.csv --only-jf "<Function Name>"` pulls just that
  one `people_count` for the same orgs.

Credit cost is ~1 credit per paid attribute per matched org (id/name/slug/url
are free), plus 1 per entity metric. A default Path B pull is ~6 credits/org —
an order of magnitude below a scoring pull, because there is no ICP to enrich.

Inputs
  _raw/spec.json      company, boundary metric, score_source
  _raw/accounts.csv   crm_account_id,name,domain   (Path B)
  --from-score PATH   an existing score.csv (org_id,name,url) (Path A supplement)

Outputs
  _raw/responses/light_*.json   raw endpoint responses
  _raw/sumble_light.csv         one row per matched org

Auth: SUMBLE_API_KEY, or a key saved by `set_api_key.py`, or --env-file.

Usage:
  python3 fetch_light.py --raw /abs/path/_raw
  python3 fetch_light.py --raw /abs/path/_raw --only-jf "Engineer" --from-score /abs/path/score.csv
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import sumble_v6
import territory_lib as tl

# The endpoint takes up to 1000 orgs per call, but this payload is small (a
# handful of attributes, at most one entity) so 200 is comfortable and keeps
# each response file readable. `_fetch` halves any batch that still fails.
BATCH = 200
MIN_BATCH = 20

# Paid attributes. `sumble_score` is Sumble's own 0-100 account score and is the
# fallback strength measure when the user has no account-scoring run.
ATTRIBUTES = [
    "id", "slug", "name", "url",           # free
    "employee_count", "industry", "headquarters_country",
    "tags", "sumble_score", "sumble_url",  # 1 credit each per matched org
]


def load_api_key(env_file: str | None) -> str:
    key = sumble_v6.resolve_api_key(env_file, allow_prompt=sys.stdin.isatty())
    if not key:
        sys.exit(
            "No Sumble API key found. Run `python3 set_api_key.py` (prompts and saves "
            "it), or `export SUMBLE_API_KEY=...`, or pass --env-file path/to/.env."
        )
    return key


def post(api_key: str, body: dict, *, retries: int = 6) -> dict | None:
    data = json.dumps(body).encode("utf-8")
    for attempt in range(retries):
        req = urllib.request.Request(sumble_v6.API_URL, data=data, method="POST")
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
            if e.code in (400, 422):
                # A bad job-function name or attribute is a config error, not a
                # transient one — fail loudly with the endpoint's own message.
                sys.exit(f"[fetch] HTTP {e.code}: {detail}")
            print(f"[fetch] HTTP {e.code} (non-fatal): {detail}", file=sys.stderr)
            return None
        except (
            urllib.error.URLError, TimeoutError, http.client.IncompleteRead,
            http.client.HTTPException, ConnectionError, OSError,
        ) as e:
            if attempt < retries - 1:
                time.sleep(2**attempt)
                continue
            print(f"[fetch] network error: {e}", file=sys.stderr)
            return None
    return None


def _fetch(api_key: str, orgs: list[dict], select: dict) -> list[dict]:
    """POST one batch; halve and retry on persistent failure so an oversized or
    pathological response degrades instead of sinking the run. Credits are per
    matched org, so splitting costs nothing extra."""
    resp = post(api_key, {"organizations": orgs, "select": select})
    if resp is not None:
        return [resp]
    if len(orgs) <= MIN_BATCH:
        sys.exit(
            f"[fetch] a {len(orgs)}-org batch failed after retries and splitting to the "
            f"{MIN_BATCH}-org floor — likely a real outage; re-run to resume."
        )
    mid = len(orgs) // 2
    print(f"[fetch] batch of {len(orgs)} failed; splitting -> {mid}+{len(orgs) - mid}")
    return _fetch(api_key, orgs[:mid], select) + _fetch(api_key, orgs[mid:], select)


def load_inputs(raw: Path, from_score: str | None) -> list[dict[str, str]]:
    """The org list to resolve: an existing score.csv, else _raw/accounts.csv."""
    if from_score:
        path = Path(from_score).expanduser()
        if not path.exists():
            sys.exit(f"[fetch] --from-score file not found: {path}")
        rows = tl.read_csv(path)
        out = []
        seen: set[str] = set()
        for r in rows:
            dom = tl.norm_domain(r.get("url") or r.get("domain"))
            name = r.get("name") or r.get("crm_account_name") or ""
            key = dom or name.lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append({"crm_account_id": r.get("crm_account_id") or "", "name": name, "domain": dom})
        return out
    rows = tl.read_csv(raw / "accounts.csv")
    if not rows:
        sys.exit(
            f"[fetch] no input list. Write {raw / 'accounts.csv'} "
            "(crm_account_id,name,domain), or pass --from-score path/to/score.csv."
        )
    return [
        {
            "crm_account_id": r.get("crm_account_id") or "",
            "name": r.get("name") or "",
            "domain": tl.norm_domain(r.get("domain") or r.get("url")),
        }
        for r in rows
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", required=True, help="the run's _raw directory (absolute path)")
    ap.add_argument("--from-score", default=None, help="an existing score.csv to take the org list from")
    ap.add_argument("--only-jf", default=None, help="job-function display name to pull people_count for")
    ap.add_argument("--env-file", default=None)
    args = ap.parse_args()

    raw = Path(args.raw).expanduser().resolve()
    raw.mkdir(parents=True, exist_ok=True)
    spec = tl.read_json(raw / "spec.json") if (raw / "spec.json").exists() else {}

    # The boundary metric decides whether a job function is needed at all.
    jf_name = args.only_jf
    if not jf_name:
        metric = str((spec.get("boundary") or {}).get("metric") or "")
        if metric.startswith("jf_people:"):
            jf_name = metric.split(":", 1)[1].strip()

    inputs = load_inputs(raw, args.from_score)
    api_key = load_api_key(args.env_file)

    select: dict = {"attributes": list(ATTRIBUTES)}
    if jf_name:
        select["entities"] = [
            {"type": "job_function", "term": jf_name, "metrics": ["people_count"]}
        ]

    per_org = len(ATTRIBUTES) - 4 + (1 if jf_name else 0)
    print(
        f"[fetch] {len(inputs):,} accounts · ~{per_org} credits/matched org "
        f"(~{per_org * len(inputs):,} total)" + (f" · job function: {jf_name}" if jf_name else "")
    )

    resp_dir = raw / "responses"
    resp_dir.mkdir(exist_ok=True)
    for old in resp_dir.glob("light_*.json"):
        old.unlink()

    out_rows: list[dict] = []
    batch_idx = 0
    matched = 0
    for start in range(0, len(inputs), BATCH):
        chunk = inputs[start : start + BATCH]
        orgs = [{"name": r["name"], "url": r["domain"]} for r in chunk]
        cursor = 0
        for resp in _fetch(api_key, orgs, select):
            (resp_dir / f"light_{batch_idx:04d}.json").write_text(
                json.dumps(resp, indent=2), encoding="utf-8"
            )
            batch_idx += 1
            for org in resp.get("organizations") or []:
                src = chunk[cursor] if cursor < len(chunk) else {}
                cursor += 1
                attrs = org.get("attributes") or {}
                if not attrs.get("id"):
                    continue  # unmatched input — dropped, counted in the summary
                matched += 1
                row = {
                    "org_id": attrs.get("id"),
                    "slug": attrs.get("slug") or "",
                    "name": attrs.get("name") or "",
                    "url": tl.norm_domain(attrs.get("url")),
                    "employee_count_int": sumble_v6._exact_employee_count(attrs),
                    "industry": attrs.get("industry") or "",
                    "headquarters_country": attrs.get("headquarters_country") or "",
                    "tags": "|".join(attrs.get("tags") or []),
                    "sumble_score": tl.to_float(attrs.get("sumble_score")),
                    "sumble_url": attrs.get("sumble_url") or "",
                    "crm_account_id": src.get("crm_account_id", ""),
                    "input_name": src.get("name", ""),
                    "input_domain": src.get("domain", ""),
                    "jf_people": 0,
                }
                if jf_name:
                    for ent in org.get("entities") or []:
                        if ent.get("type") == "job_function" and ent.get("term") == jf_name:
                            row["jf_people"] = tl.to_int(ent.get("people_count"))
                out_rows.append(row)
        print(f"[fetch] {min(start + BATCH, len(inputs)):,}/{len(inputs):,} accounts")

    columns = [
        "org_id", "slug", "name", "url", "employee_count_int", "industry",
        "headquarters_country", "tags", "sumble_score", "sumble_url",
        "jf_people", "crm_account_id", "input_name", "input_domain",
    ]
    out_path = raw / "sumble_light.csv"
    tl.write_csv(out_path, out_rows, columns)
    unmatched = len(inputs) - matched
    print(
        f"[fetch] wrote {out_path} · {matched:,} matched, {unmatched:,} unmatched "
        f"({100.0 * unmatched / max(len(inputs), 1):.1f}% — unmatched accounts are "
        "dropped from the plan)"
    )


if __name__ == "__main__":
    main()
