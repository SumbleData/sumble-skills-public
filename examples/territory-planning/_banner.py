"""Inject a 'demo — fictitious data' banner into the demo's index.html.

Idempotent: does nothing if the banner is already present. Kept as a tiny
separate step so build.sh stays a plain copy+run recipe.

Usage:  python3 _banner.py /abs/path/to/static/index.html
"""

import sys

MARKER = "demo-banner"
BANNER = (
    '\n    <div class="demo-banner" style="background:#FEF3C7;color:#78350F;'
    "border-bottom:1px solid #F59E0B;padding:8px 20px;font-size:13px;"
    'text-align:center;line-height:1.4;">\n'
    "      <strong>Demo &mdash; fictitious data.</strong> Company (Northwind), reps, and "
    "activity are invented; account names are real public companies with synthetic "
    "demo scores. Nothing here reflects a real sales team.\n    </div>\n"
)


def main() -> None:
    path = sys.argv[1]
    html = open(path, encoding="utf-8").read()
    if MARKER in html:
        print("[banner] already present")
        return
    # Place it right after the opening <body ...> tag.
    lo = html.lower()
    i = lo.find("<body")
    if i < 0:
        print("[banner] no <body> found; skipping")
        return
    j = html.find(">", i) + 1
    html = html[:j] + BANNER + html[j:]
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print("[banner] injected")


if __name__ == "__main__":
    main()
