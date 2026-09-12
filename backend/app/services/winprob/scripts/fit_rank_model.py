import glob, numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, brier_score_loss

import os
RAW = os.environ.get("TENNIS_ATP_DIR", "./tennis_atp") + "/atp_matches_{}.csv"
df = pd.concat(pd.read_csv(RAW.format(y), low_memory=False) for y in range(1991, 2025))

# --- cleaning -------------------------------------------------------------
df = df[df.tourney_level.isin(["G", "M", "A", "F"])]           # no Davis Cup / others
df = df[~df.score.fillna("").str.contains(r"RET|W/O|DEF|Walkover|ABN|UNP", regex=True)]
df = df.dropna(subset=["winner_rank", "loser_rank"])
df = df[(df.winner_rank > 0) & (df.loser_rank > 0)]
df["year"] = df.tourney_date // 10000
print(f"clean matches 1991-2024: {len(df):,}")

# --- features (all antisymmetric in the pair) ------------------------------
def build(d, use_points=False):
    if use_points:
        d = d[(d.winner_rank_points > 0) & (d.loser_rank_points > 0)]
        s = np.log2(d.winner_rank_points / d.loser_rank_points)   # >0 favourite won
    else:
        s = np.log2(d.loser_rank / d.winner_rank)
    bo5 = (d.best_of == 5).astype(float).values
    clay = (d.surface == "Clay").astype(float).values
    grass = (d.surface == "Grass").astype(float).values
    s = s.values
    cols = {
        "s": s,
        "s_bo5": s * bo5,
        "s_clay": s * clay,
        "s_grass": s * grass,
        "s_sq": s * np.abs(s),          # signed square, keeps antisymmetry
    }
    return pd.DataFrame(cols, index=d.index)

def sym(F):
    X = np.vstack([F.values, -F.values])
    y = np.r_[np.ones(len(F)), np.zeros(len(F))]
    return X, y

def fit(F, cols):
    X, y = sym(F[cols])
    return LogisticRegression(fit_intercept=False, C=1e6, max_iter=1000).fit(X, y)

def evaluate(m, F, cols, label):
    X, y = sym(F[cols])
    p = m.predict_proba(X)[:, 1]
    fav_acc = (F["s"] > 0).mean()  # "pick higher-ranked" baseline, ties count as loss
    print(f"{label:38s} logloss={log_loss(y,p):.4f} brier={brier_score_loss(y,p):.4f} "
          f"acc={((p>0.5)==y).mean():.4f}  (baseline pick-favourite acc={fav_acc:.4f})")
    return p

# --- era stability: fit s-only per decade -----------------------------------
print("\nEra check (log2 rank ratio, single coef):")
for lo, hi in [(1991, 1999), (2000, 2009), (2010, 2019), (2020, 2024)]:
    d = df[(df.year >= lo) & (df.year <= hi)]
    m = fit(build(d), ["s"])
    print(f"  {lo}-{hi}: beta={m.coef_[0][0]:.4f}  n={len(d):,}")

# --- train/test split by time ------------------------------------------------
train = df[(df.year >= 2000) & (df.year <= 2019)]
test = df[df.year >= 2020]
Ftr, Fte = build(train), build(test)
Ptr, Pte = build(train, True), build(test, True)
print(f"\ntrain 2000-19: {len(train):,}   test 2020-24: {len(test):,}")

specs = {
    "rank: s":                       (Ftr, Fte, ["s"]),
    "rank: s + bo5 + surface":       (Ftr, Fte, ["s", "s_bo5", "s_clay", "s_grass"]),
    "rank: + signed square":         (Ftr, Fte, ["s", "s_bo5", "s_clay", "s_grass", "s_sq"]),
    "points: s":                     (Ptr, Pte, ["s"]),
    "points: s + bo5 + surface":     (Ptr, Pte, ["s", "s_bo5", "s_clay", "s_grass"]),
}
models = {}
print("\nHold-out performance (2020-24):")
for label, (A, B, cols) in specs.items():
    m = fit(A, cols)
    models[label] = (m, cols)
    evaluate(m, B, cols, label)

# --- calibration of the main rank model on test -------------------------------
m, cols = models["rank: s + bo5 + surface"]
X, y = sym(Fte[cols])
p = m.predict_proba(X)[:, 1]
cal = pd.DataFrame({"p": p, "y": y})
cal["bin"] = pd.cut(cal.p, np.arange(0, 1.01, 0.1))
print("\nCalibration (rank model, test set):")
print(cal.groupby("bin", observed=True).agg(pred=("p", "mean"), actual=("y", "mean"), n=("y", "size")).round(3))

# --- empirical bucket table (2000-2024) ------------------------------------------
edges = [0, 2, 4, 8, 16, 32, 64, 128, 10000]
labels = ["1-2", "3-4", "5-8", "9-16", "17-32", "33-64", "65-128", "129+"]
d = df[df.year >= 2000]
hi_rank = np.minimum(d.winner_rank, d.loser_rank)
lo_rank = np.maximum(d.winner_rank, d.loser_rank)
fav_won = (d.winner_rank < d.loser_rank).astype(float)
tab = pd.DataFrame({"fav": pd.cut(hi_rank, edges, labels=labels),
                    "dog": pd.cut(lo_rank, edges, labels=labels), "w": fav_won})
print("\nEmpirical P(better-ranked wins), rows=favourite bucket, cols=underdog bucket, 2000-24:")
print(tab.pivot_table(index="fav", columns="dog", values="w", aggfunc="mean", observed=True).round(2))
print(tab.pivot_table(index="fav", columns="dog", values="w", aggfunc="size", observed=True))

# --- final fit on all 2000-2024 ------------------------------------------------------
full = build(df[df.year >= 2000])
cols = ["s", "s_bo5", "s_clay", "s_grass"]
mf = fit(full, cols)
print("\nFINAL rank model (2000-2024), coefficients:")
for c, b in zip(cols, mf.coef_[0]):
    print(f"  {c:8s} {b:+.4f}")
b = mf.coef_[0]

def p_win(rank_x, rank_y, surface="Hard", best_of=3):
    s = np.log2(rank_y / rank_x)
    k = b[0] + b[1]*(best_of == 5) + b[2]*(surface == "Clay") + b[3]*(surface == "Grass")
    return 1 / (1 + np.exp(-k * s))

print("\nExamples:")
for rx, ry in [(1, 10), (1, 50), (1, 100), (5, 20), (10, 30), (20, 100), (50, 100), (80, 90)]:
    print(f"  #{rx} v #{ry}: hard BO3 {p_win(rx,ry):.3f}  clay BO3 {p_win(rx,ry,'Clay'):.3f} "
          f" grass BO3 {p_win(rx,ry,'Grass'):.3f}  slam hard {p_win(rx,ry,best_of=5):.3f}")

fullp = build(df[df.year >= 2000], True)
mp = fit(fullp, cols)
print("\nFINAL points model (2000-2024), coefficients (s = log2 points_x/points_y):")
for c, bb in zip(cols, mp.coef_[0]):
    print(f"  {c:8s} {bb:+.4f}")
