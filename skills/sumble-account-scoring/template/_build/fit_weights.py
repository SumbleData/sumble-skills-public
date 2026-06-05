"""Stage 3b — fit section + category weights to the gold set (regularized).

Runs AFTER build_weights.py. Reads the freshly-built
account-scoring-weights.json (default weights = thoughtful policy priors) plus
data.csv (the calibration sample, with `is_icp_gold`), and nudges ONLY the
section blend and per-section category weights toward better separation of the
gold (closed-won) accounts — deliberately a little, not a lot.

Anti-overfit design (the Part 2 blog post tells the same story in prose):
  * Low DOF — only the section blend + per-section category weights are fit.
    The within-category signal weights (geometric decay) are FROZEN.
  * Shrinkage to the priors — objective = AUC(gold) - lam * ||w - w_default||^2,
    so a weight moves only when the gold evidence overcomes the prior.
  * Box bounds — no weight may drift more than CATEGORY_BAND / SECTION_BAND
    points from its default, so the model stays recognizable.
  * K-fold CV — lam is picked on HELD-OUT gold, never on the training fit.
  * Adopt-only-if-it-generalizes — the fit replaces the defaults only if
    held-out AUC beats the defaults by >= ADOPT_MARGIN_AUC; otherwise the
    priors stand untouched.
  * Small-gold guard — with fewer than MIN_GOLD_FOR_FIT gold rows, skip entirely.

Deterministic: folds are assigned by a stratified round-robin over org_id (no
RNG) and the optimizer is derivative-free coordinate ascent, so the same config
+ same data.csv always produce the same fitted weights.

Writes the fitted weights back into account-scoring-weights.json (in place) and
a human-readable _raw/_weight_fit_report.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

# --- Policy constants (fixed; the agent does not pick these per run) ----------
MIN_GOLD_FOR_FIT = 40          # below this many gold rows, keep the priors
MIN_NONGOLD_FOR_FIT = 40       # need a background population to rank against
N_FOLDS = 5                    # stratified CV folds
CATEGORY_BAND = 10.0           # a category weight may move +/- this many points
SECTION_BAND = 15.0            # the section blend may move +/- this many points
LAMBDA_GRID = [0.0, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0]  # shrinkage strengths to CV
ADOPT_MARGIN_AUC = 0.01        # held-out AUC must beat defaults by this to adopt
N_SWEEPS = 3                   # coordinate-ascent passes
STEP_POINTS = [-5.0, -2.5, 2.5, 5.0]  # candidate moves per coordinate (points)

_NORM_SCALE = 1.0 - math.exp(-1.0)


# --- IO -----------------------------------------------------------------------


def _f(val: object, default: float = 0.0) -> float:
    if val in (None, "", "null"):
        return default
    try:
        return float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def normalise(raw: float, transform: str, p99: float) -> float:
    """p99 exponential saturation — identical to app.py / score_accounts.py."""
    x = raw if transform == "linear" else math.log1p(max(raw, 0.0))
    p99 = max(float(p99 or 0.0), 1e-9)
    arg = min(-x / p99, 700.0)
    n = (1.0 - math.exp(arg)) / _NORM_SCALE
    return max(0.0, min(n, 1.0))


# --- Model: per-row, per-category aggregated norm -----------------------------


def build_category_norms(
    rows: list[dict[str, str]], signals: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, float]], dict[str, str]]:
    """g[r][cat] = sum over signals in cat of (within_pct/100) * norm.

    The within-category weights are frozen, so g is fixed and the score becomes
    linear in the section/category weights we are fitting. Returns (g_rows,
    cat_of_signal_is_unused) — second value is the per-category list for sizing.
    """
    sig_meta = []
    for sig in signals.values():
        col = sig.get("column")
        cat = sig.get("category")
        if not col or not cat:
            continue
        sig_meta.append(
            (
                col,
                cat,
                sig.get("transform", "log"),
                float(sig.get("p99") or 1e-9),
                float(sig.get("default_within") or 0.0) / 100.0,
            )
        )
    g_rows: list[dict[str, float]] = []
    cats_seen: dict[str, str] = {}
    for r in rows:
        g: dict[str, float] = {}
        for col, cat, transform, p99, within_frac in sig_meta:
            if within_frac <= 0:
                cats_seen.setdefault(cat, cat)
                continue
            n = normalise(_f(r.get(col)), transform, p99)
            g[cat] = g.get(cat, 0.0) + within_frac * n
            cats_seen.setdefault(cat, cat)
        g_rows.append(g)
    return g_rows, cats_seen


def score_rows(
    g_rows: list[dict[str, float]],
    section_pct: dict[str, float],
    category_pct: dict[str, float],
    section_of: dict[str, str],
) -> list[float]:
    scores: list[float] = []
    for g in g_rows:
        s = 0.0
        for cat, gval in g.items():
            sec = section_of.get(cat)
            if sec is None:
                continue
            s += (section_pct.get(sec, 0.0) / 100.0) * (category_pct[cat] / 100.0) * gval
        scores.append(s)
    return scores


# --- Metrics ------------------------------------------------------------------


def auc(scores: list[float], labels: list[int], idxs: list[int]) -> float:
    """Rank-based AUC (Mann-Whitney) over the given row indices, tie-aware."""
    # Build rank map with average ranks for ties.
    order = sorted(idxs, key=lambda i: scores[i])
    ranks: dict[int, float] = {}
    j = 0
    n = len(order)
    while j < n:
        k = j
        while k + 1 < n and scores[order[k + 1]] == scores[order[j]]:
            k += 1
        avg = (j + k) / 2.0 + 1.0  # 1-based average rank
        for m in range(j, k + 1):
            ranks[order[m]] = avg
        j = k + 1
    n_pos = sum(1 for i in idxs if labels[i] == 1)
    n_neg = len(idxs) - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5
    sum_pos = sum(ranks[i] for i in idxs if labels[i] == 1)
    return (sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def lift_at_decile(scores: list[float], labels: list[int]) -> float:
    n = len(scores)
    if n == 0:
        return 0.0
    total_gold = sum(labels)
    if total_gold == 0:
        return 0.0
    order = sorted(range(n), key=lambda i: scores[i], reverse=True)
    k = max(1, int(0.1 * n))
    top_gold = sum(labels[i] for i in order[:k])
    baseline = total_gold / n
    return (top_gold / k) / baseline if baseline > 0 else 0.0


# --- Optimizer ----------------------------------------------------------------


def _shrink(
    section_pct: dict[str, float],
    category_pct: dict[str, float],
    sec0: dict[str, float],
    cat0: dict[str, float],
) -> float:
    s = 0.0
    for sec, v in section_pct.items():
        s += ((v - sec0[sec]) / 100.0) ** 2
    for cat, v in category_pct.items():
        s += ((v - cat0[cat]) / 100.0) ** 2
    return s


def _renorm_group(vals: dict[str, float], key: str, new_v: float,
                  boxes: dict[str, tuple[float, float]]) -> dict[str, float]:
    """Set vals[key]=new_v, spread the remainder over the others proportionally,
    clip to boxes, and renormalise the group to sum 100."""
    keys = list(vals.keys())
    if len(keys) == 1:
        return {keys[0]: 100.0}
    lo, hi = boxes[key]
    new_v = max(lo, min(hi, new_v))
    others = [k for k in keys if k != key]
    other_sum = sum(vals[k] for k in others)
    remaining = 100.0 - new_v
    out = {key: new_v}
    if other_sum <= 0:
        share = remaining / len(others)
        for k in others:
            out[k] = share
    else:
        for k in others:
            out[k] = remaining * vals[k] / other_sum
    # Clip others to their boxes, then renormalise the others to `remaining`.
    for _ in range(2):
        for k in others:
            blo, bhi = boxes[k]
            out[k] = max(blo, min(bhi, out[k]))
        cur = sum(out[k] for k in others)
        if cur > 0:
            for k in others:
                out[k] = remaining * out[k] / cur
    return out


def optimize(
    g_rows: list[dict[str, float]],
    labels: list[int],
    train_idxs: list[int],
    section_of: dict[str, str],
    cats_by_section: dict[str, list[str]],
    sec0: dict[str, float],
    cat0: dict[str, float],
    sec_boxes: dict[str, tuple[float, float]],
    cat_boxes: dict[str, tuple[float, float]],
    lam: float,
) -> tuple[dict[str, float], dict[str, float]]:
    """Coordinate ascent on the section blend + category weights (train AUC -
    lam * shrinkage), starting from the defaults."""
    section_pct = dict(sec0)
    category_pct = dict(cat0)
    sections = list(sec0.keys())

    def obj(sp: dict[str, float], cp: dict[str, float]) -> float:
        sc = score_rows(g_rows, sp, cp, section_of)
        return auc(sc, labels, train_idxs) - lam * _shrink(sp, cp, sec0, cat0)

    best = obj(section_pct, category_pct)
    for _ in range(N_SWEEPS):
        improved = False
        # Section blend (only meaningful with >=2 live sections).
        if len(sections) >= 2:
            for delta in STEP_POINTS:
                for sec in sections:
                    trial = _renorm_group(section_pct, sec,
                                          section_pct[sec] + delta, sec_boxes)
                    val = obj(trial, category_pct)
                    if val > best + 1e-12:
                        best, section_pct, improved = val, trial, True
        # Category weights, per section.
        for sec in sections:
            cats = cats_by_section[sec]
            if len(cats) < 2:
                continue
            sub0 = {c: category_pct[c] for c in cats}
            for delta in STEP_POINTS:
                for c in cats:
                    sub = _renorm_group(sub0, c, sub0[c] + delta, cat_boxes)
                    trial = dict(category_pct)
                    trial.update(sub)
                    val = obj(section_pct, trial)
                    if val > best + 1e-12:
                        best, category_pct, improved = val, trial, True
                        sub0 = {c2: category_pct[c2] for c2 in cats}
        if not improved:
            break
    return section_pct, category_pct


# --- Cross-validation ---------------------------------------------------------


def stratified_folds(rows: list[dict[str, str]], labels: list[int]) -> list[int]:
    """Deterministic stratified round-robin over org_id — no RNG."""
    fold = [0] * len(rows)
    for lab in (1, 0):
        members = [i for i in range(len(rows)) if labels[i] == lab]
        members.sort(key=lambda i: str(rows[i].get("org_id") or i))
        for pos, i in enumerate(members):
            fold[i] = pos % N_FOLDS
    return fold


def cv_heldout_auc(
    g_rows, labels, folds, section_of, cats_by_section,
    sec0, cat0, sec_boxes, cat_boxes, lam: float, fit: bool,
) -> float:
    """Mean held-out AUC. If fit=False, evaluate the defaults (no optimization)."""
    aucs: list[float] = []
    for f in range(N_FOLDS):
        train = [i for i in range(len(g_rows)) if folds[i] != f]
        held = [i for i in range(len(g_rows)) if folds[i] == f]
        if not held or sum(labels[i] for i in held) == 0:
            continue
        if fit:
            sp, cp = optimize(g_rows, labels, train, section_of, cats_by_section,
                              sec0, cat0, sec_boxes, cat_boxes, lam)
        else:
            sp, cp = sec0, cat0
        scores = score_rows(g_rows, sp, cp, section_of)
        aucs.append(auc(scores, labels, held))
    return sum(aucs) / len(aucs) if aucs else 0.5


# --- Main ---------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fit section + category weights to the gold set (regularized)."
    )
    parser.add_argument("--raw", default="../_raw")
    args = parser.parse_args()
    raw = Path(args.raw).resolve()
    output_root = raw.parent
    config_path = output_root / "account-scoring-weights.json"
    data_path = output_root / "data.csv"
    report_path = raw / "_weight_fit_report.json"

    if not config_path.exists():
        print(f"[fit] {config_path.name} not found — nothing to fit.")
        return
    config = json.loads(config_path.read_text())
    signals = {k: v for k, v in config.get("signals", {}).items() if isinstance(v, dict)}
    categories = config.get("categories", {})
    sections = config.get("sections", {})

    rows: list[dict[str, str]] = []
    if data_path.exists():
        with data_path.open() as fh:
            rows = list(csv.DictReader(fh))

    def write_report(status: str, extra: dict | None = None) -> None:
        rep = {"status": status, **(extra or {})}
        report_path.write_text(json.dumps(rep, indent=2))
        print(f"[fit] {status}")

    if not rows or "is_icp_gold" not in (rows[0] if rows else {}):
        write_report("skipped_no_gold_column")
        return
    labels = [1 if int(_f(r.get("is_icp_gold"))) == 1 else 0 for r in rows]
    n_gold, n_nongold = sum(labels), len(labels) - sum(labels)
    if n_gold < MIN_GOLD_FOR_FIT or n_nongold < MIN_NONGOLD_FOR_FIT:
        write_report(
            "skipped_small_gold",
            {"n_gold": n_gold, "n_nongold": n_nongold,
             "min_gold": MIN_GOLD_FOR_FIT, "note": "too few gold — kept priors"},
        )
        return

    # Live sections / categories present in the config.
    section_of = {c: categories[c].get("section") for c in categories}
    cats_by_section: dict[str, list[str]] = {}
    for c, meta in categories.items():
        sec = meta.get("section")
        if sec:
            cats_by_section.setdefault(sec, []).append(c)
    live_sections = [s for s in sections if cats_by_section.get(s)]
    if not live_sections:
        write_report("skipped_no_sections")
        return

    # Priors = the policy defaults. If a prior fit is recorded (manual re-run
    # without rebuilding), recover the ORIGINAL priors from it so re-running is
    # idempotent rather than compounding the previous fit.
    prev = config.get("_weight_fit") or {}
    prev_sec = prev.get("section_before") or {}
    prev_cat = prev.get("category_before") or {}
    sec0 = {
        s: float(prev_sec.get(s, sections[s].get("default_pct") or 0.0))
        for s in live_sections
    }
    tot = sum(sec0.values()) or 1.0
    sec0 = {s: 100.0 * v / tot for s, v in sec0.items()}
    cat0 = {
        c: float(prev_cat.get(c, categories[c].get("default_pct") or 0.0))
        for c in categories
    }
    # Reset config to the priors up front, so the written state is always
    # "priors, plus this run's fit (if adopted)" regardless of prior contents.
    for s in live_sections:
        sections[s]["default_pct"] = round(sec0[s], 4)
    for c in categories:
        categories[c]["default_pct"] = round(cat0[c], 4)
    config.pop("_weight_fit", None)

    g_rows, _ = build_category_norms(rows, signals)

    sec_boxes = {
        s: (max(0.0, sec0[s] - SECTION_BAND), min(100.0, sec0[s] + SECTION_BAND))
        for s in live_sections
    }
    cat_boxes = {
        c: (max(0.0, cat0[c] - CATEGORY_BAND), min(100.0, cat0[c] + CATEGORY_BAND))
        for c in categories
    }
    folds = stratified_folds(rows, labels)

    default_auc = cv_heldout_auc(
        g_rows, labels, folds, section_of, cats_by_section,
        sec0, cat0, sec_boxes, cat_boxes, lam=0.0, fit=False,
    )
    best_lam, best_auc = None, default_auc
    for lam in LAMBDA_GRID:
        m = cv_heldout_auc(
            g_rows, labels, folds, section_of, cats_by_section,
            sec0, cat0, sec_boxes, cat_boxes, lam=lam, fit=True,
        )
        if best_lam is None or m > best_auc + 1e-9:
            best_lam, best_auc = lam, m

    base_scores = score_rows(g_rows, sec0, cat0, section_of)
    base_lift = lift_at_decile(base_scores, labels)

    if best_lam is None or best_auc < default_auc + ADOPT_MARGIN_AUC:
        config_path.write_text(json.dumps(config, indent=2))  # priors-reset state
        write_report(
            "kept_defaults_no_generalizing_gain",
            {"n_gold": n_gold, "default_heldout_auc": round(default_auc, 4),
             "best_fitted_heldout_auc": round(best_auc, 4),
             "adopt_margin": ADOPT_MARGIN_AUC, "default_lift_at_decile": round(base_lift, 3)},
        )
        return

    # Refit on the full sample with the CV-chosen lambda, then adopt.
    sp, cp = optimize(
        g_rows, labels, list(range(len(g_rows))), section_of, cats_by_section,
        sec0, cat0, sec_boxes, cat_boxes, lam=best_lam,
    )
    fit_scores = score_rows(g_rows, sp, cp, section_of)
    fit_lift = lift_at_decile(fit_scores, labels)

    for s in live_sections:
        sections[s]["default_pct"] = round(sp[s], 4)
    for c in categories:
        if c in cp:
            categories[c]["default_pct"] = round(cp[c], 4)

    config["_weight_fit"] = {
        "method": "regularized_section_category_fit_to_gold",
        "lambda": best_lam,
        "n_gold": n_gold,
        "n_nongold": n_nongold,
        "default_heldout_auc": round(default_auc, 4),
        "fitted_heldout_auc": round(best_auc, 4),
        "default_lift_at_decile": round(base_lift, 3),
        "fitted_lift_at_decile": round(fit_lift, 3),
        "section_before": {s: round(sec0[s], 2) for s in live_sections},
        "section_after": {s: round(sp[s], 2) for s in live_sections},
        "category_before": {c: round(cat0[c], 2) for c in categories},
        "category_after": {c: round(cp[c], 2) for c in categories},
        "note": (
            "Within-category signal weights are frozen; only the section blend "
            "and category weights were fit, shrunk toward the priors and adopted "
            "only because held-out AUC improved. These are the app's starting "
            "sliders — still fully tunable."
        ),
    }
    config_path.write_text(json.dumps(config, indent=2))
    write_report("adopted_fit", config["_weight_fit"])


if __name__ == "__main__":
    main()
