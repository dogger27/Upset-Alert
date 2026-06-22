from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    # Ensure all model modules are imported so their tables are registered with
    # Base.metadata before create_all runs.
    import app.models.rankings  # noqa: F401

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
    ]
    for sql in migrations:
        try:
            await conn.execute(_text(sql))
        except Exception:
            pass  # Column already exists — safe to ignore


from sqlalchemy import text as _text
