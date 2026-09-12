"""Fill draw_entries.seed_week_ranking for every draw already on file.

The badge's scale is the seeds and then everyone else behind them, and from
2026-09-12 the second half is ordered by the OFFICIAL SEEDING WEEK rather than
by the entry week (`ranking`), so that one scale comes from one moment. New
scrapes stamp it; this is for the draws that were scraped before the column
existed.

    .venv/bin/python scripts/backfill_seed_week_rankings.py            # report
    .venv/bin/python scripts/backfill_seed_week_rankings.py --write    # do it

Uses services.rankings.assign_seed_week_rankings, the same function the scraper
calls — a backfill that computed the week itself is a second implementation
waiting to disagree with the first.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select                                    # noqa: E402

from app.database import AsyncSessionLocal, register_models     # noqa: E402
from app.models.tournament import Draw, DrawEntry                # noqa: E402
from app.services.rankings import assign_seed_week_rankings      # noqa: E402

# Every model, or the first relationship SQLAlchemy cannot resolve raises
# "expression 'User' failed to locate a name" — an incomplete import wearing
# the costume of a broken model.
register_models()


async def main(write: bool) -> int:
    filled = skipped = 0
    async with AsyncSessionLocal() as db:
        draws = list((await db.execute(
            select(Draw).order_by(Draw.start_date))).scalars())
        for d in draws:
            entries = list((await db.execute(
                select(DrawEntry).where(DrawEntry.draw_id == d.id))).scalars())
            if not entries:
                continue
            if d.seed_ranking_week is None:
                # Nothing to date the seeds from. The readers fall back to
                # `ranking`, which is what they did before this existed.
                skipped += 1
                print(f'  draw {d.id:>4} {d.name[:28]:28} {d.year} — no seeding week')
                continue
            n = await assign_seed_week_rankings(entries, d.gender,
                                                d.seed_ranking_week, db)
            unseeded = sum(1 for e in entries if e.seed is None)
            if n:
                filled += n
                print(f'  draw {d.id:>4} {d.name[:28]:28} {d.year} — '
                      f'{n} of {len(entries)} stamped ({unseeded} unseeded)')
        if write:
            await db.commit()
            print('committed')
        else:
            await db.rollback()
            print('DRY RUN — nothing written; pass --write')
    print(f'{filled} entries stamped, {len(draws)} draws seen, '
          f'{skipped} with no seeding week')
    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main('--write' in sys.argv)))
