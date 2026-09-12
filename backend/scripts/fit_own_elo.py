"""Fit our own Elo on the record, and judge it where it will be used.

    backend/.venv/bin/python scripts/fit_own_elo.py [--fit-before 2024-01-01] [--judge-from 2026-06-22]

One chronological pass per K schedule over every match in the history
database (TennisMyLife's plus our own), collecting each tour-level match's
pre-match ratings. The schedule is chosen on the VALIDATION years (between
--fit-before and 2026), and the slope, the surface mix and the ranking term
are fitted on the fitting years and re-checked there. Then the whole thing
is judged on the same window Tennis Abstract's Elo was judged on
(fit_winprob.py: tour-level matches from --judge-from), so the two numbers
are the same kind of number.

Nothing here reads a rating that postdates the match it predicts: the pass
yields the state BEFORE each match, which is stricter than the first-Monday
rule the Tennis Abstract check had to settle for. Prints the "own" section
for winprob/models.json.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.services.history import db as hdb                       # noqa: E402
from app.services.history.ratings import load_rows, walk         # noqa: E402
from fit_winprob import _bo5, log_loss, nelder_mead, brier, LN10_400, RANK_CAP  # noqa: E402

TOUR_LEVELS = {"G", "M", "A", "500", "250", "1000", "F", "D"}


def collect(rows, cfg, judge_levels=TOUR_LEVELS, tour=None):
    """Walk once; return arrays for every played tour-level main-draw match:
    date, overall/surface Elo of both sides, counts, ranks, bo5, result."""
    dates, ow, sw, ol, sl, nw, nl, bo5, rw, rl = [], [], [], [], [], [], [], [], [], []
    for r, pre_w, pre_l in walk(rows, cfg):
        if r[4] not in judge_levels or r[10] not in (3, 5) or (tour and r[0] != tour):
            continue
        dates.append(r[2]); ow.append(pre_w[0]); sw.append(pre_w[1]); ol.append(pre_l[0]); sl.append(pre_l[1])
        nw.append(pre_w[2]); nl.append(pre_l[2]); bo5.append(r[10] == 5)
        rw.append(min(r[12], RANK_CAP) if r[12] else RANK_CAP); rl.append(min(r[13], RANK_CAP) if r[13] else RANK_CAP)
    return dict(date=np.array(dates), ow=np.array(ow), sw=np.array(sw), ol=np.array(ol), sl=np.array(sl),
                nw=np.array(nw), nl=np.array(nl), bo5=np.array(bo5),
                d_rank=np.log2(np.array(rl, float) / np.array(rw, float)))


def probs(theta, data, mask):
    """P(winner wins) — the winner is always 'player 1' here, so y = 1 — under
    (slope, surface_w, k_rank). Symmetric by construction."""
    slope, w = theta[0], min(max(theta[1], 0.0), 1.0)
    k_rank = theta[2] if len(theta) > 2 else 0.0
    rw = w * data["sw"][mask] + (1 - w) * data["ow"][mask]
    rl = w * data["sl"][mask] + (1 - w) * data["ol"][mask]
    z = slope * LN10_400 * (rw - rl) + k_rank * data["d_rank"][mask]
    p3 = 1 / (1 + np.exp(-z))
    p = np.where(data["bo5"][mask], _bo5(p3), p3)
    return np.clip(p, 1e-6, 1 - 1e-6)


def evaluate(theta, data, mask):
    p = probs(theta, data, mask)
    y = np.ones_like(p)
    # Every row is a win for "player 1"; to keep accuracy meaningful, count a
    # match right when the model favoured the winner.
    return log_loss(p, y), brier(p, y), float(np.mean(p >= 0.5))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit-before", default="2024-01-01")
    ap.add_argument("--judge-from", default="2026-06-22")
    ap.add_argument("--min-matches", type=int, default=10, help="both players need this many prior matches to be judged")
    ap.add_argument("--grid", default="full", choices=["full", "quick"], help="quick: two K schedules, for a variant check")
    ap.add_argument("--no-surface-init", action="store_true", help="surface ratings start at 1500, not the overall rating")
    ap.add_argument("--rank", action="store_true", help="fit a ranking term beside the rating")
    ap.add_argument("--tour", default=None, choices=["atp", "wta"], help="judge one tour only")
    ap.add_argument("--level-k", default="{}", help='JSON K multipliers by tourney_level, e.g. {"G":1.2,"C":0.7}')
    ap.add_argument("--k-floor", type=float, default=0.0, help="K never falls below this")
    ap.add_argument("--k-offset", type=float, default=5.0, help="the +offset in K = k0/(n+offset)^decay")
    a = ap.parse_args()
    level_k = json.loads(a.level_k)
    init = not a.no_surface_init

    conn = hdb.connect()
    rows = load_rows(conn)
    print(f"{len(rows)} matches in the record; walking one pass per K schedule …")

    grid = ([(150.0, 0.3), (250.0, 0.4)] if a.grid == "quick"
            else [(k0, dec) for k0 in (150.0, 200.0, 250.0, 300.0, 350.0) for dec in (0.3, 0.4, 0.5)])
    x0 = [1.0, 0.5, 0.1] if a.rank else [1.0, 0.5]
    results = []
    for k0, dec in grid:
        cfg = {"k0": k0, "k_decay": dec, "k_offset": a.k_offset, "level_k": level_k, "surface_from_overall": init,
               "k_floor": a.k_floor}
        data = collect(rows, cfg, tour=a.tour)
        rated = (data["nw"] >= a.min_matches) & (data["nl"] >= a.min_matches)
        fit_m = rated & (data["date"] < a.fit_before)
        val_m = rated & (data["date"] >= a.fit_before) & (data["date"] < "2026-01-01")
        judge_m = rated & (data["date"] >= a.judge_from)
        theta, _ = nelder_mead(lambda t: evaluate(t, data, fit_m)[0], x0)
        ll_fit = evaluate(theta, data, fit_m)[0]
        ll_val, br_val, acc_val = evaluate(theta, data, val_m)
        ll_j, br_j, acc_j = evaluate(theta, data, judge_m)
        results.append((ll_val, k0, dec, theta, ll_fit, ll_j, br_j, acc_j, int(val_m.sum()), int(judge_m.sum())))
        print(f"  k0={k0:5.0f} decay={dec:.1f}  slope={theta[0]:.3f} surface_w={theta[1]:.2f}"
              + (f" k_rank={theta[2]:.3f}" if a.rank else "") + "   "
              f"fit ll={ll_fit:.4f}   VAL ll={ll_val:.4f} (n={int(val_m.sum())})   2026 ll={ll_j:.4f} acc={acc_j:.3f} (n={int(judge_m.sum())})")

    results.sort()
    ll_val, k0, dec, theta, ll_fit, ll_j, br_j, acc_j, n_val, n_j = results[0]
    print(f"\nchosen on validation: k0={k0:.0f} decay={dec:.1f} slope={theta[0]:.3f} surface_w={theta[1]:.2f}")
    print(f"  validation ({a.fit_before}..2026): ll={ll_val:.4f}")
    print(f"  judged from {a.judge_from} (tour-level, both players ≥{a.min_matches} matches): "
          f"ll={ll_j:.4f} brier={br_j:.4f} acc={acc_j:.3f} n={n_j}")
    print("  Tennis Abstract on the same season, honestly (fit_winprob.py, first-Monday ratings), BY TOUR — the\n"
          "  pooled figure misleads because the two judged sets carry different tour mixes:\n"
          "    atp: TA blend 0.632, TA Elo 0.641, rank model 0.638   wta: TA blend 0.579, TA Elo 0.577, rank 0.596\n"
          "  Compare per tour with --tour; parity per tour is the bar for switching `fitted` on.")

    # Calibration on the judged window for the chosen model.
    cfg = {"k0": k0, "k_decay": dec, "k_offset": a.k_offset, "level_k": level_k, "surface_from_overall": init,
           "k_floor": a.k_floor}
    data = collect(rows, cfg, tour=a.tour)
    rated = (data["nw"] >= a.min_matches) & (data["nl"] >= a.min_matches)
    judge_m = rated & (data["date"] >= a.judge_from)
    p = probs(theta, data, judge_m)
    fav = np.where(p >= 0.5, p, 1 - p); won = (p >= 0.5).astype(float)
    print("\ncalibration on the judged window (favourite's stated chance vs how often it won):")
    for lo, hi in ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)):
        m = (fav >= lo) & (fav < hi)
        if m.sum():
            print(f"  {lo:.0%}-{min(hi, 1):.0%}: n={int(m.sum()):4}  stated={fav[m].mean():.3f}  actual={won[m].mean():.3f}")

    own = {"k0": k0, "k_decay": dec, "k_offset": a.k_offset, "k_floor": a.k_floor, "level_k": level_k,
           "surface_from_overall": init,
           "surface_w": round(float(theta[1]), 3), "k_logit": round(float(theta[0]), 3),
           "k_rank": round(float(theta[2]), 3) if a.rank else 0.0, "fitted": True}
    print('\nmodels.json "own":', json.dumps(own))


if __name__ == "__main__":
    main()
