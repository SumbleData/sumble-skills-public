#!/usr/bin/env bash
# Assemble the self-contained territory-planning DEMO from source:
#   1. copy the stdlib app from the skill template,
#   2. generate fictitious demo inputs (make_demo.py),
#   3. run the real pipeline (build_plan -> merge_territory -> suggest_moves),
#   4. inject a "demo — fictitious data" banner.
# Idempotent; re-run any time to rebuild byte-identically. No third-party deps.
set -euo pipefail

DEMO="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$DEMO/../.." && pwd)"
TPL="$REPO/skills/sumble-territory-planning/template"
DATA="$REPO/examples/account-scoring/data.csv"

[ -f "$TPL/app.py" ] || { echo "!! skill template not found at $TPL" >&2; exit 1; }
[ -f "$DATA" ]       || { echo "!! account-scoring demo data not found at $DATA" >&2; exit 1; }

echo ">> copying stdlib app from the skill template"
mkdir -p "$DEMO/static"
cp "$TPL/app.py"                  "$DEMO/app.py"
cp "$TPL/_build/territory_lib.py" "$DEMO/territory_lib.py"
cp "$TPL/README.md"               "$DEMO/APP_README.md"
cp "$TPL/Dockerfile"              "$DEMO/Dockerfile"
cp "$TPL/.dockerignore"           "$DEMO/.dockerignore"
for f in app.js style.css index.html logo.svg favicon.svg; do
  cp "$TPL/static/$f" "$DEMO/static/$f"
done

echo ">> generating fictitious demo inputs"
python3 "$DEMO/make_demo.py" --out "$DEMO" --data "$DATA"

echo ">> running the pipeline"
python3 "$TPL/_build/build_plan.py"      --raw "$DEMO/_raw"
python3 "$TPL/_build/merge_territory.py" --raw "$DEMO/_raw"
python3 "$TPL/_build/suggest_moves.py"   --dir "$DEMO"

echo ">> injecting the demo banner"
python3 "$DEMO/_banner.py" "$DEMO/static/index.html"

echo ">> done. run it:  cd $DEMO && python3 app.py   (http://localhost:8002)"
