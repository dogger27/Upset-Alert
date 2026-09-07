"""Collect how long tennis actually takes, from Sofascore's own set clocks.

    docker compose exec -T backend python -m scripts.backfill_durations --help
    ... --from-year 2022 --pace 5
    ... --from-year 2022 --pace 5 --max-requests 400     # a chunk at a time

WHY THIS IS CHEAP. The season endpoint returns THIRTY finished events per
request, and each one carries everything needed: `time.periodN` (the length of
each set), the uniqueTournament's tour, level and surface, `homeTeam.type`
(1 person = singles, 2 pair = doubles) and the round. So one request is thirty
fully classified, fully timed matches — where asking per match would be thirty
requests for the same thing.

WHY 2022. All four Grand Slams settled on a 10-point tiebreak at 6-6 in the
final set that season. Before it, final sets were unlimited at some events and
first-to-12 at others, and a match that could run six hours is not the same
sport for the purpose of predicting when the next one starts. Sofascore's set
clocks also thin out further back — a 2009 page carried none at all — so there
is little to gain and a skewed average to lose.

RESUMABLE AND IDEMPOTENT. Every sample is keyed by its Sofascore event id with
a unique constraint, so a run that is interrupted, repeated, or overlapped with
another loses nothing and double-counts nothing. --max-requests exists so this
can be done in evenings rather than in one sitting.

POLITENESS IS THE POINT. Jupiter's own IP is the only route since the proxy
lapsed, and a 403 bans the host rather than the request. --pace is seconds
between requests on top of the client's own gate, and the run stops dead the
first time the circuit breaker trips.
"""

import argparse
import asyncio
import logging
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("durations")

# Tour-level singles and doubles. Challengers and ITF are deliberately out:
# they are a different standard of match and we schedule none of them.
CATEGORIES = {3: "ATP", 6: "WTA", -100: "Grand Slam"}

# tennisPoints we care to keep. Everything else — the Finals, exhibitions,
# team events — awards none or an odd number and is not a level we estimate.
LEVELS = {250, 500, 1000, 2000}

# A run of pages returning nothing new means this season is already collected.
STOP_AFTER_BARREN_PAGES = 2


def _played_minutes(ev: dict) -> Optional[int]:
    """Sum of the per-set clocks, in minutes — PLAYING time, not wall clock."""
    periods = [v for k, v in (ev.get("time") or {}).items()
               if k.startswith("period") and isinstance(v, int) and v > 0]
    if not periods:
        return None
    mins = int(round(sum(periods) / 60))
    # Wide enough for a five-set Slam, tight enough that a mis-parse or a
    # suspension inside a set cannot pass as a match.
    return mins if 15 <= mins <= 360 else None


def _classify(ev: dict) -> Optional[dict]:
    ut = ((ev.get("tournament") or {}).get("uniqueTournament")) or {}
    level = ut.get("tennisPoints")
    if level not in LEVELS:
        return None
    if (ev.get("status") or {}).get("type") != "finished":
        return None
    mins = _played_minutes(ev)
    if mins is None:
        return None
    # A PAIR rather than a person is how doubles announces itself; there is no
    # discipline field on the event.
    pair = (ev.get("homeTeam") or {}).get("type") == 2
    name = ((ev.get("roundInfo") or {}).get("name") or "").lower()
    slug = ((ev.get("roundInfo") or {}).get("slug") or "").lower()
    qualifying = "qualif" in name or "qualif" in slug
    # THE SETS THEMSELVES, in order, not just their total. `time.periodN` is
    # the clock; homeScore/awayScore.periodN are the games. Keeping both is
    # what lets a later question — how long is a set here, how often does a
    # two-set lead end it — be answered without fetching any of this again.
    home, away = ev.get("homeScore") or {}, ev.get("awayScore") or {}
    clocks = ev.get("time") or {}
    seconds, games = [], []
    for i in range(1, 6):
        key = f"period{i}"
        if key not in clocks and key not in home:
            break
        seconds.append(clocks.get(key))
        games.append([home.get(key), away.get(key)])
    return {
        "sofa_event_id": ev.get("id"),
        "tour": (ut.get("category") or {}).get("name"),
        "level": level,
        "surface": ut.get("groundType"),
        "discipline": "doubles" if pair else "singles",
        "stage": "qualifying" if qualifying else "main",
        "sets_played": len(games) or None,
        "duration_min": mins,
        "set_seconds_json": seconds or None,
        "set_games_json": games or None,
        "winner_code": ev.get("winnerCode"),
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-year", type=int, default=2022)
    ap.add_argument("--pace", type=float, default=5.0,
                    help="seconds between requests, on top of the client's own gate")
    ap.add_argument("--max-requests", type=int, default=0, help="0 = no limit")
    ap.add_argument("--max-pages", type=int, default=40, help="per season, a safety stop")
    args = ap.parse_args()

    from sqlalchemy import func, select
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from app.database import AsyncSessionLocal
    from app.models.duration_sample import MatchDurationSample
    from app.services.sofascore import SofascoreBlocked, load_egress, _get

    async with AsyncSessionLocal() as db:
        await load_egress(db)
        before = (await db.execute(
            select(func.count()).select_from(MatchDurationSample))).scalar_one()
    logger.info("samples already held: %d", before)

    requests = 0
    stored = 0

    async def get(path):
        nonlocal requests
        if args.max_requests and requests >= args.max_requests:
            raise StopAsyncIteration
        requests += 1
        out = await _get(path)
        await asyncio.sleep(args.pace)
        return out

    try:
        # 1. The universe of tournaments, three requests.
        uts: dict[int, str] = {}
        for cat_id, cat_name in CATEGORIES.items():
            payload = await get(f"/category/{cat_id}/unique-tournaments")
            for group in payload.get("groups") or []:
                for t in group.get("uniqueTournaments") or []:
                    if t.get("id"):
                        uts[t["id"]] = t.get("name") or str(t["id"])
        logger.info("tournaments in scope: %d", len(uts))

        # 2. Each tournament's seasons, then each season's finished events.
        for ut_id, ut_name in sorted(uts.items()):
            try:
                seasons = (await get(f"/unique-tournament/{ut_id}/seasons")).get("seasons") or []
            except Exception as exc:                               # noqa: BLE001
                if isinstance(exc, (SofascoreBlocked, StopAsyncIteration)):
                    raise
                logger.info("  %s: no seasons (%s)", ut_name, type(exc).__name__)
                continue

            for season in seasons:
                year = season.get("year")
                try:
                    year_i = int(str(year)[:4])
                except (TypeError, ValueError):
                    continue
                if year_i < args.from_year:
                    continue

                barren = 0
                for page in range(args.max_pages):
                    try:
                        payload = await get(
                            f"/unique-tournament/{ut_id}/season/{season['id']}"
                            f"/events/last/{page}")
                    except StopAsyncIteration:
                        raise
                    except SofascoreBlocked:
                        raise
                    except Exception:
                        break            # past the last page, or a transient miss
                    events = payload.get("events") or []
                    if not events:
                        break

                    rows = [r for r in (_classify(e) for e in events) if r]
                    for r in rows:
                        r["season_year"] = year_i
                    if rows:
                        async with AsyncSessionLocal() as db:
                            # Ignore anything already held: the event id is
                            # unique, so re-running costs nothing and repairs
                            # a half-finished run.
                            res = await db.execute(
                                sqlite_insert(MatchDurationSample)
                                .values(rows).prefix_with("OR IGNORE"))
                            await db.commit()
                            stored += res.rowcount or 0
                        barren = 0
                    else:
                        barren += 1
                        if barren >= STOP_AFTER_BARREN_PAGES:
                            break
                logger.info("  %-34s %s: %d requests, %d stored so far",
                            ut_name[:34], year_i, requests, stored)
    except StopAsyncIteration:
        logger.info("stopped at the --max-requests limit")
    except SofascoreBlocked as exc:
        logger.warning("BLOCKED, stopping immediately: %s", exc)

    async with AsyncSessionLocal() as db:
        after = (await db.execute(
            select(func.count()).select_from(MatchDurationSample))).scalar_one()
    logger.info("done: %d requests, %d new samples (%d -> %d)",
                requests, after - before, before, after)


if __name__ == "__main__":
    asyncio.run(main())
