"""Stage 2a — resolve ICP terms to canonical Sumble slugs/names via the v6
lookup endpoints, replacing the RunSqlQuery name lookups.

  POST /v6/technologies/lookup   names/slugs/aliases -> {slug, name, categories}
  POST /v6/projects/lookup       names/slugs         -> {slug, name}
  POST /v6/jobs/title-lookup     job-function names  -> {job_function {slug,name}}

The tech-category ROLL-UP (coverage %) still needs RunSqlQuery — it's an
aggregation with no endpoint equivalent — so this only covers name resolution.

Usage (comma-separated; flags repeatable):
  python lookup.py --technologies clay,common-room --projects "generative ai" \
                   --titles "Machine Learning,AI Engineer"

Prints JSON: {"technologies": [...], "projects": [...], "job_functions": [...]},
each item {input, slug, name} (technologies also carry their categories).
Unmatched inputs are omitted. Auth: SUMBLE_API_KEY (or --env-file path).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

import sumble_v6

# https://api.sumble.com/v6  (sibling of the /organizations endpoint)
BASE = sumble_v6.API_URL.rsplit("/", 1)[0]


def _post(api_key: str, path: str, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"{BASE}{path}", data=data, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        sys.exit(f"[lookup] HTTP {e.code} on {path}: {detail}")


def _split(vals: list[str]) -> list[str]:
    out: list[str] = []
    for v in vals or []:
        out += [s.strip() for s in v.split(",") if s.strip()]
    return out


def lookup_technologies(api_key: str, names: list[str]) -> list[dict]:
    if not names:
        return []
    resp = _post(api_key, "/technologies/lookup", {"technologies": names})
    out = []
    for r in resp.get("results", []):
        t = r.get("technology")
        if t:
            out.append({
                "input": r.get("input"),
                "slug": t.get("slug"),
                "name": t.get("name"),
                "categories": t.get("categories") or [],
            })
    return out


def lookup_projects(api_key: str, names: list[str]) -> list[dict]:
    if not names:
        return []
    resp = _post(api_key, "/projects/lookup", {"projects": names})
    return [
        {"input": r.get("input"), "slug": p.get("slug"), "name": p.get("name")}
        for r in resp.get("results", [])
        if (p := r.get("project"))
    ]


def lookup_job_functions(api_key: str, titles: list[str]) -> list[dict]:
    """Map a job-function name (or any title) -> canonical job_function. The
    /v6/organizations endpoint's `job_function` term is the display NAME."""
    if not titles:
        return []
    resp = _post(api_key, "/jobs/title-lookup", {"titles": titles})
    return [
        {"input": r.get("input"), "slug": jf.get("slug"), "name": jf.get("name")}
        for r in resp.get("results", [])
        if (jf := r.get("job_function"))
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description="Resolve ICP terms via v6 lookups.")
    ap.add_argument("--technologies", action="append", default=[])
    ap.add_argument("--projects", action="append", default=[])
    ap.add_argument(
        "--titles", action="append", default=[],
        help="job-function names (or titles) -> canonical job_function",
    )
    ap.add_argument("--env-file", default=None)
    args = ap.parse_args()
    key = sumble_v6.resolve_api_key(args.env_file, allow_prompt=sys.stdin.isatty())
    if not key:
        sys.exit("No Sumble API key. Run set_api_key.py or export SUMBLE_API_KEY.")
    out = {
        "technologies": lookup_technologies(key, _split(args.technologies)),
        "projects": lookup_projects(key, _split(args.projects)),
        "job_functions": lookup_job_functions(key, _split(args.titles)),
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
