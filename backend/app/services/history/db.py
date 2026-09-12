"""The history database: one SQLite file, plain sqlite3, always in a thread.

Not the app's async engine, on purpose. The sync replaces whole files of rows
and the rating pass reads half a million of them; both are batch work with
no business inside the request path, and the app database's writer lock is
the most contended thing on the machine. A second file keeps that work off
it entirely. Callers use `run()` to keep the event loop clear.
"""
import asyncio
import sqlite3
from pathlib import Path

from app.core.config import settings

# Kept in step with TennisMyLife's column order (Sackmann's schema), because
# the loader maps a CSV row onto it by name and the export writes the same
# shape for our own matches. Nine serve statistics a side are carried even
# though the rating does not read them: they are the raw material of the
# next model (dominance ratio, serve/return form), and they cost nothing to
# keep once the file is being read anyway.
STAT_COLS = ["ace", "df", "svpt", "1stIn", "1stWon", "2ndWon", "SvGms", "bpSaved", "bpFaced"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS tml_files (
    name TEXT PRIMARY KEY, mtime TEXT, size INTEGER, loaded_at TEXT, rows INTEGER);

CREATE TABLE IF NOT EXISTS tml_matches (
    id INTEGER PRIMARY KEY,
    tour TEXT NOT NULL,            -- 'atp' | 'wta'
    family TEXT NOT NULL,          -- 'main' | 'challenger' | 'quali' | 'ongoing'
    source_file TEXT NOT NULL,
    tourney_id TEXT NOT NULL, tourney_name TEXT, surface TEXT, draw_size INTEGER,
    tourney_level TEXT, indoor TEXT, tourney_date TEXT, match_num INTEGER,
    winner_id TEXT, winner_seed TEXT, winner_entry TEXT, winner_name TEXT, winner_hand TEXT,
    winner_ht INTEGER, winner_ioc TEXT, winner_age REAL, winner_rank INTEGER, winner_rank_points INTEGER,
    loser_id TEXT, loser_seed TEXT, loser_entry TEXT, loser_name TEXT, loser_hand TEXT,
    loser_ht INTEGER, loser_ioc TEXT, loser_age REAL, loser_rank INTEGER, loser_rank_points INTEGER,
    score TEXT, best_of INTEGER, round TEXT, minutes INTEGER,
    w_ace INTEGER, w_df INTEGER, w_svpt INTEGER, w_1stIn INTEGER, w_1stWon INTEGER,
    w_2ndWon INTEGER, w_SvGms INTEGER, w_bpSaved INTEGER, w_bpFaced INTEGER,
    l_ace INTEGER, l_df INTEGER, l_svpt INTEGER, l_1stIn INTEGER, l_1stWon INTEGER,
    l_2ndWon INTEGER, l_SvGms INTEGER, l_bpSaved INTEGER, l_bpFaced INTEGER);
-- FAMILY IS PART OF THE KEY. Qualifying and the main draw of one tournament
-- share its tourney_id and both number their matches from 1, so a key without
-- the family let the US Open's 112 qualifying rows overwrite its first 112
-- main-draw rows (2026-09-12). The preview/settled supersede logic still keys
-- on (tour, tourney_id, match_num) — a preview is always main-draw.
DROP INDEX IF EXISTS ux_tml_match;
CREATE UNIQUE INDEX IF NOT EXISTS ux_tml_match2 ON tml_matches(tour, family, tourney_id, match_num);
CREATE INDEX IF NOT EXISTS ix_tml_date ON tml_matches(tourney_date);
CREATE INDEX IF NOT EXISTS ix_tml_winner ON tml_matches(tour, winner_id);
CREATE INDEX IF NOT EXISTS ix_tml_loser ON tml_matches(tour, loser_id);

-- Every player TML has ever printed, one row per id, for the name fallback.
CREATE TABLE IF NOT EXISTS tml_players (
    tour TEXT NOT NULL, player_id TEXT NOT NULL, name TEXT, name_key TEXT,
    hand TEXT, ioc TEXT, first_date TEXT, last_date TEXT, n_matches INTEGER,
    PRIMARY KEY (tour, player_id));
CREATE INDEX IF NOT EXISTS ix_tml_players_key ON tml_players(tour, name_key);

-- OUR finished matches, in TML's shape, keyed to TML ids by the linkage.
-- What the rating reads for anything TML has not published yet.
CREATE TABLE IF NOT EXISTS own_matches (
    match_id INTEGER PRIMARY KEY,   -- our matches.id
    draw_id INTEGER NOT NULL,
    tour TEXT NOT NULL, tourney_id TEXT, tourney_name TEXT, surface TEXT, draw_size INTEGER,
    tourney_level TEXT, tourney_date TEXT,
    winner_id TEXT NOT NULL, winner_name TEXT, loser_id TEXT NOT NULL, loser_name TEXT,
    score TEXT, best_of INTEGER, round TEXT, minutes INTEGER, completed_at TEXT);
CREATE INDEX IF NOT EXISTS ix_own_date ON own_matches(tourney_date);

-- The current rating of every player the pass has seen. Rewritten whole on
-- every recompute; the pass is a few seconds, so nothing is kept incremental.
CREATE TABLE IF NOT EXISTS player_ratings (
    tour TEXT NOT NULL, player_id TEXT NOT NULL,
    as_of TEXT NOT NULL,
    elo REAL NOT NULL, elo_hard REAL, elo_clay REAL, elo_grass REAL,
    n_all INTEGER NOT NULL, n_hard INTEGER, n_clay INTEGER, n_grass INTEGER,
    last_match_date TEXT,
    PRIMARY KEY (tour, player_id));

-- ONE PERSON, TWO TML IDS. TML's WTA files give a few players a second id
-- (a 2026 's-Hertogenbosch file numbered Rybakina, Boulter and twenty others
-- afresh). Our draws are the only place that knows both ids are one person:
-- the linkage records the stub id as an alias of the established one, and the
-- rating pass reads every match through this table.
CREATE TABLE IF NOT EXISTS tml_aliases (
    tour TEXT NOT NULL, alias_id TEXT NOT NULL, canonical_id TEXT NOT NULL, reason TEXT,
    PRIMARY KEY (tour, alias_id));

CREATE TABLE IF NOT EXISTS history_meta (key TEXT PRIMARY KEY, value TEXT);
"""


def path() -> Path:
    return Path(settings.history_db_path)


def connect() -> sqlite3.Connection:
    """A connection with the schema ensured. WAL, so the daily rewrite of a
    file's rows never blocks a rating read in another thread."""
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


async def run(fn, *args):
    """Run a sync function that takes a connection, off the event loop."""
    def _go():
        conn = connect()
        try:
            return fn(conn, *args)
        finally:
            conn.close()
    return await asyncio.to_thread(_go)


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM history_meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_meta(conn, key, value) -> None:
    conn.execute("INSERT OR REPLACE INTO history_meta (key, value) VALUES (?, ?)", (key, str(value)))
