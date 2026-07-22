"""Propose owner changes and write them back into `territory.csv`.

Deterministic: same territory.csv + same plan → byte-identical proposals. No
RNG, every tie broken by `org_id`.

Four phases, in this order — least disruptive first, because moving an account
someone already has a relationship with costs more than assigning one nobody
owns:

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
are respected: accepted and manual moves count as ALREADY APPLIED when measuring
balance, and rejected rows are never re-proposed. So re-running after a review
session refines the plan instead of undoing it — use --reset to start over.

Usage:
  python3 suggest_moves.py --dir /abs/path/to/territory_planning/<company>
  python3 suggest_moves.py --dir <dir> --reset
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import territory_lib as tl

WHITESPACE_CATEGORIES = {"whitespace", "whitespace_subsidiary"}
FROZEN_STATUSES = {"accepted", "rejected", "manual"}


def effective_owner(row: dict) -> str:
    """Who owns the account once the user's accepted/manual decisions are
    applied — what the balance maths must measure against."""
    if str(row.get("proposal_status") or "") in ("accepted", "manual"):
        return str(row.get("proposed_owner") or "") or str(row.get("owner") or "")
    return str(row.get("owner") or "")


class Books:
    """Per-rep load inside one segment, kept incrementally so a greedy pass
    doesn't rescan the whole sheet after every move."""

    def __init__(self, reps: list[dict], rows: list[dict], balance_cats: set[str]) -> None:
        self.reps = {r["name"]: r for r in reps}
        self.sum_score: dict[str, float] = {r["name"]: 0.0 for r in reps}
        self.n_accounts: dict[str, int] = {r["name"]: 0 for r in reps}
        for row in rows:
            owner = effective_owner(row)
            if owner in self.sum_score and str(row.get("account_category")) in balance_cats:
                self.sum_score[owner] += tl.to_float(row.get("score"))
                self.n_accounts[owner] += 1

    def add(self, rep: str, score: float) -> None:
        if rep in self.sum_score:
            self.sum_score[rep] += score
            self.n_accounts[rep] += 1

    def remove(self, rep: str, score: float) -> None:
        if rep in self.sum_score:
            self.sum_score[rep] -= score
            self.n_accounts[rep] -= 1

    def cv(self) -> float:
        return tl.coefficient_of_variation(list(self.sum_score.values()))

    def has_capacity(self, rep: str) -> bool:
        cap = self.reps.get(rep, {}).get("capacity")
        if cap in (None, "", 0):
            return True
        return self.n_accounts.get(rep, 0) < tl.to_int(cap)

    def most_underloaded(self) -> str:
        """Lightest book with room. Ties by name → deterministic."""
        candidates = [r for r in sorted(self.sum_score) if self.has_capacity(r)]
        if not candidates:
            return ""
        return min(candidates, key=lambda r: (self.sum_score[r], r))

    def donors_desc(self) -> list[str]:
        return sorted(self.sum_score, key=lambda r: (-self.sum_score[r], r))


def is_movable(row: dict) -> bool:
    """An already-owned account that may be reassigned by the balancer."""
    return (
        not tl.truthy(row.get("worked"))
        and str(row.get("proposal_status") or "") not in FROZEN_STATUSES
        and not str(row.get("proposed_owner") or "")
        and str(row.get("account_category")) not in WHITESPACE_CATEGORIES
        and str(row.get("account_category")) != "customer"
        and not tl.truthy(row.get("double_allocated"))
        and bool(effective_owner(row))
    )


def propose(row: dict, new_owner: str, reason: str) -> None:
    row["proposed_owner"] = new_owner
    row["proposal_reason"] = reason
    row["proposal_status"] = "suggested"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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

    segments = plan["segments"]
    reps = [r for r in plan["reps"] if r.get("is_rep")]
    policy = plan.get("move_policy") or {}
    cv_stop = tl.to_float(policy.get("cv_stop"), tl.CV_STOP)
    max_move_frac = tl.to_float(policy.get("max_move_frac"), tl.MAX_MOVE_FRAC)
    balance_cats = set((plan.get("balance") or {}).get("include_categories", tl.DEFAULT_BALANCE_CATEGORIES))

    if args.reset:
        for row in rows:
            row["proposed_owner"] = ""
            row["proposal_reason"] = ""
            row["proposal_status"] = ""
    else:
        # Clear stale suggestions but keep the user's own decisions.
        for row in rows:
            if str(row.get("proposal_status") or "") == "suggested":
                row["proposed_owner"] = ""
                row["proposal_reason"] = ""
                row["proposal_status"] = ""

    reps_by_segment: dict[str, list[dict]] = {}
    for r in reps:
        reps_by_segment.setdefault(str(r.get("segment") or ""), []).append(r)

    books = {
        seg["key"]: Books(reps_by_segment.get(seg["key"], []), rows, balance_cats)
        for seg in segments
    }
    cv_before = {k: b.cv() for k, b in books.items()}
    counts = {"misfit": 0, "assign_unallocated": 0, "assign_whitespace": 0, "rebalance": 0}
    skipped_worked_misfits = 0

    def rows_sorted(pred) -> list[dict]:
        return sorted(
            [r for r in rows if pred(r)],
            key=lambda r: (-tl.to_float(r.get("score")), str(r.get("org_id"))),
        )

    # --- Phase 1: misfits ----------------------------------------------------
    # Customers ARE eligible here, unlike in the rebalance phase. The difference
    # is principled: a misfit move is a correctness fix (an enterprise account
    # sitting with a commercial rep should be routed to the enterprise team, and
    # that is as true for a customer as a prospect), while rebalancing is an
    # optimisation — and churning a customer account purely to even out a
    # spreadsheet is exactly the move that costs a renewal. The no-activity
    # constraint still applies to both.
    for row in rows_sorted(lambda r: tl.truthy(r.get("segment_misfit"))):
        if tl.truthy(row.get("worked")):
            skipped_worked_misfits += 1
            continue
        if str(row.get("proposal_status") or "") in FROZEN_STATUSES:
            continue
        target_seg = str(row.get("account_segment") or "")
        from_seg = str(row.get("rep_segment") or "")
        target = books.get(target_seg)
        if not target:
            continue
        new_owner = target.most_underloaded()
        old_owner = effective_owner(row)
        if not new_owner or new_owner == old_owner:
            continue
        score = tl.to_float(row.get("score"))
        if str(row.get("account_category")) in balance_cats:
            if from_seg in books:
                books[from_seg].remove(old_owner, score)
            target.add(new_owner, score)
        propose(row, new_owner, "misfit")
        counts["misfit"] += 1

    # --- Phase 2 + 3: assign unowned accounts, then net-new whitespace -------
    for reason, pred in (
        ("assign_unallocated", lambda r: tl.truthy(r.get("unallocated")) and str(r.get("account_category")) not in WHITESPACE_CATEGORIES),
        ("assign_whitespace", lambda r: str(r.get("account_category")) in WHITESPACE_CATEGORIES),
    ):
        for row in rows_sorted(pred):
            if str(row.get("proposal_status") or "") in FROZEN_STATUSES or row.get("proposed_owner"):
                continue
            seg = str(row.get("account_segment") or "")
            book = books.get(seg)
            if not book:
                continue
            new_owner = book.most_underloaded()
            if not new_owner:
                continue
            score = tl.to_float(row.get("score"))
            # Newly assigned accounts count toward the book immediately, so the
            # next assignment goes to whoever is now lightest — this is what
            # spreads a batch of unowned accounts instead of dumping them all
            # on one rep.
            book.add(new_owner, score)
            propose(row, new_owner, reason)
            counts[reason] += 1

    # --- Phase 4: rebalance ---------------------------------------------------
    for seg in segments:
        key = seg["key"]
        book = books[key]
        if len(book.sum_score) < 2:
            continue
        seg_rows = [r for r in rows if str(r.get("account_segment")) == key]
        max_moves = int(max_move_frac * len(seg_rows))
        moved = 0
        exhausted: set[str] = set()
        while moved < max_moves and book.cv() > cv_stop:
            donor = next((d for d in book.donors_desc() if d not in exhausted), "")
            recipient = book.most_underloaded()
            if not donor or not recipient or donor == recipient:
                break
            gap = book.sum_score[donor] - book.sum_score[recipient]
            if gap <= 0:
                break
            candidates = [
                r for r in seg_rows
                if is_movable(r) and effective_owner(r) == donor
            ]
            if not candidates:
                exhausted.add(donor)
                continue
            # The account that most nearly halves the gap: after the move the
            # difference becomes |gap - 2*score|, so minimise that.
            best = min(
                candidates,
                key=lambda r: (abs(gap - 2 * tl.to_float(r.get("score"))), str(r.get("org_id"))),
            )
            score = tl.to_float(best.get("score"))
            if abs(gap - 2 * score) >= gap:
                # Every remaining account is too big to help — moving it would
                # just invert the imbalance.
                exhausted.add(donor)
                continue
            book.remove(donor, score)
            book.add(recipient, score)
            propose(best, recipient, "rebalance")
            counts["rebalance"] += 1
            moved += 1

    tl.write_csv(csv_path, rows, tl.TERRITORY_COLUMNS)

    # Report the after-CV from a full recompute over the proposed allocation,
    # NOT from the incremental `books`. The greedy state deliberately counts
    # newly-assigned whitespace so successive assignments spread across reps,
    # but whitespace is outside the balance categories — so only a clean
    # book_stats pass matches what the app will display.
    proposed_rows = [
        dict(r, owner=(r.get("proposed_owner") or r.get("owner"))) for r in rows
    ]
    after_stats = tl.book_stats(proposed_rows, reps, balance_cats)

    total = sum(counts.values())
    print(f"[moves] wrote {csv_path} · {total:,} proposals")
    print(
        f"[moves] misfit {counts['misfit']:,} · unallocated {counts['assign_unallocated']:,} · "
        f"whitespace {counts['assign_whitespace']:,} · rebalance {counts['rebalance']:,}"
    )
    for seg in segments:
        key = seg["key"]
        after = after_stats.get(key, {}).get("cv", 0.0)
        before = cv_before.get(key, 0.0)
        print(
            f"[moves] {seg['label']}: CV {before:.3f} ({tl.balance_label(before)}) → "
            f"{after:.3f} ({tl.balance_label(after)}) if every proposal is accepted"
        )
    if skipped_worked_misfits:
        print(
            f"[moves] {skipped_worked_misfits:,} out-of-segment accounts were NOT proposed "
            "for a move because their owner is actively working them — review those by hand."
        )


if __name__ == "__main__":
    main()
