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

# Set once from the command line; probs() is called by the optimiser through a
# closure and threading another argument through every call site earns nothing.
SHRINK = [0.0, 0.0]
LAYOFF = [0.0, 60.0]


def collect(rows, cfg, judge_levels=TOUR_LEVELS, tour=None, h2h_shrink=2.0, h2h_surface=False):
    """Walk once; return arrays for every played tour-level main-draw match:
    date, overall/surface Elo of both sides, counts, ranks, bo5, result."""
    dates, ow, sw, ol, sl, nw, nl, bo5, rw, rl, h2h, met, ident, surf = [], [], [], [], [], [], [], [], [], [], [], [], [], []
    nsw, nsl, gapw, gapl = [], [], [], []
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
            nsw.append(pre_w[3]); nsl.append(pre_l[3])
            gapw.append(pre_w[4] if pre_w[4] is not None else 0)
            gapl.append(pre_l[4] if pre_l[4] is not None else 0)
            rw.append(min(r[12], RANK_CAP) if r[12] else RANK_CAP); rl.append(min(r[13], RANK_CAP) if r[13] else RANK_CAP)
            # Shrunk toward nothing, so one meeting is not a verdict and
            # twenty do not swamp the rating: (w - l) / (w + l + shrink).
            denom = w_won + l_won + h2h_shrink
            h2h.append((w_won - l_won) / denom if denom else 0.0)
            met.append(w_won + l_won); surf.append(surface)
        seen[key] = (prior[0] + (1 if w_id == lo else 0), prior[1] + (0 if w_id == lo else 1))
    return dict(date=np.array(dates), ow=np.array(ow), sw=np.array(sw), ol=np.array(ol), sl=np.array(sl),
                nw=np.array(nw), nl=np.array(nl), bo5=np.array(bo5),
                d_rank=np.log2(np.array(rl, float) / np.array(rw, float)),
                h2h=np.array(h2h), met=np.array(met), ident=ident, surf=surf,
                nsw=np.array(nsw), nsl=np.array(nsl),
                gapw=np.array(gapw), gapl=np.array(gapl))


def _surface_of(rows, data, i):
    """The surface of judged row i. collect() keeps the surface out of its
    arrays, so it is recovered from the walk's own normalisation."""
    return data.get("surf", ["Hard"] * (i + 1))[i] if "surf" in data else "Hard"


def probs(theta, names, data, mask):
    """P(winner wins) — the winner is always 'player 1' here, so y = 1.
    `names` labels theta, so --rank and --h2h combine in any order.
    Symmetric by construction: every term is a difference."""
    t = dict(zip(names, theta))
    w = min(max(t["surface_w"], 0.0), 1.0)
    rw = w * data["sw"][mask] + (1 - w) * data["ow"][mask]
    rl = w * data["sl"][mask] + (1 - w) * data["ol"][mask]
    # EVIDENCE-WEIGHTED SHRINKAGE. A rating built on twenty matches is a
    # guess wearing a number's clothes; one built on four hundred is not.
    # Pulling the thin ones toward the tour mean in proportion to how little
    # is behind them (James-Stein, as Gollub 2021 applies it to serve data)
    # lets the ranking term carry those players instead. This matters far
    # more for the women: the median player in our 2026 women's draws has 54
    # recorded matches against the men's 260, because the record has no WTA
    # Challenger or qualifying in it.
    if SHRINK[0] > 0 or SHRINK[1] > 0:
        # EACH COMPONENT BY ITS OWN EVIDENCE. The overall rating and the
        # surface rating are not equally supported: a player with four
        # hundred matches behind their overall figure may have nine behind
        # their grass one. Shrinking the blended number by the overall count
        # alone lets a grass rating built on a handful of matches through at
        # full strength, which is exactly the number most likely to be noise.
        n0, ns0 = SHRINK
        def _sh(r, n, k):
            return 1500.0 + (r - 1500.0) * (n / (n + k)) if k > 0 else r
        ow_ = _sh(data["ow"][mask], data["nw"][mask], n0)
        ol_ = _sh(data["ol"][mask], data["nl"][mask], n0)
        sw_ = _sh(data["sw"][mask], data["nsw"][mask], ns0)
        sl_ = _sh(data["sl"][mask], data["nsl"][mask], ns0)
        rw = w * sw_ + (1 - w) * ow_
        rl = w * sl_ + (1 - w) * ol_
    if LAYOFF[0] > 0:
        tau, grace = LAYOFF
        fw = np.exp(-np.maximum(0.0, data["gapw"][mask] - grace) / tau)
        fl = np.exp(-np.maximum(0.0, data["gapl"][mask] - grace) / tau)
        rw = 1500.0 + (rw - 1500.0) * fw
        rl = 1500.0 + (rl - 1500.0) * fl
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
    ap.add_argument("--recal", action="store_true",
                    help="fit a temperature on the VALIDATION years and apply it, then judge. Platt scaling: "
                         "the coefficients come from 1991-2023 and the tour has moved since.")
    ap.add_argument("--pin", default=None, metavar="K0,DECAY",
                    help="fit only this K schedule — for reading off the exact coefficients "
                         "of a configuration the grid already chose")
    ap.add_argument("--no-surface-init", action="store_true", help="surface ratings start at 1500, not the overall rating")
    ap.add_argument("--rank", action="store_true", help="fit a ranking term beside the rating")
    ap.add_argument("--tour", default=None, choices=["atp", "wta"], help="judge one tour only")
    ap.add_argument("--level-k", default="{}", help='JSON K multipliers by tourney_level, e.g. {"G":1.2,"C":0.7}')
    ap.add_argument("--k-floor", type=float, default=0.0, help="K never falls below this")
    ap.add_argument("--k-offset", type=float, default=5.0, help="the +offset in K = k0/(n+offset)^decay")
    ap.add_argument("--h2h", action="store_true", help="fit a head-to-head term beside the rating")
    ap.add_argument("--h2h-shrink", type=float, default=2.0, help="(w-l)/(w+l+shrink); bigger = one meeting counts less")
    ap.add_argument("--h2h-surface", action="store_true", help="count only prior meetings on the same surface")
    ap.add_argument("--shrink", type=float, default=0.0,
                    help="pull a thin OVERALL rating toward the tour mean: r <- 1500 + (r-1500)*n/(n+N). "
                         "A player with N matches keeps half their distance from the mean. 0 disables.")
    ap.add_argument("--shrink-surface", type=float, default=0.0,
                    help="the same for the SURFACE rating, against its own much thinner match count")
    ap.add_argument("--layoff", type=float, default=0.0,
                    help="decay a rating toward the mean after time off: factor exp(-(days-grace)/TAU). "
                         "0 disables. FiveThirtyEight's documented treatment of injury layoffs.")
    ap.add_argument("--layoff-grace", type=float, default=60.0,
                    help="days off that cost nothing (an off-season is not an injury)")
    ap.add_argument("--welo", action="store_true",
                    help="weight each update by the winner's share of games (Angelini et al. 2022)")
    ap.add_argument("--welo-retired", action="store_true",
                    help="believe a retirement's lopsided scoreline instead of treating it as neutral")
    ap.add_argument("--ensemble", action="store_true",
                    help="also report a 50/50 logit average with Tennis Abstract's independent Elo")
    ap.add_argument("--market", action="store_true",
                    help="also report the betting market on exactly the judged matches it priced")
    a = ap.parse_args()
    level_k = json.loads(a.level_k)
    SHRINK[0], SHRINK[1] = a.shrink, a.shrink_surface
    LAYOFF[0], LAYOFF[1] = a.layoff, a.layoff_grace
    init = not a.no_surface_init

    conn = hdb.connect()
    rows = load_rows(conn)
    print(f"{len(rows)} matches in the record; walking one pass per K schedule …")

    # WElo scales every update by the winner's share of games, which averages
    # about 0.63 — so the same effective K needs a larger k0, and the grid has
    # to reach further up or the comparison is rigged against it.
    k0s = (150.0, 200.0, 250.0, 300.0, 350.0, 450.0, 550.0) if a.welo else (150.0, 200.0, 250.0, 300.0, 350.0)
    if a.pin:
        grid = [tuple(float(x) for x in a.pin.split(","))]
    else:
        grid = ([(250.0, 0.4), (450.0, 0.4)] if (a.grid == "quick" and a.welo)
                else [(150.0, 0.3), (250.0, 0.4)] if a.grid == "quick"
                else [(k0, dec) for k0 in k0s for dec in (0.3, 0.4, 0.5)])
    names = ["slope", "surface_w"] + (["k_rank"] if a.rank else []) + (["k_h2h"] if a.h2h else [])
    x0 = [1.0, 0.5] + ([0.1] if a.rank else []) + ([0.2] if a.h2h else [])
    results = []
    for k0, dec in grid:
        cfg = {"k0": k0, "k_decay": dec, "k_offset": a.k_offset, "level_k": level_k, "surface_from_overall": init,
               "k_floor": a.k_floor, "welo": a.welo, "welo_retired": a.welo_retired}
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

    # ── CALIBRATION ON THE VALIDATION YEARS ─────────────────────────────────
    # k_logit is a temperature, but it was fitted on 1991-2023 and the tours
    # have moved since. A single multiplier re-fitted on 2024-25 alone — never
    # on the judged window — is the standard fix (Platt scaling), and it is
    # the one that matters most for a column that PRINTS percentages: a model
    # can carry a fine log loss while telling the reader 74% and delivering
    # 70%. Reported before/after on the judged window and per decile.
    if a.recal:
        de2 = collect(rows, cfg, tour=a.tour, h2h_shrink=a.h2h_shrink, h2h_surface=a.h2h_surface)
        rated2 = (de2["nw"] >= a.min_matches) & (de2["nl"] >= a.min_matches)
        val2 = rated2 & (de2["date"] >= a.fit_before) & (de2["date"] < "2026-01-01")
        jm2 = rated2 & (de2["date"] >= a.judge_from)

        def _scaled(temp, mask):
            q = probs(theta, names, de2, mask)
            lg = np.log(np.clip(q, 1e-9, 1 - 1e-9) / (1 - np.clip(q, 1e-9, 1 - 1e-9)))
            return np.clip(1 / (1 + np.exp(-temp * lg)), 1e-6, 1 - 1e-6)

        yv = np.ones(int(val2.sum()))
        temp, _ = nelder_mead(lambda t_: log_loss(_scaled(t_[0], val2), yv), [1.0])
        temp = float(temp[0])
        yj = np.ones(int(jm2.sum()))
        before, after = probs(theta, names, de2, jm2), _scaled(temp, jm2)
        print(f"\n=== CALIBRATION, temperature fitted on {a.fit_before}..2026 (n={int(val2.sum())}) ===")
        print(f"  temperature {temp:.3f}  ({'sharpen' if temp > 1 else 'soften'} — 1.0 would mean no change needed)")
        print(f"  judged window: before ll={log_loss(before, yj):.4f} brier={brier(before, yj):.4f}  "
              f"after ll={log_loss(after, yj):.4f} brier={brier(after, yj):.4f}")
        d_cal = -np.log(after) - (-np.log(before))
        rngc = np.random.default_rng(13)
        bc = np.array([d_cal[rngc.integers(0, len(d_cal), len(d_cal))].mean() for _ in range(4000)])
        lo_c, hi_c = np.percentile(bc, [2.5, 97.5])
        print(f"  change {d_cal.mean():+.4f}, 95% CI {lo_c:+.4f}..{hi_c:+.4f} -> "
              f"{'calibration wins' if hi_c < 0 else 'unchanged is better' if lo_c > 0 else 'inside noise'}")
        for lab, q in (("before", before), ("after ", after)):
            fav = np.where(q >= 0.5, q, 1 - q); won = (q >= 0.5).astype(float)
            cells = []
            for lo, hi in ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)):
                mm = (fav >= lo) & (fav < hi)
                if mm.sum() > 15:
                    cells.append(f"{lo:.0%}: said {fav[mm].mean():.3f} got {won[mm].mean():.3f} (n={int(mm.sum())})")
            print(f"  {lab}: " + " | ".join(cells))

    # ── AN ENSEMBLE WITH AN INDEPENDENT RATING ──────────────────────────────
    # The one repeated finding in the recent literature is that two models of
    # similar strength but different construction beat either alone: the 2026
    # graph-network paper could not beat Weighted Elo (0.214 vs 0.217 Brier)
    # yet the AVERAGE of the two reached 0.211, p<0.001. Our own Elo and
    # Tennis Abstract's are exactly that pair — same idea, different code,
    # different data pipeline, different K schedule.
    #
    # DELIBERATELY UNFITTED: a flat 50/50 in logit space. We hold only a few
    # months of archived Tennis Abstract snapshots, so there is nothing to fit
    # a weight on without leaking; an unweighted average has no parameters to
    # overfit and is the honest test of whether the information is
    # complementary at all.
    if a.ensemble:
        import sqlite3
        conn = hdb.connect()
        cfg_e = {"k0": k0, "k_decay": dec, "k_offset": a.k_offset, "level_k": level_k,
                 "surface_from_overall": init, "k_floor": a.k_floor,
                 "welo": a.welo, "welo_retired": a.welo_retired}
        de = collect(rows, cfg_e, tour=a.tour, h2h_shrink=a.h2h_shrink, h2h_surface=a.h2h_surface)
        rated_e = (de["nw"] >= a.min_matches) & (de["nl"] >= a.min_matches)
        je = rated_e & (de["date"] >= a.judge_from)

        # Tennis Abstract's figures as of each tournament's first Monday, via
        # the TennisMyLife -> Tennis Explorer id bridge the linkage built.
        app_db = sqlite3.connect(str(Path(__file__).resolve().parent.parent / "tennis_fantasy.db"))
        bridge = {t: e for e, t in app_db.execute(
            "SELECT id, tml_player_id FROM te_players WHERE tml_player_id IS NOT NULL")}
        weeks = sorted({w for (w,) in app_db.execute(
            "SELECT DISTINCT week_date FROM te_rankings_snapshots WHERE elo IS NOT NULL")})
        snaps = {}
        for pid, wk, elo, eh, ec, eg, rk in app_db.execute(
                "SELECT player_id, week_date, elo, elo_hard, elo_clay, elo_grass, rank "
                "FROM te_rankings_snapshots WHERE elo IS NOT NULL"):
            snaps[(pid, wk)] = (elo, eh, ec, eg, rk)

        from app.services.winprob.elo import blend_win_prob
        ta_p, have_ta = [], []
        surf_col = {"Hard": 1, "Clay": 2, "Grass": 3}
        for i, ok in enumerate(je):
            if not ok:
                continue
            tour_, wid, lid = de["ident"][i]
            d = de["date"][i]
            wk = max((x for x in weeks if x <= d), default=None)
            tw, tl = bridge.get(wid), bridge.get(lid)
            sw_ = snaps.get((tw, wk)) if (tw and wk) else None
            sl_ = snaps.get((tl, wk)) if (tl and wk) else None
            if not sw_ or not sl_ or not sw_[0] or not sl_[0]:
                have_ta.append(False); ta_p.append(0.5); continue
            j = surf_col.get(_surface_of(rows, de, i), 1)
            selo_w, selo_l = sw_[j], sl_[j]
            bo5 = bool(de["bo5"][i])
            if selo_w and selo_l:
                p_ta = blend_win_prob(selo_w, selo_l, sw_[4], sl_[4], 5 if bo5 else 3, surface_elo=True)
            else:
                p_ta = blend_win_prob(sw_[0], sl_[0], sw_[4], sl_[4], 5 if bo5 else 3)
            have_ta.append(True); ta_p.append(p_ta)
        have_ta = np.array(have_ta); ta_p = np.array(ta_p)
        p_ours = probs(theta, names, de, je)
        both_m = have_ta
        if both_m.sum() < 50:
            print(f"\nensemble: only {int(both_m.sum())} judged matches carry a Tennis Abstract rating - too few")
        else:
            y = np.ones(int(both_m.sum()))
            o, t_ = p_ours[both_m], ta_p[both_m]
            lg = lambda q: np.log(np.clip(q, 1e-9, 1 - 1e-9) / (1 - np.clip(q, 1e-9, 1 - 1e-9)))
            ens = 1 / (1 + np.exp(-(0.5 * lg(o) + 0.5 * lg(t_))))
            print(f"\n=== ENSEMBLE with Tennis Abstract, on the {int(both_m.sum())} judged matches both rate ===")
            for label, q in (("ours alone", o), ("Tennis Abstract alone", t_), ("50/50 average", ens)):
                print(f"  {label:22} ll={log_loss(q, y):.4f}  brier={brier(q, y):.4f}  acc={np.mean(q >= 0.5):.3f}")
            d_us = -np.log(ens) - (-np.log(o))
            rng2 = np.random.default_rng(11)
            bt = np.array([d_us[rng2.integers(0, len(d_us), len(d_us))].mean() for _ in range(4000)])
            lo2, hi2 = np.percentile(bt, [2.5, 97.5])
            print(f"  ensemble vs ours: {d_us.mean():+.4f} log loss, 95% CI {lo2:+.4f}..{hi2:+.4f} -> "
                  f"{'ensemble wins' if hi2 < 0 else 'ours wins' if lo2 > 0 else 'inside noise'}")
            print(f"  correlation of the two logits: {np.corrcoef(lg(o), lg(t_))[0,1]:.3f} "
                  f"(the lower it is, the more an average can help)")

    # ── THE MARKET, ON EXACTLY THE MATCHES IT PRICED ────────────────────────
    # The subset matters more than the number: quoting our log loss over the
    # whole judged window against the market's over the half of it that has
    # odds would compare two different sets of matches and mean nothing.
    if a.market:
        from app.services.history.odds import market_probabilities
        cfg_m = {"k0": k0, "k_decay": dec, "k_offset": a.k_offset, "level_k": level_k,
                 "surface_from_overall": init, "k_floor": a.k_floor,
                 "welo": a.welo, "welo_retired": a.welo_retired}
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
           "k_floor": a.k_floor, "welo": a.welo, "welo_retired": a.welo_retired}
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
           "welo": a.welo, "welo_retired": a.welo_retired, "shrink_n0": a.shrink,
           "shrink_surface_n0": a.shrink_surface, "surface_from_overall": init,
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
