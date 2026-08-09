from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

_IS_SQLITE = settings.database_url.startswith("sqlite")

# timeout is the DRIVER-level wait for a held write lock. Without it sqlite3
# gives up immediately, which is what surfaced as "Failed to save: Unknown
# error" when a user saved picks while the scheduler or the ESPN monitor
# happened to be writing.
engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args={"timeout": 30} if _IS_SQLITE else {},
)


if _IS_SQLITE:
    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        """WAL + busy_timeout on every connection.

        The default rollback journal takes an exclusive lock for the whole of a
        write, so any concurrent writer fails outright rather than waiting —
        and this app always has background writers (the 30-minute scrape, the
        ESPN poller, the notification jobs). WAL lets readers continue during a
        write and, with busy_timeout, makes a competing writer queue for up to
        30s instead of raising "database is locked" on the spot.

        synchronous=NORMAL is the standard companion to WAL: still crash-safe,
        without an fsync per commit.
        """
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    # Ensure all model modules are imported so their tables are registered with
    # Base.metadata before create_all runs.
    # EVERY model module, not just the ones without a home elsewhere. The list
    # used to name five, and worked only because main.py imports the routers
    # first, which drag in the rest — so create_all was resolving foreign keys
    # against a registry this function had not actually populated. Anything
    # calling init_db on its own (a migration script, a test) hit
    # NoReferencedTableError instead, and each newly cross-referenced table made
    # that trap a little worse.
    import app.models.alert  # noqa: F401
    import app.models.draw_history  # noqa: F401
    import app.models.h2h  # noqa: F401
    import app.models.league  # noqa: F401
    import app.models.notification  # noqa: F401
    import app.models.prediction  # noqa: F401
    import app.models.push  # noqa: F401
    import app.models.rankings   # noqa: F401
    import app.models.system_log  # noqa: F401
    import app.models.tournament  # noqa: F401
    import app.models.user  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Add any missing columns that were introduced after initial creation
        await _migrate(conn)


async def _migrate(conn):
    """Apply additive schema migrations that create_all won't handle."""
    migrations = [
        "ALTER TABLE matches ADD COLUMN scores_json JSON",
        "ALTER TABLE players ADD COLUMN ranking INTEGER",
        "ALTER TABLE tournaments ADD COLUMN category VARCHAR",
        "ALTER TABLE tournaments ADD COLUMN draw_release_direct DATE",
        "ALTER TABLE tournaments ADD COLUMN draw_release_qualifiers DATE",
        "ALTER TABLE tournaments ADD COLUMN draw_released_direct_at DATE",
        "ALTER TABLE tournaments ADD COLUMN draw_released_qualifiers_at DATE",
        "ALTER TABLE tournaments ADD COLUMN city VARCHAR",
        "ALTER TABLE tournaments ADD COLUMN country VARCHAR",
        "ALTER TABLE users ADD COLUMN username VARCHAR",
        "ALTER TABLE users ADD COLUMN full_name VARCHAR",
        "ALTER TABLE leagues ADD COLUMN show_real_name BOOLEAN DEFAULT 0",
        # Rankings cache tables
        (
            "CREATE TABLE IF NOT EXISTS te_players "
            "(id INTEGER PRIMARY KEY, gender VARCHAR(1) NOT NULL, "
            "name_raw VARCHAR NOT NULL UNIQUE, name_norm VARCHAR NOT NULL)"
        ),
        (
            "CREATE TABLE IF NOT EXISTS te_rankings_snapshots "
            "(player_id INTEGER NOT NULL REFERENCES te_players(id), "
            "week_date DATE NOT NULL, rank INTEGER NOT NULL, "
            "PRIMARY KEY (player_id, week_date))"
        ),
        "CREATE INDEX IF NOT EXISTS idx_te_snap_week ON te_rankings_snapshots(week_date)",
        "ALTER TABLE players ADD COLUMN te_player_id INTEGER",
        "ALTER TABLE tournaments ADD COLUMN selections_unlocked BOOLEAN DEFAULT 0",
        "ALTER TABLE te_players ADD COLUMN te_slug VARCHAR",
        (
            "CREATE TABLE IF NOT EXISTS h2h_cache "
            "(slug_a VARCHAR NOT NULL, slug_b VARCHAR NOT NULL, "
            "fetched_at DATETIME NOT NULL, data_json JSON NOT NULL, "
            "PRIMARY KEY (slug_a, slug_b))"
        ),
        "ALTER TABLE players ADD COLUMN date_of_birth DATE",
        "ALTER TABLE te_players ADD COLUMN date_of_birth DATE",
        "ALTER TABLE players RENAME TO draw_entries",
        "ALTER TABLE tournaments ADD COLUMN picks_locked_at DATETIME",
        "ALTER TABLE te_players ADD COLUMN elo INTEGER",
        "ALTER TABLE matches ADD COLUMN live_scores_json JSON",
        (
            "CREATE TABLE IF NOT EXISTS notification_preferences "
            "(user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
            "pref_key VARCHAR NOT NULL, "
            "PRIMARY KEY (user_id, pref_key))"
        ),
        "ALTER TABLE tournaments ADD COLUMN completion_notified_at DATETIME",
        (
            "CREATE TABLE IF NOT EXISTS system_logs "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "created_at DATETIME NOT NULL, "
            "level VARCHAR NOT NULL, "
            "category VARCHAR NOT NULL, "
            "message VARCHAR NOT NULL, "
            "detail_json JSON)"
        ),
        "CREATE INDEX IF NOT EXISTS idx_sys_logs_created ON system_logs(created_at DESC)",
        (
            "CREATE TABLE IF NOT EXISTS tournament_results "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "user_id INTEGER NOT NULL, "
            "tournament_id INTEGER NOT NULL, "
            "league_id INTEGER, "
            "league_name VARCHAR NOT NULL, "
            "rank INTEGER NOT NULL, "
            "total_participants INTEGER NOT NULL, "
            "points REAL NOT NULL, "
            "correct_count INTEGER NOT NULL, "
            "saved_at DATETIME NOT NULL, "
            "UNIQUE (user_id, tournament_id, league_id))"
        ),
        "CREATE INDEX IF NOT EXISTS idx_tr_user ON tournament_results(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_tr_tourn ON tournament_results(tournament_id)",
        "ALTER TABLE matches ADD COLUMN served_first INTEGER",
        # Clear wrong page_id: 80434323 is the general Wimbledon event page, not Women's Singles
        "UPDATE tournaments SET wiki_page_id = NULL WHERE wiki_page_title = '2026 Wimbledon Championships – Women''s singles' AND wiki_page_id = 80434323",
        "ALTER TABLE te_rankings_snapshots ADD COLUMN points INTEGER",
        "ALTER TABLE te_players ADD COLUMN elo_rank INTEGER",
        "ALTER TABLE te_players ADD COLUMN name_display VARCHAR",
        "ALTER TABLE te_players ADD COLUMN first_name VARCHAR",
        "ALTER TABLE te_players ADD COLUMN last_name VARCHAR",
        "ALTER TABLE te_rankings_snapshots ADD COLUMN elo INTEGER",
        "ALTER TABLE te_rankings_snapshots ADD COLUMN elo_rank INTEGER",
        "ALTER TABLE te_players ADD COLUMN nationality VARCHAR",
        "ALTER TABLE te_players DROP COLUMN elo",
        "ALTER TABLE te_players DROP COLUMN elo_rank",
        "ALTER TABLE draw_entries ADD COLUMN te_slug VARCHAR",
        "ALTER TABLE draws ADD COLUMN week INTEGER",
        "ALTER TABLE draws ADD COLUMN draw_release_detected_at DATETIME",
        "ALTER TABLE draws ADD COLUMN draw_release_notified_at DATETIME",
        # Backfill draw_release_detected_at for draws released BEFORE this column
        # existed, so the new centralized notify job (scheduler.py) can pick them
        # up — fixes tournaments (e.g. Swedish Open) whose "draw released" email
        # was missed by the old ad-hoc per-call-site checks. Scoped tightly to
        # currently-relevant draws only (not completed, not already finished, not
        # a stale future-dated row) so this can't retroactively spam users with
        # "draw released" emails for tournaments from months ago.
        (
            "UPDATE draws SET draw_release_detected_at = datetime('now', '-30 minutes') "
            "WHERE draw_released_direct_at IS NOT NULL "
            "AND draw_release_detected_at IS NULL "
            "AND status != 'completed' "
            "AND (end_date IS NULL OR end_date >= date('now', '-1 day'))"
        ),
        # 2026 WTA Tour season page has a malformed literal wikilink for Iași Open
        # ("[[2026 Iași Open –Singles|Singles]]" — missing space + "Women's"), so
        # our season-page parser faithfully captured a title that doesn't resolve
        # (verified: real article is "2026 Iași Open – Women's singles", pageid
        # 83670759). Correct it and stamp the real page_id directly.
        (
            "UPDATE draws SET wiki_page_title = '2026 Iași Open – Women''s singles', "
            "wiki_page_id = 83670759 "
            "WHERE wiki_page_title = '2026 Iași Open –Singles'"
        ),
        "ALTER TABLE users ADD COLUMN is_bot BOOLEAN DEFAULT 0",
        # Honest measure of when a draw was actually published on Wikipedia,
        # replacing da_days_before as the input to the release-date predictor.
        # Deliberately NOT backfilled from da_days_before: that column records
        # when the page crossed our 50%-complete threshold, which is exactly the
        # biased-late signal this column exists to stop learning from. Seeding it
        # with those values would carry the bias straight into the new estimator.
        # Until enough clean samples accumulate the predictor falls back to the
        # curated draw_categories defaults, which is the desired conservative
        # behaviour.
        "ALTER TABLE draws ADD COLUMN bracket_first_seen_at DATE",
        "ALTER TABLE draws ADD COLUMN bracket_first_seen_days_before INTEGER",
        # Draw-release emails became a weekly digest covering every draw released
        # that week, which makes a per-tier opt-in meaningless — it could only
        # filter rows out of a mail the user receives either way. Collapse the
        # eight 'draw_open:<tier>' keys into one on/off. Anyone opted in to ANY
        # tier stays opted in, so nobody silently stops being notified.
        (
            "INSERT OR IGNORE INTO notification_preferences (user_id, pref_key) "
            "SELECT DISTINCT user_id, 'draw_released' FROM notification_preferences "
            "WHERE pref_key LIKE 'draw_open:%'"
        ),
        "DELETE FROM notification_preferences WHERE pref_key LIKE 'draw_open:%'",
        # IANA zone id for rendering deadlines in outgoing email. Populated
        # silently from the browser on next load, so it stays NULL for users who
        # never return — every read falls back to UTC.
        "ALTER TABLE users ADD COLUMN timezone VARCHAR",
        "ALTER TABLE users ADD COLUMN mobile_app_seen_at DATETIME",
        # Round-completion emails became a weekly digest: a completed round is
        # now claimed on detection and emailed later, once the week's other
        # draws have reached the same round. digest_sent_at marks "actually
        # emailed"; NULL means still pending.
        "ALTER TABLE round_complete_notifications ADD COLUMN digest_sent_at DATETIME",
        # Backfill every pre-existing row. Without this, each historical round
        # would look pending on first boot and the digest job would re-send
        # months of round emails to everyone.
        # Scoped to rows that predate the digest going live (2026-07-29 02:49 UTC).
        # This list re-runs on EVERY startup, so the unscoped version of this
        # statement did not backfill once — it re-fired on each deploy and
        # stamped any round still waiting for its week's batch as already sent,
        # silently dropping it. That is what swallowed the R32 digest for week
        # 30: Los Cabos was queued at 09:24 and marked sent by a restart at
        # 18:45 without an email ever going out.
        (
            "UPDATE round_complete_notifications SET digest_sent_at = sent_at "
            "WHERE digest_sent_at IS NULL AND sent_at < '2026-07-29 02:49:00'"
        ),
        # Release the rounds the unscoped version above already swallowed. Its
        # signature is exact: digest_sent_at copied verbatim from sent_at, and
        # recipient_count still 0 because no send ever ran. A genuine
        # zero-recipient send stamps a later digest_sent_at than sent_at, so it
        # is not matched; and once these do send, recipient_count moves off 0,
        # so this cannot re-fire on the next boot.
        (
            "UPDATE round_complete_notifications SET digest_sent_at = NULL "
            "WHERE recipient_count = 0 AND digest_sent_at = sent_at "
            "AND sent_at >= '2026-07-29 02:49:00'"
        ),
        # A draw entry matched to a TE player but never slug-stamped (qualifiers
        # who arrive between ranking runs are the usual case) loses its Form and
        # head-to-head record even though we know exactly whose profile it is.
        # assign_rankings does this too; here it is idempotent and needs no
        # scrape, so the gap closes at boot rather than at the next ranking run.
        # Safe now that a name change clears te_slug alongside te_player_id
        # (routers/tournaments.py) — otherwise this could restore a replaced
        # player's slug.
        (
            "UPDATE draw_entries SET te_slug = ("
            "  SELECT te_slug FROM te_players WHERE te_players.id = draw_entries.te_player_id"
            ") WHERE te_slug IS NULL AND te_player_id IS NOT NULL"
        ),
        # Ledger for statements that must run exactly ONCE, ever.
        #
        # Everything else in this list is idempotent by construction — an ALTER
        # that fails because the column exists, an UPDATE whose WHERE stops
        # matching. Seeding a user preference is neither: it re-matches forever,
        # so an unguarded seed re-enables on the next deploy whatever the user
        # switched off after the last one. The same trap already cost this file a
        # swallowed round digest (see the round_complete_notifications backfill
        # above), where a timestamp literal was the fix; a named ledger says what
        # it means and does not need a magic date.
        (
            "CREATE TABLE IF NOT EXISTS applied_seeds "
            "(name VARCHAR PRIMARY KEY, applied_at DATETIME NOT NULL)"
        ),
        # draw_changed and standout_pick are opt-in, full stop — nobody is
        # enrolled into a notification they did not ask for, however closely it
        # resembles one they already take.
        #
        # This undoes a seeding pass that briefly shipped on 2026-08-09 and
        # derived each new preference from the nearest existing one
        # (draw_changed from draw_released, standout_pick from round_standings,
        # each per channel). It ran once against production before being
        # reversed, so the rows it created have to be cleared here rather than
        # simply not created.
        #
        # Ledger-guarded, and this one HAS to be: without the guard it is a
        # standing DELETE that would wipe the preference again on every restart,
        # silently undoing the choice of anyone who later turns these on. That is
        # the same trap the seeds were guarded against, pointed the other way.
        (
            "DELETE FROM notification_preferences "
            "WHERE pref_key IN ('draw_changed', 'push_draw_changed', "
            "                   'standout_pick', 'push_standout_pick') "
            "AND NOT EXISTS (SELECT 1 FROM applied_seeds WHERE name = 'unseed_optional_notifications')"
        ),
        (
            "INSERT OR IGNORE INTO applied_seeds (name, applied_at) "
            "VALUES ('unseed_optional_notifications', datetime('now'))"
        ),
        # Pre-stamp every match that had already finished before standout-pick
        # measurement existed. Without this the first sweep after deploy would
        # measure an entire tournament's worth of history at once and send every
        # competitor a notification for picks they made weeks ago.
        #
        # Ledger-guarded like the seeds above, and for a sharper reason: this
        # statement matches every completed match there will ever be, so an
        # unguarded re-run on the next deploy would pre-stamp — and therefore
        # permanently silence — every match that finished since the last one.
        # That would not degrade the feature, it would disable it.
        #
        # Marked notified rather than merely measured, and with zero counts: no
        # message was ever sent for these and none should be, so recording a
        # correct_count would only invite a later reader to believe one was.
        (
            "INSERT OR IGNORE INTO standout_pick_notifications "
            "(match_id, draw_id, correct_count, participant_count, detected_at, "
            " notified_at, recipient_count) "
            "SELECT id, draw_id, 0, 0, datetime('now'), datetime('now'), 0 "
            "FROM matches WHERE winner_id IS NOT NULL AND is_bye = 0 "
            "AND NOT EXISTS (SELECT 1 FROM applied_seeds WHERE name = 'seed_standout_backfill')"
        ),
        (
            "INSERT OR IGNORE INTO applied_seeds (name, applied_at) "
            "VALUES ('seed_standout_backfill', datetime('now'))"
        ),
    ]
    for sql in migrations:
        try:
            await conn.execute(_text(sql))
        except Exception:
            pass  # Column already exists — safe to ignore

    # Backfill ATP tennis week number for draws.  Recompute all rows so any
    # previously ISO-stamped values are corrected.
    # Week 0 = December-start event belonging to the following season year.
    # Week 1 = first Monday of January in the season year (early-Jan events clamped to 1).
    from datetime import date as _date, timedelta as _td
    def _tennis_week(d: _date, season_year: int) -> int:
        if d.year < season_year:
            return 0
        jan1 = _date(season_year, 1, 1)
        first_monday = jan1 + _td(days=(7 - jan1.weekday()) % 7)
        return max(1, (d - first_monday).days // 7 + 1)

    result = await conn.execute(_text(
        "SELECT id, year, start_date FROM draws WHERE start_date IS NOT NULL"
    ))
    for row in result.fetchall():
        d = _date.fromisoformat(str(row[2]))
        week = _tennis_week(d, int(row[1]))
        await conn.execute(_text("UPDATE draws SET week = :w WHERE id = :id"), {"w": week, "id": row[0]})


from sqlalchemy import text as _text
