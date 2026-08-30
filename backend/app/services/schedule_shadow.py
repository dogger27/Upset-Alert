"""Run the structured schedule sources beside the PDF and report the difference.

Nothing here writes a schedule row. The sheet stays authoritative while this
answers the only question worth answering before demoting it: on a real day, of
a real tournament, does the feed say the same thing?

Measured on staging before this existed — Monterrey 54/54 from the WTA's own
JSON, Winston-Salem 68/75 from Sofascore — but a fixture is not a season. This
runs the same comparison continuously, so the decision to switch is made on
days we watched rather than on two tournaments I happened to pick.

It also LEARNS the court names the WTA feed does not give. Tour events carry
CourtID (1, 2, 3) where the sheet says ESTADIO or GRANDSTAND; every day both
sources describe teaches the mapping by majority, and the winner is kept in
app_settings so the feed can eventually stand alone.
"""

import logging
from collections import Counter, defaultdict
from datetime import date
from typing import Optional

from sqlalchemy import select

from app.models.schedule import ScheduleEntry, ScheduleEntryPlayer
from app.services.schedule import _fold
from app.services.system_log import app_log

logger = logging.getLogger(__name__)

COURTS_SETTING = "sofa_courts"          # + ":{tournament_id}"


def _sig(names: list) -> frozenset:
    """One match's identity: the folded name tokens of everyone in it.

    Tokens rather than a surname, because the two sides of this comparison
    disagree about which token IS the surname — a sheet prints
    "Diane PARRY FRA", the WTA feed "Diane Parry", Sofascore "Bhambri Y". The
    union survives all three, and two different matches sharing a whole name
    set on one day does not happen.
    """
    out = set()
    for n in names:
        out |= _fold(n)
    return frozenset(out)


async def _stored(db, tournament_id: int, day: date) -> list[dict]:
    rows = (await db.execute(
        select(ScheduleEntry.id, ScheduleEntry.court, ScheduleEntry.discipline)
        .where(ScheduleEntry.tournament_id == tournament_id,
               ScheduleEntry.play_date == day))).all()
    if not rows:
        return []
    ids = [r[0] for r in rows]
    players = defaultdict(list)
    for eid, raw in (await db.execute(
            select(ScheduleEntryPlayer.schedule_entry_id,
                   ScheduleEntryPlayer.raw_name)
            .where(ScheduleEntryPlayer.schedule_entry_id.in_(ids)))).all():
        players[eid].append(raw)
    return [{"court": r[1], "discipline": r[2], "sig": _sig(players[r[0]])}
            for r in rows]


async def _structured(db, tournament, draws, day: date):
    """(matches, source) from whichever feed covers this tournament, or None.

    The WTA publishes its own schedule and is preferred for its draws; the ATP
    publishes none, so its draws go to Sofascore. A tournament with both (a
    combined event) is compared on whichever it can answer for — the sheet
    carries both tours in one document, so a partial comparison is expected
    and is reported as such rather than counted as a miss.
    """
    from app.services import sofa_schedule, wta_feed

    tz = next((d.venue_timezone for d in draws if d.venue_timezone), None)
    out, sources = [], []

    wta = [d for d in draws if (d.gender or "").upper() == "F"]
    if wta:
        event_id = next(
            (wta_feed.event_id_from_pdf_url(d.oop_url) for d in wta
             if wta_feed.event_id_from_pdf_url(d.oop_url)), None)
        if event_id:
            try:
                rows = await __import__("asyncio").to_thread(
                    wta_feed.fetch_matches, event_id, day.year)
                doc = wta_feed.normalize_day(rows, day, tz)
                ms, _meta = wta_feed.parse_wta_day(doc, venue_tz=tz)
                out += ms
                sources.append(f"wta:{event_id}")
            except Exception as exc:      # noqa: BLE001 — shadow must not break the tick
                logger.info("shadow: WTA feed unavailable for %s: %s",
                            tournament.name, exc)

    atp = [d for d in draws if (d.gender or "").upper() == "M"]
    for d in atp:
        for tid, sid, disc in ((d.sofa_tournament_id, d.sofa_season_id, "singles"),
                               (d.sofa_doubles_tournament_id,
                                d.sofa_doubles_season_id, "doubles")):
            if not tid or not sid:
                continue
            try:
                evs = await sofa_schedule.fetch_events(tid, sid, "next", pages=2)
                evs += await sofa_schedule.fetch_events(tid, sid, "last", pages=2)
                ms, _meta = sofa_schedule.parse_sofa_day(
                    sofa_schedule.normalize_day(evs, day, tz),
                    venue_tz=tz, discipline=disc)
                out += ms
                sources.append(f"sofa:{tid}")
            except Exception as exc:      # noqa: BLE001
                logger.info("shadow: Sofascore unavailable for %s: %s",
                            tournament.name, exc)
    return out, ",".join(sources)


async def compare_day(db, tournament, draws, day: date) -> Optional[dict]:
    """What the feeds say against what the sheet stored. Writes nothing."""
    stored = await _stored(db, tournament.id, day)
    if not stored:
        return None
    feed, source = await _structured(db, tournament, draws, day)
    if not source:
        return None

    fsig = Counter(_sig(m.side_a + m.side_b) for m in feed)
    ssig = Counter(r["sig"] for r in stored)
    matched = sum((fsig & ssig).values())

    # Court names, learned only where both sources describe the same match.
    votes = defaultdict(Counter)
    by_sig = {r["sig"]: r for r in stored}
    for m in feed:
        row = by_sig.get(_sig(m.side_a + m.side_b))
        if row and m.court and row["court"]:
            votes[m.court][row["court"]] += 1

    return {
        "tournament": tournament.name, "day": day.isoformat(), "source": source,
        "sheet": len(stored), "feed": len(feed), "matched": matched,
        "sheet_only": sum((ssig - fsig).values()),
        "feed_only": sum((fsig - ssig).values()),
        "court_votes": {k: dict(v) for k, v in votes.items()},
    }


async def learn_courts(db, tournament_id: int, votes: dict) -> dict:
    """Fold today's votes into the stored mapping and return the winners.

    Majority, not last-write: a match MOVED court after the sheet was published
    disagrees honestly with it, and Monterrey had two of those in eight days.
    One outlier must not rename a court.
    """
    import json
    from app.services import settings as st

    key = f"{COURTS_SETTING}:{tournament_id}"
    stored = {}
    raw = await st.get_setting(db, key)
    if raw:
        try:
            stored = json.loads(raw)
        except ValueError:
            stored = {}
    for feed_court, names in votes.items():
        tally = Counter(stored.get(feed_court, {}))
        tally.update(names)
        stored[feed_court] = dict(tally)
    await st.set_setting(db, key, json.dumps(stored, sort_keys=True))
    return {c: Counter(t).most_common(1)[0][0] for c, t in stored.items() if t}


async def court_names(db, tournament_id: int) -> dict:
    """The learned CourtID -> sheet name mapping, for the feed to render with."""
    import json
    from app.services import settings as st
    raw = await st.get_setting(db, f"{COURTS_SETTING}:{tournament_id}")
    if not raw:
        return {}
    try:
        tally = json.loads(raw)
    except ValueError:
        return {}
    return {c: Counter(t).most_common(1)[0][0] for c, t in tally.items() if t}


async def run_shadow(db, tournament, draws, day: date) -> Optional[dict]:
    """Compare, learn, and record one line. Never raises into the caller."""
    try:
        report = await compare_day(db, tournament, draws, day)
    except Exception as exc:              # noqa: BLE001
        logger.warning("shadow comparison failed for %s: %s", tournament.name, exc)
        return None
    if not report:
        return None
    if report["court_votes"]:
        await learn_courts(db, tournament.id, report["court_votes"])
    agree = report["matched"] / report["sheet"] if report["sheet"] else 0
    await app_log(
        "info", "schedule_shadow",
        f"{tournament.name} {report['day']}: feed matched "
        f"{report['matched']}/{report['sheet']} of the sheet",
        detail=report,
        dedup_key=f"shadow_{tournament.id}_{report['day']}", dedup_hours=6)
    return report | {"agreement": round(agree, 3)}
