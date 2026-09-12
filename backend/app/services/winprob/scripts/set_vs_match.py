import re, numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, brier_score_loss

import os
RAW = os.environ.get("TENNIS_ATP_DIR", "./tennis_atp") + "/atp_matches_{}.csv"
df = pd.concat(pd.read_csv(RAW.format(y), low_memory=False) for y in range(2000, 2025))
df = df[df.tourney_level.isin(["G", "M", "A", "F"])]
df = df[~df.score.fillna("").str.contains(r"RET|W/O|DEF|Walkover|ABN|UNP", regex=True)]
df = df.dropna(subset=["winner_rank", "loser_rank"])
df = df[(df.winner_rank > 0) & (df.loser_rank > 0)]
df["year"] = df.tourney_date // 10000
df["s"] = np.log2(df.loser_rank / df.winner_rank)
df["bo5"] = (df.best_of == 5).astype(float)

# --- parse set scores: count sets won by winner / loser -------------------------
SET = re.compile(r"^(\d+)-(\d+)")
def sets_won(score):
    w = l = 0
    for tok in str(score).split():
        m = SET.match(tok)
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if a > b: w += 1
        elif b > a: l += 1
    return w, l
sw = df.score.map(sets_won)
df["w_sets"] = [x[0] for x in sw]
df["l_sets"] = [x[1] for x in sw]
ok = ((df.best_of == 3) & (df.w_sets == 2) & (df.l_sets <= 1)) | \
     ((df.best_of == 5) & (df.w_sets == 3) & (df.l_sets <= 2))
print(f"matches with parseable, consistent set scores: {ok.mean():.3%}")
df = df[ok]

train, test = df[df.year <= 2019], df[df.year >= 2020]

def fit_sym(X, y):
    X2 = np.vstack([X, -X]); y2 = np.r_[y, 1 - y]
    return LogisticRegression(fit_intercept=False, C=1e6, max_iter=1000).fit(X2, y2)

# --- direct match model (reference) --------------------------------------------
Xm = np.column_stack([train.s, train.s * train.bo5])
m_match = fit_sym(Xm, np.ones(len(train)))

# --- set-level model: one row per set, label = did winner take the set ---------
def set_rows(d, with_bo5):
    rows, labels = [], []
    for s, b5, w, l in zip(d.s, d.bo5, d.w_sets, d.l_sets):
        f = [s, s * b5] if with_bo5 else [s]
        rows += [f] * (w + l)
        labels += [1] * w + [0] * l
    return np.array(rows), np.array(labels, dtype=float)

Xs, ys = set_rows(train, False)
m_set = fit_sym(Xs, ys)
Xs5, ys5 = set_rows(train, True)
m_set5 = fit_sym(Xs5, ys5)
print(f"\nset rows in training: {len(ys):,}")
print(f"direct match model:  beta_s={m_match.coef_[0][0]:.4f} beta_bo5={m_match.coef_[0][1]:.4f}")
print(f"set model (iid):     beta_s={m_set.coef_[0][0]:.4f}")
print(f"set model + bo5:     beta_s={m_set5.coef_[0][0]:.4f} beta_bo5={m_set5.coef_[0][1]:.4f}")

def match_from_set(p, bo5):
    return np.where(bo5 == 1, p**3 * (10 - 15*p + 6*p**2), p**2 * (3 - 2*p))

def sig(z): return 1 / (1 + np.exp(-z))

def score(label, p_fav, y):
    print(f"{label:34s} logloss={log_loss(y,p_fav):.4f} brier={brier_score_loss(y,p_fav):.4f}")

# hold-out: evaluate P(winner wins) — symmetrised
s, b5 = test.s.values, test.bo5.values
y = np.r_[np.ones(len(s)), np.zeros(len(s))]
def both(p): return np.r_[p, 1 - p]

print("\nHold-out 2020-24, match-winner prediction:")
p_direct = sig(m_match.coef_[0][0]*s + m_match.coef_[0][1]*s*b5)
score("direct match model", both(p_direct), y)
p_set = sig(m_set.coef_[0][0]*s)
score("set model (iid sets) -> match", both(match_from_set(p_set, b5)), y)
p_set5 = sig(m_set5.coef_[0][0]*s + m_set5.coef_[0][1]*s*b5)
score("set model + bo5 -> match", both(match_from_set(p_set5, b5)), y)

# --- where does iid break? favourite's set-win rate by set number ------------------
print("\nDoes the favourite's per-set win rate depend on context? (2000-24, |s|>=1, i.e. rank ratio >= 2x)")
d = df[df.s.abs() >= 1].copy()
d["fav_is_winner"] = d.s > 0
def per_set(d):
    out = {}
    for score_str, fav_w in zip(d.score, d.fav_is_winner):
        for i, tok in enumerate(str(score_str).split()):
            m = SET.match(tok)
            if not m: continue
            a, b = int(m.group(1)), int(m.group(2))
            winner_took = a > b
            fav_took = winner_took == fav_w
            out.setdefault(i + 1, []).append(fav_took)
    return {k: (np.mean(v), len(v)) for k, v in out.items()}
for k, (r, n) in sorted(per_set(d).items()):
    print(f"  set {k}: favourite wins {r:.3f}  (n={n:,})")

# --- live win probability from set model (for the app) -----------------------------------
def live_prob(p, sets_x, sets_y, best_of=3):
    """P(X wins match) given per-set win prob p and current set count."""
    need_x = (best_of + 1)//2 - sets_x
    need_y = (best_of + 1)//2 - sets_y
    from math import comb
    # X wins if X takes need_x sets before Y takes need_y
    return sum(comb(need_x - 1 + k, k) * p**need_x * (1-p)**k for k in range(need_y))
print("\nLive example, #1 v #20 slam (p_set≈%.3f):" % sig(m_set5.coef_[0][0]*np.log2(20) + m_set5.coef_[0][1]*np.log2(20)))
p = sig(m_set5.coef_[0][0]*np.log2(20) + m_set5.coef_[0][1]*np.log2(20))
for sx, sy in [(0,0),(1,0),(0,1),(1,1),(2,1),(1,2),(2,2)]:
    print(f"  sets {sx}-{sy}: P(#1 wins)={live_prob(p, sx, sy, 5):.3f}")
