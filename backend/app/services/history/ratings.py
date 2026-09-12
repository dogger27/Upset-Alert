"""A chronological Elo over the whole record, ours and TennisMyLife's.

One pass, oldest match first, every player starting at 1500 and moving by
K·(result − expected) after each match — overall and, separately, on the
surface it was played on. K decays with a player's match count
(FiveThirtyEight's schedule: 250/(n+5)^0.4), so a newcomer's rating moves
fast and a veteran's barely, and a walkover moves nothing because no tennis
was played. That is the whole model; every constant is in
winprob/models.json "own" and was fitted by scripts/fit_own_elo.py on the
years before the ones it is judged on.

WHY RECOMPUTE FROM 1967 EVERY DAY. Half a million rows walk in three or four
seconds. An incremental update would need the pass's state kept exactly right
across restarts, republished files and our own late corrections; a full pass
needs nothing kept at all and cannot drift. So `player_ratings` is rewritten
whole, and `walk()` is the same generator the fitting script judges the
model with — what is measured is what ships.

OUR OWN RESULTS come in beside TML's (own_matches, exported by link.py) and
count first: a match we resolved from Sofascore tonight is in tomorrow's
ratings whether or not TML has published it, and when they do, their row
takes over and ours steps aside.
"""
import logging
import re
from datetime import date
from typing import Iterator, Optional

from app.services.history import db as hdb
from app.services.winprob._params import params

logger = logging.getLogger(__name__)

ROUND_ORDER = {"R128": 0, "R64": 1, "R32": 2, "R16": 3, "QF": 4, "SF": 5, "F": 6,
               "RR": 2, "BR": 5, "ER": 0, "Q1": -3, "Q2": -2, "Q3": -1}
SURFACES = ("Hard", "Clay", "Grass")
INITIAL = 1500.0


def norm_surface(s: Optional[str]) -> str:
    s = (s or "Hard").strip().lower()
    return "Clay" if s.startswith("clay") else "Grass" if s.startswith("grass") else "Hard"


_GAME_PAIR = re.compile(r"(\d{1,2})\s*-\s*(\d{1,2})")


def games_won(score: Optional[str]) -> Optional[tuple]:
    """(games won by the winner, by the loser) from a printed score.

    "6-3 6-4" -> (12, 7). Tiebreak margins in brackets are ignored: the
    scoreline is counted in GAMES, so 7-6(3) is seven games against six.
    None when the string carries no game pair at all (a walkover, an empty
    cell), or when the totals look impossible.
    """
    if not score:
        return None
    pairs = _GAME_PAIR.findall(re.sub(r"\([^)]*\)", " ", str(score)))
    if not pairs:
        return None
    w = sum(int(a) for a, _ in pairs)
    l = sum(int(b) for _, b in pairs)
    if w + l == 0 or w + l > 100:
        return None
    return (w, l)


def retired(score: Optional[str]) -> bool:
    """Did the loser stop rather than lose? The scoreline is then not a
    measure of dominance — it stops wherever the body did."""
    return "RET" in str(score or "").upper()


def _days_between(then: Optional[str], now: Optional[str]) -> Optional[int]:
    """Days from one ISO date to another; None when either is missing."""
    if not then or not now:
        return None
    try:
        return (date.fromisoformat(now) - date.fromisoformat(then)).days
    except (TypeError, ValueError):
        return None


def played(score: Optional[str]) -> bool:
    """A walkover or a default was never played: no rating moves."""
    s = (score or "").upper()
    return not ("W/O" in s or "WALKOVER" in s or s.strip() == "DEF" or "UNP" in s or "ABN" in s)


def load_rows(conn, upto: Optional[str] = None) -> list[tuple]:
    """Every match in play order: (tour, tourney_id, date, surface, level,
    round, match_num, winner_id, loser_id, score, best_of, source,
    winner_rank, loser_rank). Our own rows are dropped where TML already
    holds that pairing in that event."""
    tml = conn.execute(f"""
        SELECT tour, tourney_id, tourney_date, surface, tourney_level, round, match_num,
               winner_id, loser_id, score, best_of, 'tml', winner_rank, loser_rank FROM tml_matches
        WHERE tourney_date IS NOT NULL {"AND tourney_date <= ?" if upto else ""}""",
        ((upto,) if upto else ())).fetchall()
    have = {(r[0], r[1], frozenset((r[7], r[8]))) for r in tml if r[1]}
    own = conn.execute(f"""
        SELECT tour, tourney_id, tourney_date, surface, tourney_level, round, match_id,
               winner_id, loser_id, score, best_of, 'own', NULL, NULL FROM own_matches
        WHERE tourney_date IS NOT NULL {"AND tourney_date <= ?" if upto else ""}""",
        ((upto,) if upto else ())).fetchall()
    own = [r for r in own if (r[0], r[1], frozenset((r[7], r[8]))) not in have]
    rows = tml + own
    aliases = {(t, a): c for t, a, c in conn.execute("SELECT tour, alias_id, canonical_id FROM tml_aliases")}
    if aliases:
        rows = [(r[0], r[1], r[2], r[3], r[4], r[5], r[6],
                 aliases.get((r[0], r[7]), r[7]), aliases.get((r[0], r[8]), r[8]), r[9], r[10], r[11], r[12], r[13])
                for r in rows]
    rows.sort(key=lambda r: (r[2], r[0], r[1] or "", ROUND_ORDER.get(r[5] or "", 0), r[6] or 0))
    return rows


class Ratings:
    """The pass's state: per (tour, player) overall and per-surface Elo with counts."""

    def __init__(self, cfg: Optional[dict] = None):
        c = cfg or params("own")
        self.k0, self.decay, self.offset = float(c["k0"]), float(c["k_decay"]), float(c.get("k_offset", 5))
        self.level_k = c.get("level_k", {}) or {}
        # A PLAYER'S FIRST MATCH ON A SURFACE starts the surface rating from
        # the overall one rather than from 1500: a top-ten player's first
        # grass match is not a debutant's, and a surface rating that begins
        # at the mean drags every thin-surface prediction toward a coin toss.
        self.surface_from_overall = bool(c.get("surface_from_overall", True))
        # A FLOOR ON K: a veteran's rating must still be able to move. With
        # hundreds of Challenger matches behind a player the schedule alone
        # would leave a K of a dozen points, and a resurgence would take a
        # season to register.
        self.floor = float(c.get("k_floor", 0.0))
        # WEIGHTED ELO (Angelini, Candila & De Angelis, EJOR 2022): the
        # update is scaled by the WINNER's share of the games played, so
        # 6-0 6-0 moves both ratings at full weight and 7-6 6-7 7-6 at about
        # half. Published as beating standard Elo, Bradley-Terry and both
        # the Klaassen-Magnus logit and the Del Corral probit over 60,000
        # matches, and it is the baseline the 2026 literature measures
        # against. `welo_retired` decides whether a retirement's lopsided
        # scoreline is believed or treated as a neutral 0.5.
        self.welo = bool(c.get("welo", False))
        self.welo_retired = bool(c.get("welo_retired", False))
        self.elo: dict = {}
        self.selo: dict = {}
        self.n: dict = {}
        self.ns: dict = {}
        self.last: dict = {}

    def k(self, n: int, level: Optional[str]) -> float:
        k = self.k0 / (n + self.offset) ** self.decay * float(self.level_k.get(level or "", 1.0))
        return max(k, self.floor)

    def get(self, key) -> tuple:
        return (self.elo.get(key, INITIAL), self.selo.get(key, {}))

    def weight(self, score) -> float:
        """The WElo multiplier on K for this match; 1.0 with WElo off."""
        if not self.welo:
            return 1.0
        if retired(score) and not self.welo_retired:
            return 0.5          # the match ended for a reason the score cannot express
        g = games_won(score)
        if not g:
            return 0.5
        # A WEIGHT BELOW 0.5 IS NOT AN ERROR. You can win a match having won
        # fewer games than you lost — drop a set 0-6, take two tight ones —
        # and 7,019 matches in this record did. WElo is meant to call that
        # win weak evidence, so the scoreline is believed as it stands.
        return g[0] / (g[0] + g[1])

    def update(self, tour, w, l, surface, level, d, score=None):
        kw, kl = (tour, w), (tour, l)
        wt = self.weight(score)
        ew, el = self.elo.get(kw, INITIAL), self.elo.get(kl, INITIAL)
        pw = 1.0 / (1.0 + 10 ** ((el - ew) / 400.0))
        self.elo[kw] = ew + self.k(self.n.get(kw, 0), level) * wt * (1.0 - pw)
        self.elo[kl] = el - self.k(self.n.get(kl, 0), level) * wt * (1.0 - pw)
        sw, sl = self.selo.setdefault(kw, {}), self.selo.setdefault(kl, {})
        esw, esl = sw.get(surface, ew if self.surface_from_overall else INITIAL), \
            sl.get(surface, el if self.surface_from_overall else INITIAL)
        ps = 1.0 / (1.0 + 10 ** ((esl - esw) / 400.0))
        nsw, nsl = self.ns.setdefault(kw, {}), self.ns.setdefault(kl, {})
        sw[surface] = esw + self.k(nsw.get(surface, 0), level) * wt * (1.0 - ps)
        sl[surface] = esl - self.k(nsl.get(surface, 0), level) * wt * (1.0 - ps)
        self.n[kw] = self.n.get(kw, 0) + 1
        self.n[kl] = self.n.get(kl, 0) + 1
        nsw[surface] = nsw.get(surface, 0) + 1
        nsl[surface] = nsl.get(surface, 0) + 1
        self.last[kw] = self.last[kl] = d


def walk(rows: list[tuple], cfg: Optional[dict] = None) -> Iterator[tuple]:
    """Yield (row, pre-match state for winner, pre-match state for loser)
    for every played match, updating after each. The fitting script scores
    the yields; the nightly job only wants the state at the end."""
    st = Ratings(cfg)
    for r in rows:
        tour, w, l, surface, level, d, score = r[0], r[7], r[8], norm_surface(r[3]), r[4], r[2], r[9]
        if not played(score):
            continue
        ew, el = st.elo.get((tour, w), INITIAL), st.elo.get((tour, l), INITIAL)
        dw, dl = (ew, el) if st.surface_from_overall else (INITIAL, INITIAL)
        # DAYS SINCE THE PLAYER LAST PLAYED, which a rating cannot see: a
        # rating is frozen at whatever it was when its owner walked off court,
        # whether that was last week or after eight months out.
        pre_w = (ew, st.selo.get((tour, w), {}).get(surface, dw),
                 st.n.get((tour, w), 0), st.ns.get((tour, w), {}).get(surface, 0),
                 _days_between(st.last.get((tour, w)), d))
        pre_l = (el, st.selo.get((tour, l), {}).get(surface, dl),
                 st.n.get((tour, l), 0), st.ns.get((tour, l), {}).get(surface, 0),
                 _days_between(st.last.get((tour, l)), d))
        yield r, pre_w, pre_l
        st.update(tour, w, l, surface, level, d, score)
    walk.final = st   # the end state, for the caller that wants it


def pass_config(tour: Optional[str] = None, cfg: Optional[dict] = None) -> dict:
    """The K schedule for one tour: models.json "own" plus its overrides.

    ONE WALK PER TOUR, because k0 and k_decay are properties of the walk and
    the two tours want different ones — the men's fit settled on 250/0.4 and
    the women's on 300/0.5, which is the deeper record tolerating a steadier
    K. A single shared schedule would hand one tour someone else's number.
    """
    if cfg is not None:
        return cfg
    own = dict(params("own"))
    own.update((own.get("by_tour") or {}).get(tour or "", {}) or {})
    return own


def recompute(conn, cfg: Optional[dict] = None, as_of: Optional[str] = None) -> dict:
    """A pass per tour, and player_ratings rewritten from the end states."""
    rows = load_rows(conn)
    as_of = as_of or date.today().isoformat()
    tours = sorted({r[0] for r in rows})
    out, walked = [], 0
    for tour in tours:
        mine = [r for r in rows if r[0] == tour]
        for _ in walk(mine, pass_config(tour, cfg)):
            pass
        st: Ratings = walk.final
        walked += len(mine)
        for (t, pid), elo in st.elo.items():
            sf = st.selo.get((t, pid), {})
            ns = st.ns.get((t, pid), {})
            out.append((t, pid, as_of, elo, sf.get("Hard"), sf.get("Clay"), sf.get("Grass"),
                        st.n.get((t, pid), 0), ns.get("Hard"), ns.get("Clay"), ns.get("Grass"),
                        st.last.get((t, pid))))
    with conn:
        conn.execute("DELETE FROM player_ratings")
        conn.executemany("""INSERT INTO player_ratings
            (tour, player_id, as_of, elo, elo_hard, elo_clay, elo_grass, n_all, n_hard, n_clay, n_grass, last_match_date)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", out)
        hdb.set_meta(conn, "ratings_as_of", as_of)
        hdb.set_meta(conn, "ratings_rows", walked)
    return {"players": len(out), "matches": walked, "tours": tours, "as_of": as_of}


def ratings_for(conn, tour: str, player_ids: list[str]) -> dict:
    """{tml_player_id: {elo, elo_hard, elo_clay, elo_grass, n_all, n_<surface>, last}}
    for the players asked about — what the odds source reads."""
    if not player_ids:
        return {}
    out = {}
    q = "SELECT player_id, elo, elo_hard, elo_clay, elo_grass, n_all, n_hard, n_clay, n_grass, last_match_date " \
        "FROM player_ratings WHERE tour = ? AND player_id IN (%s)" % ",".join("?" * len(player_ids))
    for r in conn.execute(q, (tour, *player_ids)):
        out[r[0]] = {"elo": r[1], "elo_hard": r[2], "elo_clay": r[3], "elo_grass": r[4],
                     "n_all": r[5], "n_hard": r[6], "n_clay": r[7], "n_grass": r[8], "last": r[9]}
    return out


async def recompute_async(cfg: Optional[dict] = None) -> dict:
    from app.services.system_log import app_log
    out = await hdb.run(recompute, cfg)
    await app_log("info", "history", f"ratings recomputed: {out['players']} players over {out['matches']} matches", out)
    return out
