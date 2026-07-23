"""Propose owner changes and write them back into `territory.csv`.

This is a thin CLI over `territory_lib.suggest_moves()`. The engine itself
lives in the library because the APP drives it too — its calibration panel
re-runs the same four phases when you move the segment boundary or a capacity
cap. Keeping one implementation is what stops the balance bars, the move queue
and `actions.csv` from disagreeing with each other.

Four phases, least disruptive first:

  1. MISFIT      an account whose size puts it in another segment, and which
                 its owner is not working, moves to that segment.
  2. UNALLOCATED an account no active rep owns is assigned to the most
                 underloaded rep in its segment.
  3. WHITESPACE  the same, for net-new accounts carried over from an
                 account-scoring whitespace run.
  4. REBALANCE   only now, with the free wins taken, are already-owned accounts
                 moved between reps to even out the books.

The hard constraint everywhere: **an account with activity is never proposed for
a move.** A rep who has met, called, or emailed a prospect has something the
balance maths cannot see, and taking it away to make a spreadsheet even is how
territory planning loses deals. Worked misfits are flagged for a human instead.

Rows the user has already decided on in the app (accepted / rejected / manual)
are respected, so re-running after a review session refines the plan instead of
undoing it — use --reset to start over.

Usage:
  python3 suggest_moves.py --dir /abs/path/to/territory_planning/<company>
  python3 suggest_moves.py --dir <dir> --reset
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import territory_lib as tl


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--dir", required=True, help="the run directory (holds territory-plan.json + territory.csv)")
    ap.add_argument("--reset", action="store_true", help="discard existing proposals AND user decisions")
    args = ap.parse_args()

    root = Path(args.dir).expanduser().resolve()
    plan_path = root / "territory-plan.json"
    csv_path = root / "territory.csv"
    for p in (plan_path, csv_path):
        if not p.exists():
            sys.exit(f"[moves] {p} not found — run build_plan.py and merge_territory.py first.")

    plan = tl.read_json(plan_path)
    rows = tl.read_csv(csv_path)
    if not rows:
        sys.exit("[moves] territory.csv is empty.")

    report = tl.suggest_moves(plan, rows, reset=args.reset)
    tl.write_csv(csv_path, rows, tl.TERRITORY_COLUMNS)

    counts = report["counts"]
    segments = plan["segments"]
    print(f"[moves] wrote {csv_path} · {report['total']:,} proposals")
    print(
        f"[moves] misfit {counts['misfit']:,} · unallocated {counts['assign_unallocated']:,} · "
        f"whitespace {counts['assign_whitespace']:,} · rebalance {counts['rebalance']:,}"
    )
    for seg in segments:
        key = seg["key"]
        after = report["after_stats"].get(key, {}).get("cv", 0.0)
        before = report["cv_before"].get(key, 0.0)
        print(
            f"[moves] {seg['label']}: CV {before:.3f} ({tl.balance_label(before)}) → "
            f"{after:.3f} ({tl.balance_label(after)}) if every proposal is accepted"
        )
    if report["skipped_worked_misfits"]:
        print(
            f"[moves] {report['skipped_worked_misfits']:,} out-of-segment accounts were NOT "
            "proposed for a move because their owner is actively working them — "
            "review those by hand."
        )
    if report["skipped_coach_misfits"]:
        print(
            f"[moves] {report['skipped_coach_misfits']:,} out-of-segment accounts were NOT "
            "proposed for a move because they belong to a rep excluded from balance ("
            + ", ".join(report["coach_names"]) + ")."
        )
    capped = [
        f"{r['name']} {r.get('effective_capacity'):,}"
        for r in plan["reps"]
        if r.get("is_rep") and r.get("effective_capacity")
    ]
    if capped:
        print("[moves] capacity in force · " + " · ".join(capped))
    if report["unrouted"]:
        labels = {s["key"]: s["label"] for s in segments}
        detail = " · ".join(
            f"{labels.get(k, k)} {v:,}" for k, v in sorted(report["unrouted"].items())
        )
        print(
            f"[moves] NOTE: unowned accounts left unassigned because every rep is at "
            f"capacity — {detail}. Raise the segment's default_capacity (in the app's "
            "Calibrate panel, or territory-plan.json) to route more."
        )


if __name__ == "__main__":
    main()
