import numpy as np, pandas as pd
from collections import defaultdict
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss

import os
RAW = os.environ.get("TENNIS_ATP_DIR", "./tennis_atp") + "/atp_matches_{}.csv"
df = pd.concat(pd.read_csv(RAW.format(y), low_memory=False) for y in range(1991, 2025))
df = df[df.tourney_level.isin(["G", "M", "A", "F"])]
df = df[~df.score.fillna("").str.contains(r"RET|W/O|DEF|Walkover|ABN|UNP", regex=True)]
df = df.dropna(subset=["winner_rank", "loser_rank"])
df = df[(df.winner_rank > 0) & (df.loser_rank > 0)]
df["surface"] = df.surface.replace({"Carpet": "Hard"}).fillna("Hard")
df["year"] = df.tourney_date // 10000
ROUND_ORDER = {"R128":0,"R64":1,"R32":2,"R16":3,"QF":4,"SF":5,"F":6,"RR":2,"BR":5,"ER":0}
df["ro"] = df["round"].map(ROUND_ORDER).fillna(0)
df = df.sort_values(["tourney_date", "tourney_id", "ro", "match_num"]).reset_index(drop=True)

# --- sequential Elo: overall + per-surface ------------------------------------------
def kfac(n): return 250.0 / (n + 5) ** 0.4          # FiveThirtyEight-style decaying K
elo = defaultdict(lambda: 1500.0); n_all = defaultdict(int)
selo = defaultdict(lambda: 1500.0); n_surf = defaultdict(int)
pre = np.zeros((len(df), 4))                          # w_elo, l_elo, w_selo, l_selo
for i, (w, l, sf) in enumerate(zip(df.winner_id, df.loser_id, df.surface)):
    ew, el = elo[w], elo[l]; sw, sl = selo[(w, sf)], selo[(l, sf)]
    pre[i] = ew, el, sw, sl
    pw = 1 / (1 + 10 ** ((el - ew) / 400)); elo[w] += kfac(n_all[w]) * (1 - pw); elo[l] -= kfac(n_all[l]) * (1 - pw)
    ps = 1 / (1 + 10 ** ((sl - sw) / 400)); selo[(w, sf)] += kfac(n_surf[(w, sf)]) * (1 - ps); selo[(l, sf)] -= kfac(n_surf[(l, sf)]) * (1 - ps)
    n_all[w] += 1; n_all[l] += 1; n_surf[(w, sf)] += 1; n_surf[(l, sf)] += 1

df["d_elo"] = (pre[:, 0] - pre[:, 1]) / 400
df["d_selo"] = (pre[:, 2] - pre[:, 3]) / 400
df["s"] = np.log2(df.loser_rank / df.winner_rank)
df["bo5"] = (df.best_of == 5).astype(float)
df["s_bo5"] = df.s * df.bo5
df["s_grass"] = df.s * (df.surface == "Grass")
df["s_clay"] = df.s * (df.surface == "Clay")
df["d_elo_bo5"] = df.d_elo * df.bo5
df["d_selo_bo5"] = df.d_selo * df.bo5

train = df[(df.year >= 2005) & (df.year <= 2019)]     # Elo warmed up from 1991
test = df[df.year >= 2020]

def fit(cols):
    X = train[cols].values; X2 = np.vstack([X, -X]); y = np.r_[np.ones(len(X)), np.zeros(len(X))]
    return LogisticRegression(fit_intercept=False, C=1e6, max_iter=2000).fit(X2, y)

def ev(label, m, cols, d=test):
    X = d[cols].values; X2 = np.vstack([X, -X]); y = np.r_[np.ones(len(X)), np.zeros(len(X))]
    ll = log_loss(y, m.predict_proba(X2)[:, 1])
    print(f"{label:44s} logloss={ll:.4f}   " + " ".join(f"{c}={b:+.3f}" for c, b in zip(cols, m.coef_[0])))
    return ll

print(f"train {len(train):,}  test {len(test):,}\n")
specs = [
    ("rank (s, bo5, surface)",          ["s", "s_bo5", "s_clay", "s_grass"]),
    ("overall Elo",                     ["d_elo", "d_elo_bo5"]),
    ("surface Elo only",                ["d_selo", "d_selo_bo5"]),
    ("Elo + surface Elo",               ["d_elo", "d_selo", "d_elo_bo5", "d_selo_bo5"]),
    ("rank + Elo + surface Elo",        ["s", "s_bo5", "d_elo", "d_selo", "d_elo_bo5", "d_selo_bo5"]),
]
models = {}
for label, cols in specs:
    models[label] = (fit(cols), cols); ev(label, *models[label])

print("\nHold-out log loss by surface:")
for sf in ["Hard", "Clay", "Grass"]:
    d = test[test.surface == sf]
    print(f"  {sf} (n={len(d):,}):")
    for label in ["rank (s, bo5, surface)", "overall Elo", "Elo + surface Elo"]:
        ev("    " + label, *models[label], d=d)

# how much does surface Elo disagree with overall Elo? example spread
print("\nPlayers with the biggest clay-vs-hard Elo gap at end of 2024 (>=30 matches on each):")
pl = pd.read_csv(os.environ.get("TENNIS_ATP_DIR", "./tennis_atp") + "/atp_players.csv", low_memory=False)
names = dict(zip(pl.player_id, pl.name_first + " " + pl.name_last))
rows = []
for (p, sf), r in selo.items():
    if sf == "Clay" and n_surf[(p, "Clay")] >= 30 and n_surf[(p, "Hard")] >= 30 and n_all[p] >= 0:
        rows.append((names.get(p, p), round(elo[p]), round(r), round(selo[(p, "Hard")]), round(r - selo[(p, "Hard")])))
rows = pd.DataFrame(rows, columns=["player", "elo", "clay", "hard", "clay-hard"])
active = df[df.year >= 2024]; active_ids = set(active.winner_id) | set(active.loser_id)
rows = rows[rows.player.isin([names.get(i, i) for i in active_ids])]
print(rows.sort_values("clay-hard").tail(6).to_string(index=False))
print(rows.sort_values("clay-hard").head(6).to_string(index=False))
