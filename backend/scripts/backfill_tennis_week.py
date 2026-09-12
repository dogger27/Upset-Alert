"""Recompute draws.week with the tour's own Monday.

A Sunday-start event is six days into the PREVIOUS week by arithmetic and in
the NEXT week by the tour's calendar. Nine of the 111 draws on file start on a
Sunday and one on a Saturday, so their stored week is one short — which is how
Guadalajara (Sun 13 Sep, week 36) and SP Open (Mon 14 Sep, week 37) became two
draw-release emails instead of one.

    .venv/bin/python scripts/backfill_tennis_week.py          # report
    .venv/bin/python scripts/backfill_tennis_week.py --write  # do it

REFUSES TO TOUCH A PENDING RELEASE. Moving a draw into a week whose email has
already gone out makes it a late arrival, which the batcher stamps as notified
and never emails — so a draw still waiting for its announcement is left alone
and named, for a human to decide.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select                                  # noqa: E402

from app.database import AsyncSessionLocal, register_models     # noqa: E402
from app.models.tournament import Draw                          # noqa: E402
from app.services.tournament_sync import tennis_week            # noqa: E402

register_models()


async def main(write: bool) -> int:
    changed = held = 0
    async with AsyncSessionLocal() as db:
        draws = list((await db.execute(
            select(Draw).where(Draw.start_date.isnot(None))
            .order_by(Draw.start_date))).scalars())
        for d in draws:
            want = tennis_week(d.start_date, d.year)
            if want == d.week:
                continue
            pending = (d.draw_released_direct_at is not None
                       and d.draw_release_notified_at is None)
            mark = ''
            if pending:
                held += 1
                mark = '   ** PENDING RELEASE — left alone'
            else:
                changed += 1
                if write:
                    d.week = want
            print(f'  draw {d.id:>4} {d.name[:26]:26} {d.gender} {d.start_date} '
                  f'{d.start_date.strftime("%a")}  week {d.week} -> {want}{mark}')
        if write:
            await db.commit()
            print('committed')
        else:
            await db.rollback()
            print('DRY RUN — nothing written; pass --write')
    print(f'{changed} draw(s) re-weeked, {held} left alone as pending, '
          f'{len(draws)} seen')
    return 1 if held else 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main('--write' in sys.argv)))
