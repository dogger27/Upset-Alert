"""The TennisMyLife sync: every results file they publish, mirrored by mtime.

TennisMyLife (stats.tennismylife.org) is Jeff Sackmann's `tennis_atp` schema
continued and kept live — updated daily, MIT licensed, one CSV per tour per
year plus Challengers, ATP qualifying, and an "ongoing" file for the events
in play this week. Sackmann's own repository has no file for the current
season at all, so this is the record we build our ratings on.

A FILE IS THE UNIT. They republish a whole year's CSV when a result changes,
so the loader replaces a file's rows wholesale when its mtime moves, and
never merges row by row. The ledger (`tml_files`) is what makes the daily
run cheap: 172 files are listed, the current season's four are the only ones
that move, and nothing is downloaded twice.

THE ONGOING FILE IS A PREVIEW. Its rows reappear in the year file once the
event is over, under the same (tour, tourney_id, match_num) key. The year
file always wins: loading one evicts the preview rows it supersedes, and a
preview never overwrites a settled row.
"""
import csv
import io
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional

from app.services.history import db as hdb

logger = logging.getLogger(__name__)

BASE = "https://stats.tennismylife.org"
LIST_URL = BASE + "/api/data-files"
USER_AGENT = "UpsetAlert/1.0 (+https://upsetalert.ca; tennis fantasy league; one sync a day)"

_YEAR = re.compile(r"^(\d{4})\.csv$")
_WTA = re.compile(r"^(\d{4})_wta\.csv$")
_CHAL = re.compile(r"^(\d{4})_challenger\.csv$")
_QUALI = re.compile(r"^atp_quali/(\d{4})_atp_quali\.csv$")
_ONGOING = {
    "ongoing_tourneys.csv": ("atp", "ongoing"),
    "wta_ongoing_tourneys.csv": ("wta", "ongoing"),
    "challenger_ongoing_tourneys.csv": ("atp", "ongoing"),
}


def classify(name: str) -> Optional[tuple]:
    """(tour, family) for a file we want; None for the rest (backups, the
    all-in-one dump, the amateur era, ranking lists)."""
    if name in _ONGOING:
        return _ONGOING[name]
    if _YEAR.match(name):
        return ("atp", "main")
    if _WTA.match(name):
        return ("wta", "main")
    if _CHAL.match(name):
        return ("atp", "challenger")
    if _QUALI.match(name):
        return ("atp", "quali")
    return None


def name_key(name: str) -> str:
    """Accents folded, lower-cased, tokens sorted — so "Cerúndolo Juan Manuel"
    (Tennis Explorer) and "Juan Manuel Cerundolo" (TML) are the same key.
    The order-free form is what the Elo scraper already matches on."""
    folded = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    tokens = re.sub(r"[^a-z0-9 ]+", " ", folded.lower()).split()
    return " ".join(sorted(tokens))


def _int(v) -> Optional[int]:
    try:
        return int(float(v)) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _float(v) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _date(v) -> Optional[str]:
    s = str(v or "").strip()
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else None


COLUMNS = (
    "tour family source_file tourney_id tourney_name surface draw_size tourney_level indoor "
    "tourney_date match_num winner_id winner_seed winner_entry winner_name winner_hand winner_ht "
    "winner_ioc winner_age winner_rank winner_rank_points loser_id loser_seed loser_entry loser_name "
    "loser_hand loser_ht loser_ioc loser_age loser_rank loser_rank_points score best_of round minutes "
    + " ".join(f"w_{c}" for c in hdb.STAT_COLS) + " " + " ".join(f"l_{c}" for c in hdb.STAT_COLS)
).split()


def parse_rows(text: str, tour: str, family: str, source_file: str) -> list[tuple]:
    """CSV text -> rows in COLUMNS order. A row without both player ids or a
    tournament id is not a match we can use and is dropped."""
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        tid, w, l = (r.get("tourney_id") or "").strip(), (r.get("winner_id") or "").strip(), (r.get("loser_id") or "").strip()
        if not (tid and w and l):
            continue
        row = (
            tour, family, source_file, tid, r.get("tourney_name"), r.get("surface"), _int(r.get("draw_size")),
            r.get("tourney_level"), r.get("indoor"), _date(r.get("tourney_date")), _int(r.get("match_num")),
            w, r.get("winner_seed"), r.get("winner_entry"), r.get("winner_name"), r.get("winner_hand"),
            _int(r.get("winner_ht")), r.get("winner_ioc"), _float(r.get("winner_age")), _int(r.get("winner_rank")),
            _int(r.get("winner_rank_points")),
            l, r.get("loser_seed"), r.get("loser_entry"), r.get("loser_name"), r.get("loser_hand"),
            _int(r.get("loser_ht")), r.get("loser_ioc"), _float(r.get("loser_age")), _int(r.get("loser_rank")),
            _int(r.get("loser_rank_points")),
            r.get("score"), _int(r.get("best_of")), r.get("round"), _int(r.get("minutes")),
        ) + tuple(_int(r.get(f"w_{c}")) for c in hdb.STAT_COLS) + tuple(_int(r.get(f"l_{c}")) for c in hdb.STAT_COLS)
        out.append(row)
    return out


def _load_file(conn, name: str, tour: str, family: str, rows: list[tuple]) -> int:
    """Replace this file's rows. Year files evict the preview rows they
    supersede; a preview skips keys a settled file already holds."""
    keys = [(tour, r[3], r[10]) for r in rows]
    if family in ("challenger", "quali"):
        # Neither previews nor is previewed; nothing to supersede either way.
        with conn:
            conn.execute("DELETE FROM tml_matches WHERE source_file = ?", (name,))
            placeholders = ",".join("?" * len(COLUMNS))
            conn.executemany(f"INSERT OR REPLACE INTO tml_matches ({','.join(COLUMNS)}) VALUES ({placeholders})", rows)
        return len(rows)
    with conn:
        conn.execute("DELETE FROM tml_matches WHERE source_file = ?", (name,))
        if family == "ongoing":
            settled = set()
            for tour_, tid, mn in keys:
                if conn.execute("SELECT 1 FROM tml_matches WHERE tour=? AND tourney_id=? AND match_num=? "
                                "AND family = 'main'", (tour_, tid, mn)).fetchone():
                    settled.add((tour_, tid, mn))
            rows = [r for r in rows if (tour, r[3], r[10]) not in settled]
        else:
            conn.executemany("DELETE FROM tml_matches WHERE tour=? AND tourney_id=? AND match_num=? "
                             "AND family = 'ongoing'", keys)
        placeholders = ",".join("?" * len(COLUMNS))
        conn.executemany(
            f"INSERT OR REPLACE INTO tml_matches ({','.join(COLUMNS)}) VALUES ({placeholders})", rows)
    return len(rows)


def rebuild_players(conn) -> int:
    """tml_players from tml_matches: one row per (tour, id), latest name."""
    with conn:
        conn.execute("DELETE FROM tml_players")
        conn.execute("""
            INSERT INTO tml_players (tour, player_id, name, name_key, hand, ioc, first_date, last_date, n_matches)
            SELECT tour, player_id, name, '', hand, ioc, min(d), max(d), count(*) FROM (
                SELECT tour, winner_id AS player_id, winner_name AS name, winner_hand AS hand, winner_ioc AS ioc,
                       tourney_date AS d FROM tml_matches
                UNION ALL
                SELECT tour, loser_id, loser_name, loser_hand, loser_ioc, tourney_date FROM tml_matches)
            GROUP BY tour, player_id""")
        rows = conn.execute("SELECT tour, player_id, name FROM tml_players").fetchall()
        conn.executemany("UPDATE tml_players SET name_key = ? WHERE tour = ? AND player_id = ?",
                         [(name_key(n), t, p) for t, p, n in rows])
        # The latest-printed name, not an arbitrary one: names change (marriage, transliteration).
        conn.execute("""
            UPDATE tml_players SET name = (
                SELECT name FROM (
                    SELECT tour, winner_id AS pid, winner_name AS name, tourney_date AS d FROM tml_matches
                    UNION ALL SELECT tour, loser_id, loser_name, tourney_date FROM tml_matches) x
                WHERE x.tour = tml_players.tour AND x.pid = tml_players.player_id
                ORDER BY d DESC LIMIT 1)""")
        conn.executemany("UPDATE tml_players SET name_key = ? WHERE tour = ? AND player_id = ?",
                         [(name_key(n), t, p) for t, p, n in conn.execute("SELECT tour, player_id, name FROM tml_players")])
    return len(rows)


def sync(conn, force: bool = False, only_current: bool = False) -> dict:
    """Bring tml_matches up to date with what TennisMyLife lists. Returns a
    summary. `only_current` restricts to files that can still change (this
    season's and the previews) — what the daily run wants; the full listing
    is checked otherwise, which is the first run and any repair."""
    import httpx

    with httpx.Client(timeout=180, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        listing = client.get(LIST_URL).json()
        files = listing.get("files", listing) if isinstance(listing, dict) else listing
        wanted = []
        year = str(datetime.now(timezone.utc).year)
        for f in files:
            kind = classify(f["name"])
            if not kind:
                continue
            if only_current and not (f["name"] in _ONGOING or f["name"].startswith(year) or f"/{year}_" in f["name"]):
                continue
            wanted.append((f, kind))
        ledger = {n: (m, s) for n, m, s in conn.execute("SELECT name, mtime, size FROM tml_files")}
        loaded = rows_total = 0
        for f, (tour, family) in wanted:
            name, mtime, size = f["name"], str(f.get("mtime")), int(f.get("size") or 0)
            if not force and ledger.get(name) == (mtime, size):
                continue
            text = client.get(f["url"]).text
            rows = parse_rows(text, tour, family, name)
            n = _load_file(conn, name, tour, family, rows)
            with conn:
                conn.execute("INSERT OR REPLACE INTO tml_files (name, mtime, size, loaded_at, rows) VALUES (?,?,?,?,?)",
                             (name, mtime, size, datetime.now(timezone.utc).isoformat(), n))
            loaded += 1
            rows_total += n
            logger.info("tml: loaded %s (%s/%s) %d rows", name, tour, family, n)
    players = rebuild_players(conn) if loaded else None
    with conn:
        hdb.set_meta(conn, "tml_last_sync", datetime.now(timezone.utc).isoformat())
    total = conn.execute("SELECT count(*) FROM tml_matches").fetchone()[0]
    return {"files_checked": len(wanted), "files_loaded": loaded, "rows_loaded": rows_total,
            "rows_total": total, "players": players}


async def sync_async(force: bool = False, only_current: bool = False) -> dict:
    """The sync off the loop, with the outcome in the system log."""
    from app.services.system_log import app_log
    try:
        out = await hdb.run(sync, force, only_current)
    except Exception as exc:
        from app.services.http_errors import describe_exception, is_transient_http_error
        err = describe_exception(exc)
        if is_transient_http_error(exc):
            logger.debug("tml sync: source unreachable: %s", err)
        else:
            await app_log("error", "history", f"TennisMyLife sync failed: {err}", {"error": err},
                          dedup_key="tml_sync_fail", dedup_hours=6)
        raise
    if out["files_loaded"]:
        await app_log("info", "history",
                      f"TennisMyLife sync: {out['files_loaded']} file(s), {out['rows_loaded']} rows "
                      f"({out['rows_total']} total)", out)
    return out
