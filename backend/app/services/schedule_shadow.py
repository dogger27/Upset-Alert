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
WTA_EVENT_SETTING = "wta_event"         # + ":{tournament_id}"


async def wta_event_id(db, tournament_id: int, draws) -> Optional[int]:
    """The WTA's id for this event, remembered rather than re-derived.

    It lives in the PDF URL — .../draws/2026/1039/OP.pdf — which is the whole
    reason no mapping table is needed. But that URL is NOT durable: it holds
    only the current sheet and goes null overnight and again when the
    tournament ends, so a completed event has nothing left to read the id from.
    On a combined event it is stranded on whichever draw last had a sheet,
    which is how Cincinnati ended up with the wtafiles id on its MEN'S row.

    So: take it from any draw that has it, whatever the gender, and write it
    down the first time it is seen.
    """
    from app.services import settings as st
    from app.services import wta_feed

    key = f"{WTA_EVENT_SETTING}:{tournament_id}"
    stored = await st.get_setting(db, key)
    if stored:
        try:
            return int(stored)
        except ValueError:
            pass
    for d in draws:
        found = wta_feed.event_id_from_pdf_url(getattr(d, "oop_url", None))
        if found:
            await st.set_setting(db, key, str(found))
            return found
    return None


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


def _pair(stored: list, feed: list):
    """Pair sheet rows with feed rows by how much of the name they share.

    NOT set equality, which was the first attempt and measured the wrong thing:
    "J.J. WOLF" against the feed's rendering, or a hyphenated given name split
    differently, counted as a missing match when both sources plainly had it.
    Two matches on the same day never share two surnames, so an overlap of two
    distinctive tokens identifies the pair while a single shared common name
    ("Maria") does not.

    Greedy by best overlap, and each row is consumed once, so a near-duplicate
    cannot absorb two sheet rows.
    """
    feed_sigs = [(m, _sig(m.side_a + m.side_b)) for m in feed]
    taken, pairs = set(), []
    for row in stored:
        best, best_score = None, 0
        for i, (m, fs) in enumerate(feed_sigs):
            if i in taken:
                continue
            # Initials and one-letter fragments say little; distinctive tokens
            # are what identify a person across three renderings of their name.
            shared = {t for t in (row["sig"] & fs) if len(t) >= 3}
            if len(shared) > best_score:
                best, best_score = i, len(shared)
        if best is not None and best_score >= 2:
            taken.add(best)
            pairs.append((row, feed_sigs[best][0]))
    matched_rows = {id(r) for r, _ in pairs}
    return (pairs,
            [r for r in stored if id(r) not in matched_rows],
            [m for i, (m, _f) in enumerate(feed_sigs) if i not in taken])


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

    # THE WTA'S OWN FEED FIRST, where the draw came from a wtafiles PDF — that
    # URL is where the event id lives. A Slam's WTA draw has no such URL (the
    # US Open's points at usopen.org), so it falls through to Sofascore below
    # rather than being skipped: comparing only the men's half of a combined
    # event against a sheet carrying both reads as 50% disagreement and means
    # nothing.
    seen_events = set()
    event_id = await wta_event_id(db, tournament.id, draws)
    for d in [x for x in draws if (x.gender or "").upper() == "F"]:
        if not event_id:
            continue
        try:
            rows = await __import__("asyncio").to_thread(
                wta_feed.fetch_matches, event_id, day.year)
            doc = wta_feed.normalize_day(rows, day, tz)
            ms, _meta = wta_feed.parse_wta_day(doc, venue_tz=tz)
            out += ms
            sources.append(f"wta:{event_id}")
        except Exception as exc:          # noqa: BLE001 — shadow must not break the tick
            logger.info("shadow: WTA feed unavailable for %s: %s",
                        tournament.name, exc)

    # MIXED DOUBLES IS A THIRD EVENT, and its ids were already stored on the
    # tournament — the shadow simply never asked for them, so the 12 mixed
    # matches the US Open played during fan week counted as sheet-only.
    mixed = [(getattr(tournament, "sofa_mixed_tournament_id", None),
              getattr(tournament, "sofa_mixed_season_id", None), "mixed")]

    # EVERY source, not the first that answers. Treating the WTA feed as
    # exclusive for its draws made three perfect days worse: Sofascore stopped
    # being asked for those draws and covered more of them than the WTA API
    # did. The matcher consumes each feed row once, so offering the same match
    # twice cannot double-count it — it can only give the sheet row something
    # to pair with. `feed` therefore counts rows OFFERED, not distinct matches.
    for d in draws:
        for tid, sid, disc in ((d.sofa_tournament_id, d.sofa_season_id, "singles"),
                               (d.sofa_doubles_tournament_id,
                                d.sofa_doubles_season_id, "doubles"),
                               *mixed):
            if not tid or not sid or (tid, sid) in seen_events:
                continue
            seen_events.add((tid, sid))
            try:
                # DEEP ENOUGH TO REACH QUALIFYING. Sofascore keeps it under the
                # same tournament id, not a separate one as first assumed — it
                # simply sits further back than a page or two of history, since
                # it is played before the main draw. Two pages stopped at the
                # main draw and reported every qualifying day as 0 matched.
                evs = await sofa_schedule.fetch_events(tid, sid, "next", pages=4)
                evs += await sofa_schedule.fetch_events(tid, sid, "last", pages=8)
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

    pairs, unmatched_sheet, unmatched_feed = _pair(stored, feed)
    matched = len(pairs)

    # Court names, learned only where both sources describe the same match.
    votes = defaultdict(Counter)
    for row, m in pairs:
        if m.court and row["court"]:
            votes[m.court][row["court"]] += 1

    return {
        "tournament": tournament.name, "day": day.isoformat(), "source": source,
        "sheet": len(stored), "feed": len(feed), "matched": matched,
        "sheet_only": len(unmatched_sheet),
        "feed_only": len(unmatched_feed),
        "sheet_only_names": [sorted(r["sig"])[:6] for r in unmatched_sheet[:4]],
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
