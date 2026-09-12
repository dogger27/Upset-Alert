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

HEAD-TO-HEAD WAS TESTED HERE AND REJECTED (2026-09-12). `--h2h` adds a
shrunk prior-meetings term, (wins - losses) / (wins + losses + shrink),
counted over every match in the record. It fits: the coefficient comes out
positive (~0.14) and the fitting years like it. It does not generalise —
on the judged season it is WORSE in every configuration and every subset:

    all judged (n=1717)   without 0.6139   with 0.6140
    met >= 1   (n= 821)   without 0.6017   with 0.6021
    met >= 3   (n= 220)   without 0.6380   with 0.6406
    met >= 5   (n=  75)   without 0.6624   with 0.6648

Worst where it should help most, which is the signature of a rating that
already contains the information. Same at shrink 0/2/5, same restricted to
the match's own surface (29% availability), same per tour. A prior meeting
exists for only 48% of matches anyway. Rerun with --h2h if the record grows
enough to change this; do not add the term on intuition.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.services.history import db as hdb                       # noqa: E402
from app.services.history.ratings import load_rows, norm_surface, walk   # noqa: E402
from fit_winprob import _bo5, log_loss, nelder_mead, brier, LN10_400, RANK_CAP  # noqa: E402

TOUR_LEVELS = {"G", "M", "A", "500", "250", "1000", "F", "D"}


def collect(rows, cfg, judge_levels=TOUR_LEVELS, tour=None, h2h_shrink=2.0, h2h_surface=False):
    """Walk once; return arrays for every played tour-level main-draw match:
    date, overall/surface Elo of both sides, counts, ranks, bo5, result."""
    dates, ow, sw, ol, sl, nw, nl, bo5, rw, rl, h2h, met, ident = [], [], [], [], [], [], [], [], [], [], [], [], []
    # PRIOR MEETINGS, counted as the walk passes them — every match in the
    # record, not just tour level, because a Challenger meeting is a meeting.
    # Keyed on the pair, and on the surface too with --h2h-surface.
    seen: dict = {}
    for r, pre_w, pre_l in walk(rows, cfg):
        tour_, w_id, l_id, surface = r[0], r[7], r[8], norm_surface(r[3])
        lo = min(w_id, l_id)
        key = (tour_, *sorted((w_id, l_id))) + ((surface,) if h2h_surface else ())
        prior = seen.get(key, (0, 0))          # (wins by lo, wins by hi)
        if r[4] in judge_levels and r[10] in (3, 5) and not (tour and tour_ != tour):
            w_won, l_won = (prior[0], prior[1]) if w_id == lo else (prior[1], prior[0])
            dates.append(r[2]); ow.append(pre_w[0]); sw.append(pre_w[1]); ol.append(pre_l[0]); sl.append(pre_l[1])
            nw.append(pre_w[2]); nl.append(pre_l[2]); bo5.append(r[10] == 5); ident.append((tour_, w_id, l_id))
            rw.append(min(r[12], RANK_CAP) if r[12] else RANK_CAP); rl.append(min(r[13], RANK_CAP) if r[13] else RANK_CAP)
            # Shrunk toward nothing, so one meeting is not a verdict and
            # twenty do not swamp the rating: (w - l) / (w + l + shrink).
            denom = w_won + l_won + h2h_shrink
            h2h.append((w_won - l_won) / denom if denom else 0.0)
            met.append(w_won + l_won)
        seen[key] = (prior[0] + (1 if w_id == lo else 0), prior[1] + (0 if w_id == lo else 1))
    return dict(date=np.array(dates), ow=np.array(ow), sw=np.array(sw), ol=np.array(ol), sl=np.array(sl),
                nw=np.array(nw), nl=np.array(nl), bo5=np.array(bo5),
                d_rank=np.log2(np.array(rl, float) / np.array(rw, float)),
                h2h=np.array(h2h), met=np.array(met), ident=ident)


def probs(theta, names, data, mask):
    """P(winner wins) — the winner is always 'player 1' here, so y = 1.
    `names` labels theta, so --rank and --h2h combine in any order.
    Symmetric by construction: every term is a difference."""
    t = dict(zip(names, theta))
    w = min(max(t["surface_w"], 0.0), 1.0)
    rw = w * data["sw"][mask] + (1 - w) * data["ow"][mask]
    rl = w * data["sl"][mask] + (1 - w) * data["ol"][mask]
    z = t["slope"] * LN10_400 * (rw - rl)
    if "k_rank" in t:
        z = z + t["k_rank"] * data["d_rank"][mask]
    if "k_h2h" in t:
        z = z + t["k_h2h"] * data["h2h"][mask]
    p3 = 1 / (1 + np.exp(-z))
    p = np.where(data["bo5"][mask], _bo5(p3), p3)
    return np.clip(p, 1e-6, 1 - 1e-6)


def evaluate(theta, names, data, mask):
    p = probs(theta, names, data, mask)
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
    ap.add_argument("--h2h", action="store_true", help="fit a head-to-head term beside the rating")
    ap.add_argument("--h2h-shrink", type=float, default=2.0, help="(w-l)/(w+l+shrink); bigger = one meeting counts less")
    ap.add_argument("--h2h-surface", action="store_true", help="count only prior meetings on the same surface")
    ap.add_argument("--market", action="store_true",
                    help="also report the betting market on exactly the judged matches it priced")
    a = ap.parse_args()
    level_k = json.loads(a.level_k)
    init = not a.no_surface_init

    conn = hdb.connect()
    rows = load_rows(conn)
    print(f"{len(rows)} matches in the record; walking one pass per K schedule …")

    grid = ([(150.0, 0.3), (250.0, 0.4)] if a.grid == "quick"
            else [(k0, dec) for k0 in (150.0, 200.0, 250.0, 300.0, 350.0) for dec in (0.3, 0.4, 0.5)])
    names = ["slope", "surface_w"] + (["k_rank"] if a.rank else []) + (["k_h2h"] if a.h2h else [])
    x0 = [1.0, 0.5] + ([0.1] if a.rank else []) + ([0.2] if a.h2h else [])
    results = []
    for k0, dec in grid:
        cfg = {"k0": k0, "k_decay": dec, "k_offset": a.k_offset, "level_k": level_k, "surface_from_overall": init,
               "k_floor": a.k_floor}
        data = collect(rows, cfg, tour=a.tour, h2h_shrink=a.h2h_shrink, h2h_surface=a.h2h_surface)
        rated = (data["nw"] >= a.min_matches) & (data["nl"] >= a.min_matches)
        fit_m = rated & (data["date"] < a.fit_before)
        val_m = rated & (data["date"] >= a.fit_before) & (data["date"] < "2026-01-01")
        judge_m = rated & (data["date"] >= a.judge_from)
        theta, _ = nelder_mead(lambda t: evaluate(t, names, data, fit_m)[0], x0)
        ll_fit = evaluate(theta, names, data, fit_m)[0]
        ll_val, br_val, acc_val = evaluate(theta, names, data, val_m)
        ll_j, br_j, acc_j = evaluate(theta, names, data, judge_m)
        results.append((ll_val, k0, dec, theta, ll_fit, ll_j, br_j, acc_j, int(val_m.sum()), int(judge_m.sum())))
        print(f"  k0={k0:5.0f} decay={dec:.1f}  " + " ".join(f"{n}={v:.3f}" for n, v in zip(names, theta)) + "   "
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

    # ── THE MARKET, ON EXACTLY THE MATCHES IT PRICED ────────────────────────
    # The subset matters more than the number: quoting our log loss over the
    # whole judged window against the market's over the half of it that has
    # odds would compare two different sets of matches and mean nothing.
    if a.market:
        from app.services.history.odds import market_probabilities
        cfg_m = {"k0": k0, "k_decay": dec, "k_offset": a.k_offset, "level_k": level_k,
                 "surface_from_overall": init, "k_floor": a.k_floor}
        dm = collect(rows, cfg_m, tour=a.tour, h2h_shrink=a.h2h_shrink, h2h_surface=a.h2h_surface)
        rated_m = (dm["nw"] >= a.min_matches) & (dm["nl"] >= a.min_matches)
        jm = rated_m & (dm["date"] >= a.judge_from)
        mkt = market_probabilities(hdb.connect(), since=a.judge_from, tour=a.tour)
        have = np.array([k in mkt for k in dm["ident"]])
        both = jm & have
        if both.sum() < 30:
            print(f"\nmarket: only {int(both.sum())} judged matches carry a price - too few to compare")
        else:
            p_us = probs(theta, names, dm, both)
            p_mkt = np.array([mkt[k] for k, m in zip(dm["ident"], both) if m])
            y = np.ones_like(p_us)
            print(f"\n=== THE MARKET, on the {int(both.sum())} judged matches it priced "
                  f"({100 * float(both.sum()) / max(1, int(jm.sum())):.0f}% of the judged window) ===")
            print(f"  ours   ll={log_loss(p_us, y):.4f}  brier={brier(p_us, y):.4f}  acc={np.mean(p_us >= 0.5):.3f}")
            print(f"  market ll={log_loss(p_mkt, y):.4f}  brier={brier(p_mkt, y):.4f}  acc={np.mean(p_mkt >= 0.5):.3f}")
            gap = log_loss(p_us, y) - log_loss(p_mkt, y)
            print(f"  gap    {gap:+.4f} log loss  ({'we are behind' if gap > 0 else 'we are ahead'})")
            # IS THE GAP REAL? A paired bootstrap over matches. Log loss on a
            # few hundred matches moves by more than a hundredth on noise
            # alone, so a gap without an interval is not a finding.
            per_us = -np.log(p_us)
            per_mkt = -np.log(p_mkt)
            diff = per_us - per_mkt
            rng = np.random.default_rng(7)
            boot = np.array([diff[rng.integers(0, len(diff), len(diff))].mean() for _ in range(4000)])
            lo_ci, hi_ci = np.percentile(boot, [2.5, 97.5])
            verdict = ("we are genuinely behind" if lo_ci > 0 else
                       "we are genuinely ahead" if hi_ci < 0 else
                       "INSIDE NOISE — no difference demonstrated")
            print(f"  95% CI on the gap: {lo_ci:+.4f} .. {hi_ci:+.4f}   -> {verdict}")
            agree = (p_us >= 0.5) == (p_mkt >= 0.5)
            if (~agree).sum() > 5:
                print(f"  same favourite on {100 * agree.mean():.0f}%; on the {int((~agree).sum())} we disagree about, "
                      f"ours ll={log_loss(p_us[~agree], y[~agree]):.3f} vs market {log_loss(p_mkt[~agree], y[~agree]):.3f}")
            # BAND ON THE FAVOURITE'S PRICE, not the winner's. p is P(the
            # actual winner wins), so banding it from 0.5 up quietly drops
            # every upset — a third of the sample, and the third a model is
            # most likely to differ on.
            fav_mkt = np.where(p_mkt >= 0.5, p_mkt, 1 - p_mkt)
            upset = p_mkt < 0.5
            print(f"  the market's favourite lost {int(upset.sum())} of {len(p_mkt)} ({100*upset.mean():.0f}%); "
                  f"there ours ll={log_loss(p_us[upset], y[upset]):.3f} vs market {log_loss(p_mkt[upset], y[upset]):.3f}; "
                  f"elsewhere ours ll={log_loss(p_us[~upset], y[~upset]):.3f} vs market {log_loss(p_mkt[~upset], y[~upset]):.3f}")
            for lo, hi in ((0.5, 0.65), (0.65, 0.8), (0.8, 1.01)):
                m = (fav_mkt >= lo) & (fav_mkt < hi)
                if m.sum() > 20:
                    print(f"  market's favourite priced {lo:.0%}-{min(hi,1):.0%} (n={int(m.sum()):4}): "
                          f"ours ll={log_loss(p_us[m], y[m]):.4f}  market ll={log_loss(p_mkt[m], y[m]):.4f}")

    # Calibration on the judged window for the chosen model.
    cfg = {"k0": k0, "k_decay": dec, "k_offset": a.k_offset, "level_k": level_k, "surface_from_overall": init,
           "k_floor": a.k_floor}
    data = collect(rows, cfg, tour=a.tour, h2h_shrink=a.h2h_shrink, h2h_surface=a.h2h_surface)
    rated = (data["nw"] >= a.min_matches) & (data["nl"] >= a.min_matches)
    judge_m = rated & (data["date"] >= a.judge_from)
    p = probs(theta, names, data, judge_m)
    fav = np.where(p >= 0.5, p, 1 - p); won = (p >= 0.5).astype(float)
    print("\ncalibration on the judged window (favourite's stated chance vs how often it won):")
    for lo, hi in ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)):
        m = (fav >= lo) & (fav < hi)
        if m.sum():
            print(f"  {lo:.0%}-{min(hi, 1):.0%}: n={int(m.sum()):4}  stated={fav[m].mean():.3f}  actual={won[m].mean():.3f}")

    t = dict(zip(names, theta))
    own = {"k0": k0, "k_decay": dec, "k_offset": a.k_offset, "k_floor": a.k_floor, "level_k": level_k,
           "surface_from_overall": init,
           "surface_w": round(float(t["surface_w"]), 3), "k_logit": round(float(t["slope"]), 3),
           "k_rank": round(float(t.get("k_rank", 0.0)), 3),
           "k_h2h": round(float(t.get("k_h2h", 0.0)), 3), "h2h_shrink": a.h2h_shrink,
           "h2h_surface": a.h2h_surface, "fitted": True}

    # WHERE H2H COULD MATTER AT ALL: how many judged matches have a history,
    # and does the term earn its keep on those alone?
    if a.h2h:
        print(f"\nhead-to-head availability in the judged window: "
              f"{int((data['met'][judge_m] > 0).sum())} of {int(judge_m.sum())} matches have a prior meeting "
              f"({100 * float((data['met'][judge_m] > 0).mean()):.0f}%), "
              f"{int((data['met'][judge_m] >= 3).sum())} have three or more")
        base = ["slope", "surface_w"] + (["k_rank"] if a.rank else [])
        th0, _ = nelder_mead(lambda t_: evaluate(t_, base, data, fit_m)[0], x0[:len(base)])
        for label, sub in (("all judged", judge_m),
                           ("met >= 1", judge_m & (data["met"] >= 1)),
                           ("met >= 3", judge_m & (data["met"] >= 3)),
                           ("met >= 5", judge_m & (data["met"] >= 5))):
            if sub.sum() < 30:
                continue
            with_h = evaluate(theta, names, data, sub)[0]
            without = evaluate(th0, base, data, sub)[0]
            print(f"  {label:11} n={int(sub.sum()):5}  without H2H ll={without:.4f}  with H2H ll={with_h:.4f}  "
                  f"{'better' if with_h < without else 'WORSE'} by {abs(without - with_h):.4f}")
    print('\nmodels.json "own":', json.dumps(own))


if __name__ == "__main__":
    main()
