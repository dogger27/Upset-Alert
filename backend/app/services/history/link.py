"""OUR tournaments and players, paired with TennisMyLife's ids.

THE METHOD IS THE MATCH, NOT THE NAME. Every tournament we hold a draw for is
paired with the TML tournament (exactly, from the ATP or WTA id we already
carry; by name and date only when we have no id), and inside a paired
tournament each of our finished matches is paired with theirs by round and
name. A pairing hands us both players' ids at once — and once one side of a
match is known, the other side is whoever OUR match says it was, so a
misspelling on one line cannot stop the other. Name matching against the
whole player list is the backup, flagged as such, never the first resort.

Also here: our own finished matches exported into the history database in
TML's shape, so the rating can count a result the hour it happens rather
than when TML publishes it. Everything runs off the request path.
"""
import json
import logging
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rankings import TePlayer
from app.models.tournament import Draw, DrawEntry, Match, Tournament
from app.services.history import db as hdb
from app.services.history.tml import name_key

logger = logging.getLogger(__name__)

ROUND_BY_FROM_END = {0: "F", 1: "SF", 2: "QF", 3: "R16", 4: "R32", 5: "R64", 6: "R128"}
FUZZY_MIN = 0.88          # SequenceMatcher ratio on folded full names, the backup's bar
PAIR_WINDOW_DAYS = 10     # a tournament's TML date sits within this of our start_date

# The same event under two names. TML prints the venue or the city where we
# print the sponsor's or the country's name; a word in common is the usual
# case and this list is the rest. Keys and values are folded name keys.
TOURNAMENT_ALIASES = {
    "french open": ["roland garros"],
    "rosmalen championships": ["s hertogenbosch", "hertogenbosch"],
    "libema open": ["s hertogenbosch", "hertogenbosch"],
    "canadian open": ["montreal", "toronto", "canada masters"],
    "cincinnati open": ["cincinnati masters", "cincinnati"],
    "us open": ["us open"],
    "australian open": ["australian open"],
    "wimbledon": ["wimbledon"],
    "italian open": ["rome masters", "rome"],
    "madrid open": ["madrid masters", "madrid"],
    "monte carlo masters": ["monte carlo masters", "monte carlo"],
    "miami open": ["miami masters", "miami"],
    "indian wells open": ["indian wells masters", "indian wells"],
    "bnp paribas open": ["indian wells masters", "indian wells"],
    "paris masters": ["paris masters", "paris"],
    "shanghai masters": ["shanghai masters", "shanghai"],
    "china open": ["beijing"],
    "japan open": ["tokyo"],
    "pan pacific open": ["tokyo"],
    "korea open": ["seoul"],
    "swiss indoors": ["basel"],
    "vienna open": ["vienna"],
    "european open": ["antwerp"],
    "stockholm open": ["stockholm"],
    "queens club championships": ["queen s club", "queens club", "london"],
    "cinch championships": ["queen s club", "queens club", "london"],
    "halle open": ["halle"],
    "terra wortmann open": ["halle"],
    "mexican open": ["acapulco"],
    "abierto mexicano": ["acapulco"],
    "dubai tennis championships": ["dubai"],
    "qatar open": ["doha"],
    "washington open": ["washington"],
    "mubadala citi dc open": ["washington"],
    "los cabos open": ["los cabos"],
    "winston salem open": ["winston salem"],
    "hamburg open": ["hamburg"],
    "swedish open": ["bastad"],
    "austrian open": ["kitzbuhel"],
    "croatia open": ["umag"],
    "hong kong open": ["hong kong"],
    "brisbane international": ["brisbane"],
    "adelaide international": ["adelaide"],
    "auckland open": ["auckland"],
    "united cup": ["united cup"],
    "argentina open": ["buenos aires"],
    "rio open": ["rio de janeiro"],
    "chile open": ["santiago"],
    "dallas open": ["dallas"],
    "delray beach open": ["delray beach"],
    "open 13": ["marseille"],
    "rotterdam open": ["rotterdam"],
    "abn amro open": ["rotterdam"],
    "bmw open": ["munich"],
    "barcelona open": ["barcelona"],
    "geneva open": ["geneva"],
    "lyon open": ["lyon"],
    "hungarian open": ["budapest"],
    "mallorca championships": ["mallorca"],
    "eastbourne open": ["eastbourne"],
    "atlanta open": ["atlanta"],
    "chengdu open": ["chengdu"],
    "hangzhou open": ["hangzhou"],
    "almaty open": ["almaty"],
    "belgrade open": ["belgrade"],
    "moselle open": ["metz"],
    "sofia open": ["sofia"],
    "gijon open": ["gijon"],
    "tel aviv open": ["tel aviv"],
    "san diego open": ["san diego"],
    "napoli cup": ["naples"],
    "nordic open": ["stockholm"],
}


# name_key sorts a name's tokens, so the table is looked up by the sorted form.
_ALIASES_BY_KEY = {name_key(k): v for k, v in TOURNAMENT_ALIASES.items()}


# Our category words -> TML's tourney_level codes.
_LEVEL = {"grand slam": "G", "atp 1000": "M", "atp 500": "500", "atp 250": "250",
          "wta 1000": "1000", "wta 500": "500", "wta 250": "250"}


def level_code(category: Optional[str]) -> Optional[str]:
    return _LEVEL.get((category or "").strip().lower())


def names_agree(entry_name: str, te_name: str) -> bool:
    """Is this the same person's name in two forms? "Sorana Cîrstea" and
    "Sorana-Mihaela Cirstea" are; "Luciano Darderi" and "Alexander Bublik"
    are not. One set of tokens inside the other, or two tokens shared
    including the last (the surname), or simply near-identical."""
    a_, b_ = set(name_key(entry_name).split()), set(name_key(te_name).split())
    if not a_ or not b_:
        return False
    if a_ <= b_ or b_ <= a_:
        return True
    la, lb = name_key(entry_name).split()[-1], name_key(te_name).split()[-1]
    if len(a_ & b_) >= 2 and (la in b_ or lb in a_):
        return True
    return SequenceMatcher(None, " ".join(sorted(a_)), " ".join(sorted(b_))).ratio() >= 0.8


def norm_surface(s: Optional[str]) -> str:
    s = (s or "Hard").strip().lower()
    return "Clay" if s.startswith("clay") else "Grass" if s.startswith("grass") else "Hard"


def round_code(round_number: int, num_rounds: int) -> Optional[str]:
    return ROUND_BY_FROM_END.get(num_rounds - round_number)


def score_text(scores_json, winner_is_p1: bool) -> Optional[str]:
    """Our per-set grid as TML prints it: "6-3 3-0 RET", "W/O". Winner first."""
    if not scores_json:
        return None
    try:
        grid = json.loads(scores_json) if isinstance(scores_json, str) else scores_json
        a, b = grid[0], grid[1]
    except (ValueError, TypeError, IndexError):
        return None
    cells = list(zip(a, b)) if winner_is_p1 else list(zip(b, a))
    if any(str(x).lower() == "w/o" or str(y).lower() == "w/o" for x, y in cells):
        return "W/O"
    parts, retired = [], False
    for x, y in cells:
        x, y = str(x or ""), str(y or "")
        if x.endswith("r") or y.endswith("r"):
            retired = True
        x, y = x.rstrip("r"), y.rstrip("r")
        if x == "" and y == "":
            continue
        parts.append(f"{x}-{y}")
    return (" ".join(parts) + (" RET" if retired else "")).strip() or None


def _tml_tournaments(conn, tour: str, year: int) -> list[dict]:
    """Every TML tournament of that tour and season, with its printed shape."""
    rows = conn.execute("""
        SELECT tourney_id, min(tourney_name), min(tourney_date), min(tourney_level), max(draw_size), min(surface), count(*)
        FROM tml_matches WHERE tour = ? AND substr(tourney_date, 1, 4) = ? AND family != 'challenger'
        GROUP BY tourney_id""", (tour, str(year))).fetchall()
    return [dict(id=r[0], name=r[1], date=r[2], level=r[3], draw_size=r[4], surface=r[5], n=r[6]) for r in rows]


def _tml_matches_of(conn, tour: str, tourney_id: str) -> list[dict]:
    rows = conn.execute("""
        SELECT round, winner_id, winner_name, loser_id, loser_name, score, match_num
        FROM tml_matches WHERE tour = ? AND tourney_id = ?""", (tour, tourney_id)).fetchall()
    return [dict(round=r[0], w_id=r[1], w_name=r[2], w_key=name_key(r[2]), l_id=r[3], l_name=r[4],
                 l_key=name_key(r[4]), score=r[5], match_num=r[6]) for r in rows]


def _tml_players(conn, tour: str) -> list[tuple]:
    return conn.execute("SELECT player_id, name, name_key, last_date FROM tml_players WHERE tour = ?", (tour,)).fetchall()


def _name_words(s: str) -> set:
    return set(name_key(s).split())


def pair_tournament(draw: Draw, tournament: Tournament, candidates: list[dict], tour: str) -> tuple[Optional[str], str]:
    """(tml_tourney_id, method). Exact from our own id when we carry one and
    TML lists it; else the best-named tournament within the date window at
    a compatible level — the backup, and it says so."""
    own_id = tournament.atp_tournament_id if tour == "atp" else tournament.wta_live_scoring_id
    by_id = {c["id"]: c for c in candidates}
    if own_id:
        key = f"{draw.year}-{own_id}"
        if key in by_id:
            return key, "id"
    if not draw.start_date:
        return None, "none"
    want_level = level_code(draw.category or tournament.category)
    our_key = name_key(tournament.name or draw.name or "")
    aliases = {name_key(x) for x in _ALIASES_BY_KEY.get(our_key, [])}
    ours = _name_words(tournament.name or draw.name or "") | _name_words(draw.city or tournament.city or "")
    ours -= {"open", "championships", "international", "masters", "cup", "classic", "atp", "wta", "tennis"}
    best, best_score = None, 0.0
    for c in candidates:
        try:
            d = date.fromisoformat(c["date"])
        except (TypeError, ValueError):
            continue
        if abs((d - draw.start_date).days) > PAIR_WINDOW_DAYS:
            continue
        their_key = name_key(c["name"] or "")
        theirs = _name_words(c["name"] or "") - {"open", "masters", "championships"}
        if not theirs:
            continue
        if their_key in aliases or (c.get("id") and any(their_key == a for a in aliases)):
            score = 1.0
        else:
            overlap = len(ours & theirs) / max(1, len(theirs))
            ratio = SequenceMatcher(None, our_key, their_key).ratio()
            score = max(overlap, ratio)
        # The level and the draw size are tiebreaks, not gates: our category
        # and their level code disagree for a few events every season.
        if want_level and c["level"] and want_level == c["level"]:
            score += 0.05
        if getattr(draw, "draw_size", None) and c["draw_size"] and abs(int(draw.draw_size) - int(c["draw_size"])) <= 8:
            score += 0.05
        if score > best_score:
            best, best_score = c, score
    if best and best_score >= 0.55:
        return best["id"], "name"
    return None, "none"


async def repair_te_links(db: AsyncSession) -> dict:
    """Entries whose name is not their Tennis Explorer player's name — the
    broken links the linkage refuses to use — re-pointed at the one player
    whose name is exactly theirs, where such a player exists. Anything else
    is left as it is and reported; a guess would be the fault over again."""
    te_rows = (await db.execute(select(TePlayer))).scalars().all()
    te_by_id = {p.id: p for p in te_rows}
    by_key: dict = {}
    for p in te_rows:
        by_key.setdefault((p.gender, name_key(p.name_display or p.name_raw or "")), []).append(p)
    fixed, left = [], []
    rows = (await db.execute(select(DrawEntry, Draw.gender).join(Draw, Draw.id == DrawEntry.draw_id)
                             .where(DrawEntry.te_player_id.isnot(None)))).all()
    for e, gender in rows:
        te = te_by_id.get(e.te_player_id)
        if te is None or names_agree(e.name, te.name_display or te.name_raw or ""):
            continue
        cands = by_key.get((gender, name_key(e.name)), [])
        if len(cands) == 1:
            fixed.append({"draw_entry_id": e.id, "entry": e.name, "was": te.name_display or te.name_raw,
                          "now": cands[0].name_display or cands[0].name_raw})
            e.te_player_id = cands[0].id
            e.te_slug = cands[0].te_slug
        else:
            left.append({"draw_entry_id": e.id, "draw_id": e.draw_id, "entry": e.name, "te_name": te.name_display or te.name_raw})
    if fixed:
        await db.commit()
    return {"fixed": fixed, "left": left}


async def link_draws(db: AsyncSession, draw_ids: Optional[list[int]] = None) -> dict:
    """Pair tournaments, then players, then export our results. One report.

    Players are linked in three phases over EVERY draw, strictest first, so
    the exact evidence from one tournament settles a person before a weaker
    reading of another can:

      1. exact — a match of ours whose BOTH sides are identified in the paired
         TML row (by an id already known, or by the folded name key);
      2. inferred — a match with one side identified, where the other side
         is taken to be whoever our match says, guarded: only for a player
         still unlinked, whose TML name is not the name of anyone else in
         our field, and which resembles ours;
      3. the backup — the whole player list, exact key first, then fuzzy.

    A person met under two TML ids (the same folded name, the second id a
    stub of a few matches) records the stub as an alias of the established
    id rather than a conflict; that is knowledge only our draw has.
    """
    report = dict(draws=0, paired_id=0, paired_name=0, unpaired=[], linked_match=0, linked_inferred=0,
                  linked_name=0, linked_fuzzy=0, unlinked=[], conflicts=[], aliases=0, bad_te_links=[],
                  result_disagreements=0, exported=0)

    q = select(Draw, Tournament).join(Tournament, Tournament.id == Draw.tournament_id)
    if draw_ids:
        q = q.where(Draw.id.in_(draw_ids))
    pairs = (await db.execute(q)).all()

    conn = hdb.connect()
    try:
        tml_by_year: dict = {}

        def _cands(tour, year):
            if (tour, year) not in tml_by_year:
                tml_by_year[(tour, year)] = _tml_tournaments(conn, tour, year)
            return tml_by_year[(tour, year)]

        players_by_tour = {t: _tml_players(conn, t) for t in ("atp", "wta")}
        player_info = {(t, p[0]): p for t in players_by_tour for p in players_by_tour[t]}
        te_rows = (await db.execute(select(TePlayer))).scalars().all()
        te_by_id = {p.id: p for p in te_rows}
        taken: dict = {}
        for p in te_rows:
            if p.tml_player_id:
                taken[(("wta" if p.gender == "F" else "atp"), p.tml_player_id)] = p.id

        def _assign(te: TePlayer, tour: str, tml_id: str, method: str, our_name: str = "") -> bool:
            if te.tml_player_id == tml_id:
                return False
            if te.tml_player_id and te.tml_player_id != tml_id:
                have, saw = player_info.get((tour, te.tml_player_id)), player_info.get((tour, tml_id))
                # The same name under a stub id: TML's duplicate, merged here —
                # whichever of the two ids is the stub becomes the alias of the
                # other, so it does not matter which tournament was read first.
                if have and saw and have[2] == saw[2]:
                    def _n(pid):
                        r = conn.execute("SELECT n_matches FROM tml_players WHERE tour=? AND player_id=?", (tour, pid)).fetchone()
                        return r[0] if r else 0
                    n_have, n_saw = _n(te.tml_player_id), _n(tml_id)
                    if n_saw <= 10 < n_have or n_have <= 10 < n_saw:
                        stub, real = (tml_id, te.tml_player_id) if n_saw <= 10 else (te.tml_player_id, tml_id)
                        with conn:
                            conn.execute("INSERT OR IGNORE INTO tml_aliases (tour, alias_id, canonical_id, reason) VALUES (?,?,?,?)",
                                         (tour, stub, real, f"same name via our draw ({method})"))
                        report["aliases"] += 1
                        if te.tml_player_id == stub:
                            taken.pop((tour, stub), None)
                            te.tml_player_id, te.tml_link = real, method
                            taken[(tour, real)] = te.id
                        return False
                report["conflicts"].append({"te_player_id": te.id, "name": te.name_display or te.name_raw,
                                            "have": te.tml_player_id, "saw": tml_id, "via": method, "entry": our_name})
                return False
            holder = taken.get((tour, tml_id))
            if holder and holder != te.id:
                report["conflicts"].append({"te_player_id": te.id, "name": te.name_display or te.name_raw,
                                            "tml_id": tml_id, "already": holder, "via": method})
                return False
            te.tml_player_id, te.tml_link = tml_id, method
            taken[(tour, tml_id)] = te.id
            report[f"linked_{method}"] += 1
            return True

        # ── tournaments, and everything each draw needs, loaded once ──────────
        work = []
        for draw, tournament in pairs:
            tour = "wta" if draw.gender == "F" else "atp"
            report["draws"] += 1
            tml_id, how = pair_tournament(draw, tournament, _cands(tour, draw.year), tour)
            if tml_id:
                if draw.tml_tourney_id != tml_id:
                    draw.tml_tourney_id = tml_id
                report["paired_id" if how == "id" else "paired_name"] += 1
            else:
                report["unpaired"].append({"draw_id": draw.id, "name": f"{tournament.name} {draw.year} {draw.gender}"})
            entries = (await db.execute(select(DrawEntry).where(DrawEntry.draw_id == draw.id))).scalars().all()
            matches = (await db.execute(select(Match).where(Match.draw_id == draw.id, Match.winner_id.isnot(None),
                                                            Match.is_bye == False))).scalars().all()  # noqa: E712
            theirs = _tml_matches_of(conn, tour, tml_id) if tml_id else []
            by_round: dict = {}
            for t in theirs:
                by_round.setdefault(t["round"], []).append(t)
            work.append((draw, tournament, tour, entries, matches, by_round))

        # AN ENTRY WHOSE NAME IS NOT ITS PLAYER'S NAME is a broken Tennis
        # Explorer link in our own data (Mallorca 2026 had Darderi on Bublik's
        # row, Cassone on Tiafoe's), and would hand one person's id to another.
        # Such entries take no part in the linkage and are reported for repair.
        def _trusted(e) -> bool:
            te = te_by_id.get(e.te_player_id)
            if te is None:
                return False
            if names_agree(e.name, te.name_display or te.name_raw or ""):
                return True
            rec = {"draw_entry_id": e.id, "entry": e.name, "te_player_id": te.id,
                   "te_name": te.name_display or te.name_raw}
            if rec not in report["bad_te_links"]:
                report["bad_te_links"].append(rec)
            return False

        def _sides(m, e1, e2, key_of, t):
            """Which side of their row each of our two players is, by id or name."""
            side = {}
            for e in (e1, e2):
                te = te_by_id.get(e.te_player_id)
                tid = te.tml_player_id if te else None
                if tid and tid in (t["w_id"], t["l_id"]):
                    side[e] = "w" if tid == t["w_id"] else "l"
                elif key_of[e.id] and key_of[e.id] in (t["w_key"], t["l_key"]):
                    side[e] = "w" if key_of[e.id] == t["w_key"] else "l"
            return side

        # ── phase 1: exact, both sides ─────────────────────────────────────────
        for draw, tournament, tour, entries, matches, by_round in work:
            entry_by_id = {e.id: e for e in entries}
            key_of = {e.id: name_key(e.name) for e in entries}
            for m in matches:
                rc = round_code(m.round_number, draw.num_rounds or 7)
                e1, e2 = entry_by_id.get(m.player1_id), entry_by_id.get(m.player2_id)
                if not (rc and e1 and e2 and _trusted(e1) and _trusted(e2)):
                    continue
                hits = []
                for t in by_round.get(rc, []):
                    side = _sides(m, e1, e2, key_of, t)
                    if len(side) == 2 and side[e1] != side[e2]:
                        hits.append((t, side))
                if len(hits) != 1:
                    continue
                t, side = hits[0]
                for e in (e1, e2):
                    te = te_by_id.get(e.te_player_id)
                    if te is not None:
                        _assign(te, tour, t["w_id"] if side[e] == "w" else t["l_id"], "match", e.name)
                our_winner = e1 if m.winner_id == e1.id else e2
                if side.get(our_winner) != "w":
                    report["result_disagreements"] += 1

        # ── phase 2: inferred, one side known, the other still unlinked ──────
        for draw, tournament, tour, entries, matches, by_round in work:
            entry_by_id = {e.id: e for e in entries}
            key_of = {e.id: name_key(e.name) for e in entries}
            field_keys = set(key_of.values())
            for m in matches:
                rc = round_code(m.round_number, draw.num_rounds or 7)
                e1, e2 = entry_by_id.get(m.player1_id), entry_by_id.get(m.player2_id)
                if not (rc and e1 and e2 and _trusted(e1) and _trusted(e2)):
                    continue
                hits = []
                for t in by_round.get(rc, []):
                    side = _sides(m, e1, e2, key_of, t)
                    if len(side) == 1:
                        hits.append((t, side))
                if len(hits) != 1:
                    continue
                t, side = hits[0]
                known = e1 if e1 in side else e2
                other = e2 if known is e1 else e1
                te = te_by_id.get(other.te_player_id)
                if te is None or te.tml_player_id:
                    continue
                their_id = t["l_id"] if side[known] == "w" else t["w_id"]
                their_key = t["l_key"] if side[known] == "w" else t["w_key"]
                # Not somebody else in our field, and recognisably the same name.
                if their_key in field_keys - {key_of[other.id]}:
                    continue
                if SequenceMatcher(None, key_of[other.id], their_key).ratio() < 0.8:
                    continue
                _assign(te, tour, their_id, "inferred", other.name)

        # ── phase 3: the backup — the whole list, exact key then fuzzy ──────
        for draw, tournament, tour, entries, matches, by_round in work:
            for e in entries:
                te = te_by_id.get(e.te_player_id)
                if te is None or te.tml_player_id or not _trusted(e):
                    continue
                k = name_key(e.name)
                exact = [p for p in players_by_tour[tour] if p[2] == k]
                if len(exact) == 1:
                    _assign(te, tour, exact[0][0], "name", e.name)
                    continue
                if len(exact) > 1:
                    exact.sort(key=lambda p: p[3] or "", reverse=True)
                    _assign(te, tour, exact[0][0], "fuzzy", e.name)
                    continue
                surname = k.split()[-1] if k else ""
                best, best_r = None, 0.0
                for pid, pname, pkey, last in players_by_tour[tour]:
                    if surname and surname not in pkey.split():
                        continue
                    r = SequenceMatcher(None, k, pkey).ratio()
                    if r > best_r:
                        best, best_r = pid, r
                if best and best_r >= FUZZY_MIN:
                    _assign(te, tour, best, "fuzzy", e.name)
                elif not any(u["te_player_id"] == te.id for u in report["unlinked"]):
                    report["unlinked"].append({"te_player_id": te.id, "name": e.name, "draw_id": draw.id})

        # ── our results, in their shape ──────────────────────────────────────
        for draw, tournament, tour, entries, matches, by_round in work:
            entry_by_id = {e.id: e for e in entries}
            rows = []
            for m in matches:
                e1, e2 = entry_by_id.get(m.player1_id), entry_by_id.get(m.player2_id)
                if not (e1 and e2):
                    continue
                w, l = (e1, e2) if m.winner_id == e1.id else (e2, e1)
                if not (_trusted(w) and _trusted(l)):
                    continue
                tw, tl = te_by_id.get(w.te_player_id), te_by_id.get(l.te_player_id)
                if not (tw and tl and tw.tml_player_id and tl.tml_player_id):
                    continue
                rows.append((
                    m.id, draw.id, tour, draw.tml_tourney_id, tournament.name, norm_surface(draw.surface),
                    draw.draw_size, level_code(draw.category or tournament.category),
                    draw.start_date.isoformat() if draw.start_date else None,
                    tw.tml_player_id, w.name, tl.tml_player_id, l.name,
                    score_text(m.scores_json, m.winner_id == e1.id),
                    5 if (draw.gender == "M" and (draw.category or "").lower().startswith("grand")) else (draw.sofa_number_of_sets or 3),
                    round_code(m.round_number, draw.num_rounds or 7), m.duration_min,
                    m.completed_at.isoformat() if m.completed_at else None,
                ))
            if rows:
                with conn:
                    conn.executemany("""INSERT OR REPLACE INTO own_matches
                        (match_id, draw_id, tour, tourney_id, tourney_name, surface, draw_size, tourney_level, tourney_date,
                         winner_id, winner_name, loser_id, loser_name, score, best_of, round, minutes, completed_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
                report["exported"] += len(rows)
        await db.commit()
        with conn:
            hdb.set_meta(conn, "last_link", datetime.now(timezone.utc).isoformat())
    finally:
        conn.close()
    return report


async def link_all_async(draw_ids: Optional[list[int]] = None) -> dict:
    """The linkage on its own session, with the outcome in the system log."""
    from app.database import AsyncSessionLocal
    from app.services.system_log import app_log
    async with AsyncSessionLocal() as db:
        repair = await repair_te_links(db)
        if repair["fixed"] or repair["left"]:
            await app_log("warning" if repair["left"] else "info", "history",
                          f"Tennis Explorer links: {len(repair['fixed'])} entries re-pointed at the player their name "
                          f"names, {len(repair['left'])} left on the wrong player", repair)
        report = await link_draws(db, draw_ids)
    summary = (f"TML linkage: {report['draws']} draws ({report['paired_id']} by id, {report['paired_name']} by name, "
               f"{len(report['unpaired'])} unpaired); players +{report['linked_match']} by match, "
               f"+{report['linked_inferred']} inferred, +{report['linked_name']} by name, +{report['linked_fuzzy']} fuzzy, "
               f"{len(report['unlinked'])} unlinked; {report['aliases']} stub ids merged; "
               f"{len(report['conflicts'])} conflicts; {len(report['bad_te_links'])} broken TE links; "
               f"{report['result_disagreements']} result disagreements; "
               f"{report['exported']} results exported")
    await app_log("warning" if report["conflicts"] or report["unpaired"] else "info", "history", summary,
                  {k: v for k, v in report.items() if k in ("unpaired", "unlinked", "conflicts", "bad_te_links")})
    return report
