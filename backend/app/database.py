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
    ]
    for sql in migrations:
        try:
            await conn.execute(_text(sql))
        except Exception:
            pass  # Column already exists — safe to ignore


from sqlalchemy import text as _text
