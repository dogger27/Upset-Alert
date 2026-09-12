"""Fit and test the win-probability model on OUR results, without leaks.

    backend/.venv/bin/python scripts/fit_winprob.py [path/to/db] [--split 2026-08-10]

`winprob_calibration.py` scores every match with today's Elo, which flatters
the model: September's rating knows how March went. This script is the honest
version. Every match is scored with the ratings as they stood on the Monday
the tournament STARTED — the last weekly snapshot on or before `start_date` —
so nothing the model sees postdates the result it is asked to predict.

It then fits the one number the vendored package leaves open, `logit_scale`
(how steep the Elo curve is), and tries the two cheap extensions worth trying:
a per-tour scale, and a rank term beside Elo. Everything is fitted on draws
that started before `--split` and judged on the ones after, so the numbers at
the end are out-of-sample. A better in-sample fit that does not survive the
split is reported and not recommended.

No scipy here (it is not a dependency); the optimiser is a Nelder-Mead in
thirty lines, which is plenty for three smooth parameters.
"""
import argparse
import math
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.winprob.sets import match_from_set_prob, set_prob_from_match_prob  # noqa: E402

LN10_400 = math.log(10) / 400.0
RANK_CAP = 500


# ── data ──────────────────────────────────────────────────────────────────────

def best_of(nsets, gender, category):
    if nsets in (3, 5):
        return nsets
    return 5 if (gender == "M" and "Grand" in (category or "")) else 3


def norm_surface(s):
    s = (s or "Hard").strip().lower()
    return "Clay" if s.startswith("clay") else "Grass" if s.startswith("grass") else "Hard"


def load(db_path: str):
    """One row per completed match, rated as of the tournament's first Monday."""
    c = sqlite3.connect(db_path)
    first_week = c.execute(
        "SELECT min(week_date) FROM te_rankings_snapshots WHERE elo IS NOT NULL").fetchone()[0]
    weeks = [r[0] for r in c.execute(
        "SELECT DISTINCT week_date FROM te_rankings_snapshots WHERE elo IS NOT NULL ORDER BY 1")]
    snaps = {}
    for pid, wk, elo, rank in c.execute(
            "SELECT player_id, week_date, elo, rank FROM te_rankings_snapshots WHERE week_date >= ?",
            (first_week,)):
        snaps[(pid, wk)] = (elo, rank)

    rows = c.execute("""
        SELECT d.id, d.start_date, d.gender, d.category, d.surface, d.sofa_number_of_sets,
               m.round_number, d.num_rounds, m.player1_id, m.winner_id,
               e1.te_player_id, e2.te_player_id, e1.ranking, e2.ranking
        FROM matches m
        JOIN draws d ON d.id = m.draw_id
        JOIN draw_entries e1 ON e1.id = m.player1_id
        JOIN draw_entries e2 ON e2.id = m.player2_id
        WHERE m.winner_id IS NOT NULL AND m.is_bye = 0 AND d.start_date >= ?
        ORDER BY d.start_date, m.round_number, m.match_number
    """, (first_week,)).fetchall()

    out = []
    for did, start, g, cat, surf, nsets, rnd, nr, p1, w, te1, te2, r1, r2 in rows:
        # The last weekly table published on or before the first day of play.
        wk = max((x for x in weeks if x <= start), default=None)
        if wk is None:
            continue
        e1, k1 = snaps.get((te1, wk), (None, None)) if te1 else (None, None)
        e2, k2 = snaps.get((te2, wk), (None, None)) if te2 else (None, None)
        out.append(dict(
            draw=did, start=start, gender=g, surface=norm_surface(surf),
            best_of=best_of(nsets, g, cat), slam="Grand" in (cat or ""),
            round_from_end=(nr or 7) - rnd,
            y=1 if w == p1 else 0,
            elo1=e1, elo2=e2,
            rank1=k1 or r1, rank2=k2 or r2,
        ))
    return out


# ── model ─────────────────────────────────────────────────────────────────────

def _bo5(p3: np.ndarray) -> np.ndarray:
    """The package's best-of-five step, vectorised by table: p3 -> p5."""
    grid = np.linspace(0.001, 0.999, 999)
    p5 = np.array([match_from_set_prob(set_prob_from_match_prob(p, 3), 5) for p in grid])
    return np.interp(p3, grid, p5)


def features(rows):
    """Per-match inputs as arrays. Elo difference is NaN where either is missing."""
    d_elo = np.array([(r["elo1"] - r["elo2"]) if (r["elo1"] and r["elo2"]) else np.nan for r in rows], float)
    rk1 = np.array([min(r["rank1"], RANK_CAP) if r["rank1"] else RANK_CAP for r in rows], float)
    rk2 = np.array([min(r["rank2"], RANK_CAP) if r["rank2"] else RANK_CAP for r in rows], float)
    d_rank = np.log2(rk2 / rk1)
    bo5 = np.array([r["best_of"] == 5 for r in rows])
    women = np.array([r["gender"] == "F" for r in rows])
    slam = np.array([r["slam"] for r in rows])
    surf = np.array([r["surface"] for r in rows])
    y = np.array([r["y"] for r in rows], float)
    return d_elo, d_rank, bo5, women, slam, surf, y


def predict(theta, spec, d_elo, d_rank, bo5, women, slam, surf):
    """P(player 1 wins) under a parameterisation.

    spec names the parameters in theta, in order. Elo pairs get the Elo
    curve; pairs missing a rating get the package's rank model with its own
    fitted slope (beta + bo5/clay/grass terms), untouched here.
    """
    t = dict(zip(spec, theta))
    k_elo = t.get("k_elo", 1.0)
    k_elo = np.where(women, t.get("k_elo_w", k_elo), k_elo) if "k_elo_w" in t else k_elo
    logit = k_elo * LN10_400 * d_elo
    if "k_rank" in t:
        logit = logit + t["k_rank"] * d_rank
    p3 = 1.0 / (1.0 + np.exp(-logit))
    # The rank-only fallback, exactly as shipped (models.json "rank").
    k_rank_only = 0.3837 + 0.1529 * bo5 - 0.0015 * (surf == "Clay") - 0.0579 * (surf == "Grass")
    p_rank = 1.0 / (1.0 + np.exp(-k_rank_only * d_rank))
    p = np.where(np.isnan(d_elo), p_rank, np.where(bo5, _bo5(np.nan_to_num(p3, nan=0.5)), p3))
    return np.clip(p, 1e-6, 1 - 1e-6)


def log_loss(p, y):
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def brier(p, y):
    return float(np.mean((p - y) ** 2))


def accuracy(p, y):
    return float(np.mean((p >= 0.5) == (y == 1)))


# ── optimiser ─────────────────────────────────────────────────────────────────

def nelder_mead(f, x0, step=0.3, iters=400, tol=1e-7):
    n = len(x0)
    pts = [np.array(x0, float)]
    for i in range(n):
        x = np.array(x0, float); x[i] += step; pts.append(x)
    vals = [f(x) for x in pts]
    for _ in range(iters):
        order = np.argsort(vals); pts = [pts[i] for i in order]; vals = [vals[i] for i in order]
        if abs(vals[-1] - vals[0]) < tol:
            break
        centroid = np.mean(pts[:-1], axis=0)
        xr = centroid + (centroid - pts[-1]); fr = f(xr)
        if fr < vals[0]:
            xe = centroid + 2 * (centroid - pts[-1]); fe = f(xe)
            pts[-1], vals[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = xr, fr
        else:
            xc = centroid + 0.5 * (pts[-1] - centroid); fc = f(xc)
            if fc < vals[-1]:
                pts[-1], vals[-1] = xc, fc
            else:
                pts = [pts[0]] + [pts[0] + 0.5 * (p - pts[0]) for p in pts[1:]]
                vals = [vals[0]] + [f(p) for p in pts[1:]]
    i = int(np.argmin(vals))
    return pts[i], vals[i]


def fit(spec, x0, data_train):
    d_elo, d_rank, bo5, women, slam, surf, y = data_train
    def obj(theta):
        return log_loss(predict(theta, spec, d_elo, d_rank, bo5, women, slam, surf), y)
    theta, val = nelder_mead(obj, x0)
    return theta, val


# ── report ────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db", nargs="?", default="tennis_fantasy.db")
    ap.add_argument("--split", default="2026-08-10", help="draws starting on/after this date are the test set")
    a = ap.parse_args()

    rows = load(a.db)
    train = [r for r in rows if r["start"] < a.split]
    test = [r for r in rows if r["start"] >= a.split]
    both = [r for r in rows if r["elo1"] and r["elo2"]]
    print(f"matches rated as of their tournament's first Monday: {len(rows)} "
          f"(both players with Elo: {len(both)}, {100 * len(both) / max(1, len(rows)):.0f}%)")
    print(f"train: {len(train)} matches in draws starting before {a.split}; test: {len(test)} after")
    print()

    F_train, F_test, F_all = features(train), features(test), features(rows)

    def report(label, theta, spec):
        p_tr = predict(theta, spec, *F_train[:-1]); p_te = predict(theta, spec, *F_test[:-1])
        print(f"{label:34} train: ll={log_loss(p_tr, F_train[-1]):.4f} acc={accuracy(p_tr, F_train[-1]):.3f}"
              f"   TEST: ll={log_loss(p_te, F_test[-1]):.4f} brier={brier(p_te, F_test[-1]):.4f} "
              f"acc={accuracy(p_te, F_test[-1]):.3f}")

    # Baselines: textbook Elo, the fallback model, and what is LIVE right now
    # (models.json "blend", overall Elo — the history holds no surface figure).
    import json
    live = json.loads((Path(__file__).resolve().parent.parent / "app/services/winprob/models.json").read_text())["blend"]
    report("Elo as shipped (scale 1.0)", [1.0], ["k_elo"])
    report(f"LIVE blend {[live['k_elo'], live['k_rank']]}", [live["k_elo"], live["k_rank"]], ["k_elo", "k_rank"])
    # Rank only: hand every pair to the fallback by hiding the Elo.
    d_elo, d_rank, bo5, women, slam, surf, y = F_test
    p_rank = predict([1.0], ["k_elo"], np.full_like(d_elo, np.nan), d_rank, bo5, women, slam, surf)
    print(f"{'rank only (the fallback model)':34} {'':40}   TEST: ll={log_loss(p_rank, y):.4f} brier={brier(p_rank, y):.4f} acc={accuracy(p_rank, y):.3f}")
    print()

    fits = {}
    for label, spec, x0 in (
        ("Elo, fitted scale", ["k_elo"], [1.0]),
        ("Elo, per-tour scale", ["k_elo", "k_elo_w"], [1.0, 1.0]),
        ("Elo + rank term", ["k_elo", "k_rank"], [1.0, 0.0]),
        ("Elo + rank, per-tour", ["k_elo", "k_elo_w", "k_rank"], [1.0, 1.0, 0.0]),
    ):
        theta, val = fit(spec, x0, F_train)
        fits[label] = (spec, theta)
        report(f"{label} {np.round(theta, 3).tolist()}", theta, spec)
    print()

    # Does the best-of-five step earn its keep? Men's Slam matches only.
    men_slam = [r for r in rows if r["best_of"] == 5 and r["elo1"] and r["elo2"]]
    if men_slam:
        Fm = features(men_slam)
        spec, theta = fits["Elo, fitted scale"]
        p_with = predict(theta, spec, *Fm[:-1])
        p_without = predict(theta, spec, Fm[0], Fm[1], np.zeros_like(Fm[2]), *Fm[3:-1])
        print(f"best-of-five ({len(men_slam)} men's Slam matches): "
              f"ll with set combinatorics={log_loss(p_with, Fm[-1]):.4f}, treating as bo3={log_loss(p_without, Fm[-1]):.4f}")

    # The honest slope by surface: the pooled number is a weighted average of
    # three quite different ones, and the window is a third grass.
    for s_name in ("Hard", "Clay", "Grass"):
        sub = [r for r in rows if r["surface"] == s_name]
        if len(sub) >= 80:
            th, val = fit(["k_elo"], [1.0], features(sub))
            print(f"  overall-Elo slope on {s_name:5} alone: k={th[0]:.3f} ll={val:.4f} (n={len(sub)})")

    # Calibration by decile, on the whole leak-free set, for the fitted Elo.
    spec, theta = fits["Elo, fitted scale"]
    p_all = predict(theta, spec, *F_all[:-1]); y_all = F_all[-1]
    fav = np.where(p_all >= 0.5, p_all, 1 - p_all); won = np.where(p_all >= 0.5, y_all, 1 - y_all)
    print("\ncalibration (favourite's stated chance vs. how often the favourite won):")
    for lo, hi in ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)):
        m = (fav >= lo) & (fav < hi)
        if m.sum():
            print(f"  {lo:.0%}-{min(hi, 1):.0%}: n={int(m.sum()):4}  stated={fav[m].mean():.3f}  actual={won[m].mean():.3f}")

    # THE MODEL TO SHIP: Elo plus the rank term, one scale for both tours.
    # The per-tour split fits better on both halves but on ~1σ of evidence,
    # in a window dominated by grass, and against everything published about
    # the two tours (women's results are the LESS predictable ones) — so it
    # stays an experiment here until the surface ratings have a history.
    # Refit on everything for the numbers to ship, with a bootstrap for the
    # error bars, and say so.
    spec = ["k_elo", "k_rank"]
    theta_all, _ = fit(spec, fits["Elo + rank term"][1], F_all)
    rng = np.random.default_rng(7)
    boots = []
    for _ in range(60):
        idx = rng.integers(0, len(rows), len(rows))
        Fb = tuple(a[idx] for a in F_all)
        boots.append(fit(spec, theta_all, Fb)[0])
    boots = np.array(boots)
    lo, hi = np.percentile(boots, [5, 95], axis=0)
    print(f"\nElo + rank refitted on all {len(rows)} leak-free matches:")
    for i, name in enumerate(spec):
        print(f"  {name:7} = {theta_all[i]:.3f}   (90% bootstrap: {lo[i]:.3f} .. {hi[i]:.3f})")
    print('\nmodels.json  "blend": {"k_elo": %.3f, "k_rank": %.3f}' % tuple(theta_all))


if __name__ == "__main__":
    main()
