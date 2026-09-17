"""THE INFERRED SEED OF A DOUBLES PAIR (owner, 2026-09-17).

A pair's entry and seeding come from the SUM of its two players' doubles
rankings at the seeding week — so an unseeded team's place in the field is
the rank of that sum among every pair in the draw, behind the seeds, exactly
the shape of the singles badge (services/upsets.py::_compute_draw_ranks).

Sofascore holds no doubles ranking at all — a player carries one `ranking`
and it is the live singles rank — so the figure comes from Tennis Explorer's
weekly doubles list (rankings.py::ensure_te_doubles_week), snapshotted like
the singles one and read at the tournament's seeding week.

Read-only on the request path. The badge is served by the schedule day
endpoint, which the live subscription polls every ten seconds, so the answer
is cached per tournament for a few minutes; a seeding week we do not hold yet
is fetched in the background, by its own session, and the next request sees
it. Doubles pairs are identified by their two players, so the same team is one
pair across every day and round of the event.
"""
import asyncio
import logging
import time
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

_TTL_SECONDS = 300
# tournament_id -> (monotonic time, {(schedule_entry_id, side): rank})
_cache: dict[int, tuple[float, dict]] = {}
# Weeks being fetched right now, so a burst of requests launches one fetch.
_filling: set[tuple[str, date]] = set()
# (gender, week) fetches that came back empty — TE had nothing for the date —
# so the page is not asked again for an hour.
_declined: dict[tuple[str, date], float] = {}


def rank_pairs(pairs: list[tuple[object, Optional[int], Optional[int]]]) -> dict[object, int]:
    """(key, seed, sum-of-ranks) per pair -> key -> inferred rank.

    A seeded pair keeps its seed. The unseeded follow in order of the sum,
    numbered from just past the seeds — the count of seeds as the sheet
    printed them, or the highest seed if the sheet showed more of the field
    than the day did. Equal sums share a rank (1, 2, 2, 4). A pair whose sum
    is unknown — a player the rankings do not name — gets no rank at all,
    rather than a guess.
    """
    out: dict[object, int] = {}
    seeds = [s for _, s, _ in pairs if s]
    for key, seed, _ in pairs:
        if seed:
            out[key] = seed
    base = max(len(seeds), max(seeds) if seeds else 0)
    ranked = sorted(((total, key) for key, seed, total in pairs if not seed and total is not None),
                    key=lambda x: x[0])
    last_total, last_rank = None, 0
    for i, (total, key) in enumerate(ranked, start=1):
        if total != last_total:
            last_rank = base + i
            last_total = total
        out[key] = last_rank
    return out


def _monday(d: date) -> date:
    from app.services.rankings import _monday
    return _monday(d)


async def _latest_week(db, gender: str, on_or_before: date) -> Optional[date]:
    from app.models.rankings import TeDoublesSnapshot, TePlayer
    return (await db.execute(
        select(TeDoublesSnapshot.week_date)
        .join(TePlayer, TePlayer.id == TeDoublesSnapshot.player_id)
        .where(TePlayer.gender == gender, TeDoublesSnapshot.week_date <= on_or_before)
        .order_by(TeDoublesSnapshot.week_date.desc())
        .limit(1)
    )).scalar_one_or_none()


def _fill_week_in_background(gender: str, week: date) -> None:
    """Fetch a seeding week we do not hold, off the request path."""
    key = (gender, week)
    if key in _filling:
        return
    declined_at = _declined.get(key)
    if declined_at is not None and time.monotonic() - declined_at < 3600:
        return
    _filling.add(key)

    async def _run():
        try:
            from app.database import AsyncSessionLocal
            from app.services.rankings import ensure_te_doubles_week
            async with AsyncSessionLocal() as db:
                stored = await ensure_te_doubles_week(gender, week, db, log_errors=True)
                if stored:
                    await db.commit()
                    _cache.clear()
                    logger.info("Doubles rankings: stored %s week %s for the seeding badge", gender, week)
                else:
                    _declined[key] = time.monotonic()
        except Exception:
            logger.exception("Doubles rankings: background fetch of %s week %s failed", gender, week)
            _declined[key] = time.monotonic()
        finally:
            _filling.discard(key)

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        _filling.discard(key)


async def _compute(db, tournament_id: int) -> dict[tuple[int, str], int]:
    from app.models.rankings import TeDoublesSnapshot, TePlayer
    from app.models.schedule import ScheduleEntry
    from app.models.tournament import DrawEntry, Tournament
    from app.routers.schedule import _name_key, _printed_mark
    from app.services.rankings import _build_te_index, _match_token_set

    t = await db.get(Tournament, tournament_id)
    if t is None:
        return {}
    anchor = t.seed_ranking_week or t.start_date or date.today()
    target = _monday(anchor)
    week = await _latest_week(db, t.gender, target)
    if week is None:
        _fill_week_in_background(t.gender, target)
        return {}
    if week < target:
        # We hold an older week; the seeding week itself is worth fetching.
        _fill_week_in_background(t.gender, target)

    entries = (await db.execute(
        select(ScheduleEntry)
        .options(selectinload(ScheduleEntry.players))
        .where(ScheduleEntry.tournament_id == tournament_id,
               ScheduleEntry.discipline == "doubles",
               ScheduleEntry.stage == "main")
    )).scalars().all()
    if not entries:
        return {}

    ranks_by_te = {s.player_id: s.rank for s in (await db.execute(
        select(TeDoublesSnapshot).where(TeDoublesSnapshot.week_date == week))).scalars()}
    te_players = (await db.execute(select(TePlayer).where(TePlayer.gender == t.gender))).scalars().all()
    te_index, _norms, _slugs = _build_te_index(te_players)

    de_ids = {p.draw_entry_id for e in entries for p in e.players if p.draw_entry_id}
    te_by_entry: dict[int, int] = {}
    if de_ids:
        for de in (await db.execute(select(DrawEntry).where(DrawEntry.id.in_(de_ids)))).scalars():
            if de.te_player_id:
                te_by_entry[de.id] = de.te_player_id

    def te_id_of(p) -> Optional[int]:
        if p.draw_entry_id and p.draw_entry_id in te_by_entry:
            return te_by_entry[p.draw_entry_id]
        name = _name_key(p.raw_name)
        return _match_token_set(name, te_index) if name else None

    pairs: dict[object, tuple[Optional[int], Optional[int]]] = {}
    where: list[tuple[int, str, object]] = []
    for e in entries:
        for side in ("a", "b"):
            ps = [p for p in e.players if p.side == side]
            if len(ps) != 2:
                continue
            ids = [te_id_of(p) for p in ps]
            key = frozenset(ids) if all(ids) else frozenset(_name_key(p.raw_name) for p in ps)
            seed = next((s for s in (_printed_mark(p.raw_name)[0] for p in ps) if s), None)
            total = None
            if all(ids):
                rs = [ranks_by_te.get(i) for i in ids]
                if all(r is not None for r in rs):
                    total = sum(rs)
            prev = pairs.get(key)
            # The sheet may print the seed on one day and not another: keep it.
            pairs[key] = (seed or (prev[0] if prev else None), total if total is not None else (prev[1] if prev else None))
            where.append((e.id, side, key))

    ranked = rank_pairs([(k, s, tot) for k, (s, tot) in pairs.items()])
    return {(eid, side): ranked[key] for eid, side, key in where if key in ranked}


async def doubles_pair_ranks(db, tournament_id: int) -> dict[tuple[int, str], int]:
    """{(schedule_entry_id, side): inferred rank} for a tournament's doubles."""
    now = time.monotonic()
    hit = _cache.get(tournament_id)
    if hit and now - hit[0] < _TTL_SECONDS:
        return hit[1]
    try:
        result = await _compute(db, tournament_id)
    except Exception:
        logger.exception("Doubles pair ranks failed for tournament %s", tournament_id)
        result = {}
    _cache[tournament_id] = (now, result)
    return result
