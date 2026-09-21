"""WHAT MUST BE TRUE OF A DRAW, AND OF THE WEEK IT SITS IN.

THE BUGS THIS EXISTS FOR DID NOT RAISE. Every draw-lifecycle fault the owner
reported in the week of 2026-09-21 was an IMPOSSIBLE STATE THAT NOTHING
ASSERTED WAS IMPOSSIBLE — no exception, no log line, nothing for the self-heal
watcher to hash:

  * "Why does it say SP Open ends Sept 20 if the final is scheduled for 3pm on
    the 21st?"  end_date was read off a Wikipedia infobox before the weather
    moved the final. Nothing compared it to the play we can see.
  * "Why is Guadalajara still showing as Active?"  Its own last match had been
    over for two days.
  * "ATP Hong Kong open is showing active as an atp draw with January dates.
    WTF is going on???"  One tournament row held January's ATP 250 and
    November's WTA 250, so the two moved between buckets together.
  * China Open's ATP 500 given a TWELVE-DAY main draw, because the infobox
    names a range per tour and the parser knew only "(men)"/"(women)".
  * "Several players are still missing their inferred draw rank."  Entries with
    neither a seed nor a ranking cannot be placed by computeDrawRanks, so they
    render no badge at all.

In every case the machine was content and the OWNER was the detector. That is
the thing this module changes: it states each condition as a fault, logs it
where `alerts.py` and the self-heal watcher already look, and lets the repair
machinery that exists do the rest.

WHY THE CHECKS RE-DERIVE FROM RAW FIELDS. `_check_draw_health` already
established the rule and it is worth restating: a check that asks
`computed_status` what it thinks can never catch a bug in `computed_status`.
So nothing below consults that property, or any other derived view. Every
judgement is made from stored columns and from observed play.

WHY OBSERVED PLAY OUTRANKS THE CALENDAR. A scraped date is a claim about the
future; a match on a court is a fact. Where the two disagree the calendar is
what is wrong — `adopt_scheduled_end_date` already encodes this for the repair
path, and `end_date_behind_play` below is the same principle as a check, which
matters because the repair only runs where an order of play was ingested and
most 250s never publish one we parse.

A CHECK NEVER WRITES. Same law as schedule_invariants: violations are
returned, and `check_and_log` is the only thing that touches the log. Repairs
belong to the sweep that owns them.
"""
import logging
from datetime import date
from typing import Optional

from sqlalchemy import select

from app.models.schedule import ScheduleEntry
from app.models.tournament import Draw, DrawEntry, Match, Tournament
from app.services.events import SAME_EVENT_DAYS, split_plan

logger = logging.getLogger(__name__)

# How long a main draw of each category may run, in days from start_date to
# end_date inclusive-of-neither (so a Monday-to-Sunday week is 6).
#
# DERIVED FROM THE 111 DRAWS IN PRODUCTION on 2026-09-21, not invented, then
# widened by a day at each end so an unusual-but-real calendar does not cry
# wolf. Observed spans were: ATP 250 5..7, ATP 500 5..6, ATP 1000 6..11,
# WTA 250 5..6, WTA 500 5..7, WTA 1000 5..11, Grand Slam 7..14. The 1000s
# legitimately take two shapes — a one-week 7 and a mandatory-combined 11 —
# so their envelope is wide, and that is the honest limit of this check: it
# catches a 500 wearing a 1000's dates (China Open, 2026-09-21) and any date
# pair that is simply nonsense, but it cannot catch a 1000 handed another
# 1000's range.
CATEGORY_SPAN_DAYS = {
    "ATP 250": (4, 8),
    "ATP 500": (4, 8),
    "ATP 1000": (5, 12),
    "WTA 250": (4, 8),
    "WTA 500": (4, 8),
    "WTA 1000": (4, 12),
    "Grand Slam": (6, 15),
}
# Nothing in tennis runs longer than a Slam. The backstop for a category we
# have never seen, or a NULL one.
ABSOLUTE_MAX_SPAN_DAYS = 15

# How long after its last day a draw may still be unfinished. The status column
# is written by the scrapers, and a draw whose final is done stops being active
# the moment the result lands — but a result can arrive late, and a rain-delayed
# final legitimately pushes play past end_date (which is what
# `end_date_behind_play` is for, and what adopt_scheduled_end_date repairs).
# Two days is past both.
UNFINISHED_GRACE_DAYS = 2


# ── the law, as pure predicates ───────────────────────────────────────────
# Each takes plain values so it can be tested without a database, and each
# returns a reason string (the violation's detail) or None for "lawful".

def end_date_behind_play(end_date: Optional[date],
                         last_play_day: Optional[date]) -> Optional[str]:
    """Play falls after the day the calendar says the draw ended.

    SP Open, 2026-09-21: end_date said the 20th while the final was on court
    on the 21st, so the draw retired itself with its final unplayed and left
    the owner's picks looking settled.
    """
    if end_date is None or last_play_day is None:
        return None
    if last_play_day > end_date:
        return (f"play on {last_play_day} is after end_date {end_date} "
                f"({(last_play_day - end_date).days}d)")
    return None


def dates_out_of_order(start_date: Optional[date],
                       end_date: Optional[date]) -> Optional[str]:
    """A draw cannot end before it starts."""
    if start_date is None or end_date is None:
        return None
    if end_date < start_date:
        return f"end_date {end_date} precedes start_date {start_date}"
    return None


def duration_outside_envelope(category: Optional[str],
                              start_date: Optional[date],
                              end_date: Optional[date]) -> Optional[str]:
    """A main draw running far longer or shorter than its category ever does.

    China Open, 2026-09-21: the infobox reads "30 September – 11 October (WTA)
    <br> 30 September – 6 October (ATP)" and the parser knew only the words
    "(men)" and "(women)", so the ATP 500 took the WTA 1000's end date and
    became a twelve-day event. A wrong end_date is not a cosmetic fault — it
    decides which bucket the draw sits in and when picks lock.
    """
    if start_date is None or end_date is None:
        return None
    span = (end_date - start_date).days
    if span < 0:
        return None                      # dates_out_of_order owns this
    lo, hi = CATEGORY_SPAN_DAYS.get(category or "", (0, ABSOLUTE_MAX_SPAN_DAYS))
    if span < lo or span > hi:
        return (f"{category or 'uncategorised'} running {span}d "
                f"({start_date}..{end_date}), outside {lo}..{hi}")
    return None


def not_completed_after_its_end(status: Optional[str], end_date: Optional[date],
                                today: date) -> Optional[str]:
    """Its last day has passed and the scrapers never finished it.

    THIS IS THE ONE WORTH MEASURING, because of what computed_status does when
    the stored status is anything but `completed`. Walked against the real
    property on 2026-09-21, for an ordinary 6-day week whose final is on day
    +6:

        status 'completed' on time    active day +0..+6, completed from +7
        status left at 'active'       active day +1..+14, completed from +15
        status left at 'upcoming'     active day +1..+14, completed from +15

    The fallback that retires a draw nobody updated is `(today - start_date) >
    14 days`, which owes nothing to end_date — so a scrape that dies after the
    semi-finals leaves EIGHT DAYS of a tournament reading Active with its final
    already played. Nothing logs a scrape that simply stopped, so nothing has
    ever reported this; the owner reporting a draw "still showing as Active" is
    the only detector there has been.

    Generalised from an earlier `stale_active`, which asked only about
    status == 'active' and so missed the identical fault in a draw the scrapers
    left at 'upcoming' or 'open' — the same eight phantom days, from a status
    that looks harmless in the column.
    """
    if status == "completed" or end_date is None:
        return None
    late = (today - end_date).days
    if late > UNFINISHED_GRACE_DAYS:
        return (f"status {status!r} {late}d after end_date {end_date} — "
                f"computed_status reads 'active' until "
                f"14 days past start_date")
    return None


def completed_with_unplayed_final(status: Optional[str],
                                  final_has_winner: Optional[bool]) -> Optional[str]:
    """Retired with its last match undecided.

    The shape every stale-date bug ends in, and the one the owner sees: the
    draw leaves Active, the standings settle, and the final never happened.
    """
    if status != "completed" or final_has_winner is None:
        return None
    if not final_has_winner:
        return "status 'completed' but the final has no winner"
    return None


def row_holds_two_events(draws: list) -> Optional[str]:
    """One tournament row holding tournaments played weeks apart.

    Four rows did on 2026-09-21 — Hong Kong, Hamburg, Stuttgart and Japan
    Open, each an ATP event and a WTA event sharing a city's name in one year
    — because the migration that created the table grouped on name and year
    alone. Everything keyed on tournament_id trusts that a row is one event,
    so January's Hong Kong reappeared under ACTIVE in September. Split by
    migrate_split_conflated_events.py; this is the guard against it returning,
    and against `events.attach` ever placing a draw in the wrong row.
    """
    groups = split_plan(draws)
    if len(groups) < 2:
        return None
    spans = "; ".join(
        f"[{', '.join(str(d.id) for d in g)}] from {min(x.start_date for x in g if x.start_date)}"
        for g in groups if any(x.start_date for x in g))
    return (f"{len(groups)} events more than {SAME_EVENT_DAYS}d apart in one "
            f"row: {spans}")


def entries_without_draw_rank(entries: list) -> Optional[str]:
    """A released draw holding players who can be given no rank at all.

    The badge on a player's pill is their rank WITHIN the draw: seeds keep
    their seed number and everyone else is ordered by world ranking. An entry
    with neither shows nothing, which is what the owner kept reporting — and
    it self-heals only if something notices, which until now nothing did.

    Byes and empty slots are not players and are not counted.
    """
    nameless = {"", "bye", "bye/"}
    blank = [e for e in entries
             if (e.name or "").strip().lower() not in nameless
             and e.seed is None and e.ranking is None]
    if not blank:
        return None
    shown = ", ".join(sorted((e.name or "?") for e in blank)[:6])
    return (f"{len(blank)} entr{'y' if len(blank) == 1 else 'ies'} with neither "
            f"seed nor ranking: {shown}" + (" …" if len(blank) > 6 else ""))


# ── the repair ────────────────────────────────────────────────────────────
# A FIX, NOT A CHECK, and it runs before the checks so they see the healed
# state. Same division as schedule_invariants: where the answer is already in
# the database and the derivation is deterministic, routing it through a logged
# fault and the self-heal watcher is ceremony.

# A finished bracket for an event supposedly this far off means the stored
# dates point at the wrong EDITION — December/January season openers were once
# stamped a year forward. The repair refuses to act on that contradiction and
# leaves it to the checks, because stamping it completed would retire a draw
# that has not been played. Mirrors the guard in routers/tournaments.py.
WRONG_EDITION_DAYS = 30


def finish_decision(status: Optional[str], num_rounds: Optional[int],
                    final_matches: list, start_date: Optional[date],
                    today: date) -> Optional[str]:
    """Whether the bracket itself says this draw is over. Pure.

    `final_matches` is every Match at round_number == num_rounds, as objects
    carrying `winner_id` and `is_bye`.

    WHY THIS EXISTS WHEN THE SCRAPER ALREADY DOES IT. routers/tournaments.py
    sets status='completed' on `parsed.has_final_winner` — read off a freshly
    scraped Wikipedia page. That fires only when a scrape RUNS and SUCCEEDS,
    so a scrape that dies after the semi-finals, or a draw that has dropped
    out of the refresh set, never gets the stamp; computed_status then reports
    'active' until 14 days past start_date, which for a 6-day week is eight
    days of a finished tournament showing as live. The bracket in our own
    `matches` table is written by the authoritative result sources and is
    always there to be read, so it answers the same question without needing
    anybody to scrape anything.
    """
    if status == "completed":
        return None
    if not num_rounds or not final_matches:
        return None
    # A final is one match and cannot be a bye. Anything else is a bracket
    # this repair does not understand, and guessing at it is how a draw gets
    # retired unplayed.
    real = [m for m in final_matches if not m.is_bye]
    if len(real) != 1:
        return None
    if real[0].winner_id is None:
        return None
    if start_date and (start_date - today).days > WRONG_EDITION_DAYS:
        return None                 # wrong edition; the checks own this
    return f"the final is decided (match {real[0].id}) but status is {status!r}"


async def finish_decided_draws(db) -> list:
    """Stamp every draw whose own final has a winner. Returns what changed.

    The completion NOTIFICATION that follows is already guarded: the job that
    fires it takes only draws whose end_date is within three days, precisely
    so a draw resurrected long after the fact does not mail its standings out
    as news. So a recent draw gets the completion mail it should have had, and
    an old one is repaired silently.
    """
    today = date.today()
    draws = (await db.execute(
        select(Draw).where(Draw.status != "completed"))).scalars().all()
    if not draws:
        return []
    finals = (await db.execute(
        select(Match).where(Match.draw_id.in_([d.id for d in draws])))).scalars().all()
    by_draw: dict = {}
    for m in finals:
        by_draw.setdefault(m.draw_id, []).append(m)

    changed = []
    for d in draws:
        at_final = [m for m in by_draw.get(d.id, []) if m.round_number == d.num_rounds]
        why = finish_decision(d.status, d.num_rounds, at_final, d.start_date, today)
        if why:
            d.status = "completed"
            changed.append({"draw_id": d.id,
                            "draw": f"{d.year} {d.name} ({d.gender})", "detail": why})
    return changed


# ── the law applied to the database ───────────────────────────────────────

async def _last_play_day(db, draw_ids: list) -> dict:
    """The latest day each draw has main-draw play on, scheduled or played.

    From the order of play, which is the only place that knows a final moved.
    Qualifying is excluded: it runs before start_date and would make every
    draw look as though it began early.
    """
    if not draw_ids:
        return {}
    rows = (await db.execute(
        select(ScheduleEntry.draw_id, ScheduleEntry.play_date)
        .where(ScheduleEntry.draw_id.in_(draw_ids),
               ScheduleEntry.stage == "main",
               ScheduleEntry.play_date.isnot(None)))).all()
    out: dict = {}
    for did, day in rows:
        if did is not None and (did not in out or day > out[did]):
            out[did] = day
    return out


async def _final_has_winner(db, draws: list) -> dict:
    """Whether each draw's last round holds a decided match.

    Keyed on num_rounds rather than "the highest round present", so a bracket
    that was never fully built reads as undecided instead of quietly calling
    its semi-final the final.
    """
    ids = [d.id for d in draws if d.num_rounds]
    if not ids:
        return {}
    by_id = {d.id: d for d in draws}
    rows = (await db.execute(
        select(Match.draw_id, Match.round_number, Match.winner_id)
        .where(Match.draw_id.in_(ids)))).all()
    seen: dict = {}
    for did, rnd, winner in rows:
        if rnd == by_id[did].num_rounds:
            seen[did] = seen.get(did, False) or winner is not None
    return seen


async def check(db, *, today: Optional[date] = None) -> list[dict]:
    """Every draw-lifecycle violation there is right now. Empty list = lawful.

    Reads only. Scoped to draws that are current or recent — a finished
    January event cannot newly break, and reporting on the whole season every
    hour would bury the one line that matters. The structural check on
    tournament rows is deliberately NOT scoped that way: a row conflating two
    events is wrong all year, and the November half is how you find it.
    """
    today = today or date.today()
    v: list[dict] = []

    draws = (await db.execute(select(Draw))).scalars().all()
    by_row: dict = {}
    for d in draws:
        if d.tournament_id is not None:
            by_row.setdefault(d.tournament_id, []).append(d)

    # A draw is worth checking while it can still change what the site shows:
    # anything not finished, plus anything whose last day is within a
    # fortnight (a rain-delayed final and a late result both land in there).
    def current(d) -> bool:
        if d.status != "completed":
            return True
        return d.end_date is not None and (today - d.end_date).days <= 14

    watched = [d for d in draws if current(d)]
    last_play = await _last_play_day(db, [d.id for d in watched])
    finals = await _final_has_winner(db, watched)

    entries_by_draw: dict = {}
    released = [d.id for d in watched if d.draw_released_direct_at is not None]
    if released:
        for e in (await db.execute(
                select(DrawEntry).where(DrawEntry.draw_id.in_(released)))).scalars():
            entries_by_draw.setdefault(e.draw_id, []).append(e)

    def add(draw, code, detail):
        if detail:
            v.append({"code": code, "draw_id": draw.id,
                      "draw": f"{draw.year} {draw.name} ({draw.gender})",
                      "detail": detail})

    for d in watched:
        add(d, "dates_out_of_order", dates_out_of_order(d.start_date, d.end_date))
        add(d, "end_date_behind_play",
            end_date_behind_play(d.end_date, last_play.get(d.id)))
        add(d, "duration_outside_envelope",
            duration_outside_envelope(d.category, d.start_date, d.end_date))
        add(d, "not_completed_after_its_end",
            not_completed_after_its_end(d.status, d.end_date, today))
        add(d, "completed_with_unplayed_final",
            completed_with_unplayed_final(d.status, finals.get(d.id)))
        if d.id in entries_by_draw:
            add(d, "entry_without_draw_rank",
                entries_without_draw_rank(entries_by_draw[d.id]))

    # One row, one event — checked across the whole season, see docstring.
    for tid, row_draws in sorted(by_row.items()):
        detail = row_holds_two_events(row_draws)
        if detail:
            t = await db.get(Tournament, tid)
            v.append({"code": "row_holds_two_events", "tournament_id": tid,
                      "draw": f"t{tid} {t.name if t else '?'}",
                      "detail": detail})
    return v


async def check_and_log(db, *, today: Optional[date] = None) -> list[dict]:
    """Run the law and put violations where the watcher reads.

    One log line per CODE rather than per draw: a parser change that moves
    twenty end dates is one fault to fix, and twenty alerts would cost the
    self-heal watcher twenty triage passes on the same bug.
    """
    from app.services.system_log import app_log

    violations = await check(db, today=today)
    for code in dict.fromkeys(x["code"] for x in violations):
        hits = [x for x in violations if x["code"] == code]
        await app_log(
            "error", "draws",
            f"{len(hits)} draw invariant violation(s) — {code}: "
            + "; ".join(f"{x['draw']} {x['detail']}" for x in hits[:3])
            + (" …" if len(hits) > 3 else ""),
            {"code": code, "count": len(hits), "violations": hits[:20]},
            dedup_key=f"draw_invariant_{code}", dedup_hours=6)
    return violations


if __name__ == "__main__":  # pragma: no cover
    # `python -m app.services.draw_invariants` — the dry run. Prints every
    # violation and writes nothing, including no log rows.
    import asyncio
    import json as _json

    async def _main():
        from app.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            # What the repair WOULD do. Never committed from here: this entry
            # point is the dry run, and it is expected to be pointed at
            # production.
            pending = await finish_decided_draws(db)
            await db.rollback()
            for x in pending:
                print(f"REPAIR  {x['draw']}: {x['detail']}")
            if pending:
                print()
            violations = await check(db)
        by_code: dict = {}
        for x in violations:
            by_code.setdefault(x["code"], []).append(x)
        for code, hits in sorted(by_code.items()):
            print(f"\n{code}  ({len(hits)})")
            for h in hits:
                print(f"    {h['draw']}: {h['detail']}")
        print(f"\n{len(violations)} violation(s), {len(by_code)} code(s)")
        print(_json.dumps({"total": len(violations),
                           "codes": {k: len(x) for k, x in by_code.items()}}))
        raise SystemExit(1 if violations else 0)

    asyncio.run(_main())
