"""The betting market, as a yardstick for our own predictions.

No published tennis model beats the closing market price. Kovalchik (2016)
put a bookmaker consensus at 0.55 log loss against 0.59 for the best of
eleven published models; the 2026 graph-network paper put Pinnacle at 0.198
Brier against 0.214 for its model, and found the market ENCOMPASSED the
model — blending the model in added nothing. So the market is the closest
thing this sport has to a known ceiling, and a model's accuracy means very
little until it is quoted next to one.

THIS MODULE IS MEASUREMENT, NOT PREDICTION. Nothing here feeds `predict()`.
The odds are stored beside the results so `scripts/fit_own_elo.py --market`
can print what the market said about exactly the matches we are judged on.
Using them as an input would be a separate decision, and a different
product: our column would become the market's opinion rather than ours.

THE SOURCE. tennis-data.co.uk publishes one spreadsheet per season per tour,
free, updated weekly, ATP back to 2001 and WTA to 2007, carrying Bet365,
Pinnacle, the average across books and the best available price. It is the
archive every published betting study uses. Its one weakness is uptime — it
answered 503 for the whole of the night this was written — so the fetcher
falls back to the Wayback Machine's capture of the same file, which is a
different host, a different network, and the same bytes.

WHICH PRICE. The AVERAGE across bookmakers, falling back to Bet365 and then
Pinnacle. Pinnacle is the sharpest book and the one the literature prefers,
but it is missing from 96% of the 2026 rows; the average is present on
essentially all of them and is itself the "bookmaker consensus" those
studies model. The best-available price (Max) is deliberately NOT used: it
is the most generous quote rather than an estimate of the truth.
"""
import io
import logging
import re
import unicodedata
from datetime import date, timedelta
from typing import Optional

from app.services.history import db as hdb

logger = logging.getLogger(__name__)

CANONICAL = "http://www.tennis-data.co.uk/{path}"
WAYBACK = "https://web.archive.org/web/2026id_/http://www.tennis-data.co.uk/{path}"
USER_AGENT = "UpsetAlert/1.0 (+https://upsetalert.ca; tennis fantasy league; one fetch a week)"

# The columns that carry a price, best first. W is the winner's price.
PRICE_COLUMNS = [("Avg", "average across books"), ("B365", "Bet365"), ("PS", "Pinnacle")]

SCHEMA = """
CREATE TABLE IF NOT EXISTS market_odds (
    id INTEGER PRIMARY KEY,
    tour TEXT NOT NULL, season INTEGER NOT NULL, match_date TEXT NOT NULL,
    tourney TEXT, round TEXT, best_of INTEGER, surface TEXT,
    winner_name TEXT NOT NULL, loser_name TEXT NOT NULL,
    odds_w REAL, odds_l REAL, book TEXT,
    p_market REAL,              -- P(the winner wins), margin removed
    tml_winner_id TEXT, tml_loser_id TEXT,
    source TEXT, comment TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS ux_market_odds
    ON market_odds(tour, match_date, winner_name, loser_name);
CREATE INDEX IF NOT EXISTS ix_market_pair ON market_odds(tour, tml_winner_id, tml_loser_id);
CREATE INDEX IF NOT EXISTS ix_market_date ON market_odds(match_date);
"""


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


# ── names ───────────────────────────────────────────────────────────────────
# tennis-data prints "Ugo Carabelli C." — surname words, then the initial.
# TennisMyLife prints "Camilo Ugo Carabelli" — given names, then surname.
# Neither is parseable into first/last reliably (compound surnames, and
# "O Connell C." splits into three tokens), so the comparison is deliberately
# loose: ANY long token in common, and the initials must not contradict.

def _fold(s) -> str:
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()


def _tokens(s) -> list:
    return [t for t in re.split(r"[^a-z]+", _fold(s)) if t]


def market_name(name) -> tuple:
    """(surname tokens, initial) from tennis-data's form. The initial is the
    LAST single letter, not the first: "O Connell C." is C. O'Connell."""
    t = _tokens(name)
    singles = [x for x in t if len(x) == 1]
    return (frozenset(x for x in t if len(x) > 1), singles[-1] if singles else "")


def record_name(name) -> tuple:
    """(surname tokens, initial) from TennisMyLife's form."""
    t = _tokens(name)
    if not t:
        return (frozenset(), "")
    return (frozenset(t[1:]) or frozenset(t), t[0][0])


def names_match(a: tuple, b: tuple) -> bool:
    return bool(a[0] & b[0]) and (not a[1] or not b[1] or a[1] == b[1])


# ── the price ───────────────────────────────────────────────────────────────

def devig(odds_w: float, odds_l: float) -> Optional[float]:
    """P(winner wins) with the bookmaker's margin removed.

    Decimal odds are 1/probability plus a cut, so the two implied
    probabilities sum to more than one (the overround). Scaling them back to
    one is the standard, and assumes the cut is spread evenly across the two
    prices — near enough on a two-way market.
    """
    try:
        if not odds_w or not odds_l or odds_w <= 1 or odds_l <= 1:
            return None
        iw, il = 1.0 / float(odds_w), 1.0 / float(odds_l)
        return iw / (iw + il)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def pick_price(row: dict) -> tuple:
    """(odds_w, odds_l, book) — the best-supported price on this row."""
    for prefix, label in PRICE_COLUMNS:
        w, l = row.get(f"{prefix}W"), row.get(f"{prefix}L")
        if w and l:
            try:
                if float(w) > 1 and float(l) > 1:
                    return float(w), float(l), label
            except (TypeError, ValueError):
                continue
    return None, None, None


# ── fetching ────────────────────────────────────────────────────────────────

def year_paths(season: int, tour: str) -> str:
    """tennis-data's layout: /2026/2026.xlsx for men, /2026w/2026.xlsx women."""
    return f"{season}{'w' if tour == 'wta' else ''}/{season}.xlsx"


def fetch_workbook(season: int, tour: str, client=None) -> tuple:
    """(rows, source). The canonical host first, the archive if it is down."""
    import httpx
    path = year_paths(season, tour)
    owns = client is None
    client = client or httpx.Client(timeout=120, follow_redirects=True,
                                    headers={"User-Agent": USER_AGENT})
    try:
        for url, source in ((CANONICAL.format(path=path), "tennis-data.co.uk"),
                            (WAYBACK.format(path=path), "web.archive.org")):
            try:
                resp = client.get(url)
                if resp.status_code != 200 or len(resp.content) < 10_000:
                    logger.info("odds: %s gave %s (%d bytes)", source, resp.status_code, len(resp.content))
                    continue
                return parse_workbook(resp.content), source
            except Exception as exc:      # noqa: BLE001 — any transport problem falls through
                logger.info("odds: %s unreachable: %s", source, exc)
        return [], None
    finally:
        if owns:
            client.close()


def parse_workbook(content: bytes) -> list:
    """The spreadsheet's rows as dicts, one per match."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    it = ws.iter_rows(values_only=True)
    header = [str(h) if h is not None else "" for h in next(it)]
    out = []
    for raw in it:
        row = dict(zip(header, raw))
        if row.get("Winner") and row.get("Loser") and row.get("Date"):
            out.append(row)
    return out


def _iso(value) -> Optional[str]:
    s = str(value)[:10]
    try:
        date.fromisoformat(s)
        return s
    except ValueError:
        return None


def load_season(conn, season: int, tour: str, client=None) -> dict:
    """Fetch one season for one tour and store every priced match."""
    rows, source = fetch_workbook(season, tour, client)
    if not rows:
        return {"season": season, "tour": tour, "rows": 0, "source": None}
    kept = []
    for r in rows:
        d = _iso(r.get("Date"))
        if not d:
            continue
        ow, ol, book = pick_price(r)
        p = devig(ow, ol)
        if p is None:
            continue
        kept.append((tour, season, d, r.get("Tournament"), r.get("Round"),
                     int(r["Best of"]) if str(r.get("Best of") or "").isdigit() else None,
                     r.get("Surface"), str(r["Winner"]).strip(), str(r["Loser"]).strip(),
                     ow, ol, book, p, source, r.get("Comment")))
    with conn:
        conn.executemany("""INSERT OR REPLACE INTO market_odds
            (tour, season, match_date, tourney, round, best_of, surface, winner_name, loser_name,
             odds_w, odds_l, book, p_market, source, comment)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", kept)
    return {"season": season, "tour": tour, "rows": len(kept), "source": source}


def link_to_record(conn, since: str = "2000-01-01") -> dict:
    """Attach each priced match to the two TennisMyLife player ids.

    The spreadsheet's date is the DAY PLAYED; the record's is the day the
    tournament started, so the search is a window rather than an equality —
    and inside that window a pair of names is all but unique.
    """
    pool: dict = {}
    for tour, td, w, l, wid, lid in conn.execute(
            """SELECT tour, tourney_date, winner_name, loser_name, winner_id, loser_id
               FROM tml_matches WHERE tourney_date >= ? AND family IN ('main', 'quali')""", (since,)):
        try:
            t0 = date.fromisoformat(td)
        except (TypeError, ValueError):
            continue
        pool.setdefault(tour, []).append((t0, record_name(w), record_name(l), wid, lid))

    rows = conn.execute("""SELECT id, tour, match_date, winner_name, loser_name FROM market_odds
                           WHERE match_date >= ? AND tml_winner_id IS NULL""", (since,)).fetchall()
    linked, ambiguous, unmatched = [], 0, 0
    for oid, tour, d, wn, ln in rows:
        try:
            day = date.fromisoformat(d)
        except (TypeError, ValueError):
            unmatched += 1
            continue
        kw, kl = market_name(wn), market_name(ln)
        hits = set()
        for t0, pw, pl, wid, lid in pool.get(tour, ()):
            if not (t0 - timedelta(days=2) <= day <= t0 + timedelta(days=21)):
                continue
            if names_match(kw, pw) and names_match(kl, pl):
                hits.add((wid, lid))
            elif names_match(kw, pl) and names_match(kl, pw):
                hits.add((lid, wid))       # the record has them the other way up
        if len(hits) == 1:
            wid, lid = hits.pop()
            linked.append((wid, lid, oid))
        elif hits:
            ambiguous += 1
        else:
            unmatched += 1
    with conn:
        conn.executemany("UPDATE market_odds SET tml_winner_id = ?, tml_loser_id = ? WHERE id = ?", linked)
    return {"considered": len(rows), "linked": len(linked), "ambiguous": ambiguous, "unmatched": unmatched}


def sync(conn, seasons: Optional[list] = None, tours=("atp", "wta")) -> dict:
    """Fetch the seasons asked for, store them, and link them to the record."""
    import httpx
    ensure_schema(conn)
    seasons = seasons or [date.today().year]
    out = {"seasons": [], "sources": set()}
    with httpx.Client(timeout=120, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        for season in seasons:
            for tour in tours:
                got = load_season(conn, season, tour, client)
                out["seasons"].append(got)
                if got["source"]:
                    out["sources"].add(got["source"])
    out["link"] = link_to_record(conn, since=f"{min(seasons)}-01-01")
    out["sources"] = sorted(out["sources"])
    with conn:
        hdb.set_meta(conn, "market_last_sync", date.today().isoformat())
    return out


def market_probabilities(conn, since: str, tour: Optional[str] = None) -> dict:
    """{(tour, winner_id, loser_id): p_market} for judging, keyed as the
    record stores the match — so the caller looks it up by the pair it
    already has, and gets the market's probability for the ACTUAL winner."""
    q = "SELECT tour, tml_winner_id, tml_loser_id, p_market FROM market_odds " \
        "WHERE match_date >= ? AND tml_winner_id IS NOT NULL"
    args = [since]
    if tour:
        q += " AND tour = ?"
        args.append(tour)
    return {(t, w, l): p for t, w, l, p in conn.execute(q, args)}


async def sync_async(seasons: Optional[list] = None) -> dict:
    from app.services.system_log import app_log
    out = await hdb.run(sync, seasons)
    total = sum(s["rows"] for s in out["seasons"])
    await app_log("info", "history",
                  f"market odds: {total} priced matches from {', '.join(out['sources']) or 'nowhere'}; "
                  f"{out['link']['linked']} linked to the record", out)
    return out
