"""
Background scheduler:
- Auto-discovers and adds tournaments daily for current + next 2 years
- Real-time EventStreams listener for tournament draw page updates
- Dynamic subscriptions: subscribes on tournament add, unsubscribes on completion
"""

import asyncio
import logging
import traceback
from datetime import date, datetime, timedelta, timezone

import httpx

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import case, func, select

from app.database import AsyncSessionLocal
from app.models.tournament import Draw, Match
from app.services.espn_monitor import ESPNMonitor
from app.services.eventstream import EventStreamListener

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()
eventstream = EventStreamListener()
espn_monitor = ESPNMonitor()


async def _auto_discover_tournaments() -> None:
    logger.info("=== Starting tournament auto-discovery ===")
    from app.services.tournament_sync import sync_season

    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        current_year = now.year

        for year in [current_year, current_year + 1]:
            logger.info("Discovering tournaments for %d...", year)
            try:
                summary = await sync_season(db, year, scrape_new=True)
                logger.info("✓ Sync complete for %d: %s", year, summary)
            except Exception as exc:
                await db.rollback()
                logger.warning("Failed to sync tournaments for %d: %s", year, exc)
                # "Page not found" for a future year is expected — Wikipedia page won't
                # exist until the season is underway. Skip app_log entirely.
                is_future_not_found = year > current_year and "Page not found" in str(exc)
                if not is_future_not_found:
                    from app.services.system_log import app_log
                    await app_log("error", "scheduler", f"Tournament discovery failed for {year}: {exc}",
                                  {"year": year, "error": str(exc)})

    # Sync EventStream subscriptions after DB is updated
    await _sync_subscriptions()


# How far ahead of a draw's expected release date to start polling for it.
# Kept modest because this job runs every 30 minutes and the Wikipedia response
# cache expires just under that (25 min), so each extra day of lead is real
# request volume, not cache hits. EventStreams handles real-time detection; this
# is the backstop, and 3 days is enough headroom for the estimate to be wrong in
# the safe direction without widening the sweep much.
POLL_LEAD_DAYS = 3


async def _refresh_active_tournaments(force_refresh: bool = False) -> None:
    """
    Catch-up scrape (every 30 min — see start_scheduler) covering two groups:

    1. Active tournaments — start_date within the last 14 days, not yet completed.
       Catches match results / tournament completion that EventStreams may have missed.

    2. Upcoming tournaments awaiting draw release — expected DA or Qual date is
       within POLL_LEAD_DAYS but the draw hasn't been confirmed yet (no
       draw_released_*_at). This is what sets the checkmarks when players are
       placed in the draw.

    The lead time on group 2/3 matters more than it looks. Polling exactly from
    the expected date made the estimate self-confirming: a draw predicted for
    start-minus-one was not looked at until the day before play, so a draw that
    had been up for three days was recorded as "released one day before start",
    which fed the median that produced the next late prediction. Starting early
    lets the observation disagree with the estimate.
    """
    from sqlalchemy import or_
    from app.routers.tournaments import _do_scrape

    today = date.today()
    poll_from = today + timedelta(days=POLL_LEAD_DAYS)

    # Identify the work as plain tuples, not ORM instances. A scrape that fails
    # rolls its session back, and rollback expires every instance still attached
    # to it — so a Draw read before the loop would need a lazy reload afterwards,
    # which is sync IO inside the event loop (MissingGreenlet) and killed the rest
    # of the cycle. Tuples can't expire; the Draw is re-fetched below per draw.
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Draw.id, Draw.name, Draw.wiki_page_title).where(
                Draw.status != "completed",
                or_(
                    # Group 1: active window (started within last 14 days)
                    (
                        Draw.start_date.isnot(None) &
                        (Draw.start_date <= today) &
                        (Draw.start_date >= today - timedelta(days=14))
                    ),
                    # Group 2: upcoming — DA draw date is near, not yet confirmed
                    (
                        Draw.draw_release_direct.isnot(None) &
                        (Draw.draw_release_direct <= poll_from) &
                        Draw.draw_released_direct_at.is_(None)
                    ),
                    # Group 3: upcoming — Qual date is near, not yet confirmed
                    (
                        Draw.draw_release_qualifiers.isnot(None) &
                        (Draw.draw_release_qualifiers <= poll_from) &
                        Draw.draw_released_qualifiers_at.is_(None)
                    ),
                )
            )
        )
        tournaments = result.all()

    logger.info("Daily refresh: %d tournaments to check", len(tournaments))
    for t_id, t_name, t_wiki in tournaments:
        await asyncio.sleep(5)  # throttle Wikipedia requests to avoid 429s
        # One session per draw, so a failed scrape's rollback is contained to the
        # draw that caused it instead of poisoning every draw still to come.
        async with AsyncSessionLocal() as db:
            try:
                t = await db.get(Draw, t_id)
                if t is None:
                    continue  # deleted between the sweep and now
                prev_status = t.status

                await _do_scrape(t, db, force_refresh=force_refresh)
                await db.commit()
                logger.info("Refreshed %s %s (%s)", t.year, t_name, t.gender)

                # Prefetch H2H and DOB for any new matchups/players (uses own sessions)
                from app.services.h2h import prefetch_h2h_for_draw
                from app.services.rankings import prefetch_dob_for_draw
                await prefetch_h2h_for_draw(t_id)
                await prefetch_dob_for_draw(t_id)

                # "Draw released" email dispatch is centralized in
                # _notify_pending_draw_releases (runs on its own interval) so every
                # scrape path — this one, season-page edits, EventStreams, manual
                # admin refresh — is covered uniformly. Only tournament-complete is
                # fired directly here (it has its own completion_notified_at guard).
                from app.services.notifications import notify_tournament_complete
                just_completed = prev_status != "completed" and t.status == "completed"
                if just_completed:
                    asyncio.create_task(notify_tournament_complete(t_id))
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
                logger.debug("Network blip refreshing %s: %s", t_wiki, exc)
                await db.rollback()
            except Exception as exc:
                tb = traceback.format_exc()
                logger.warning("Failed to refresh %s: %s\n%s", t_wiki, exc, tb)
                await db.rollback()
                from app.services.system_log import app_log
                await app_log("error", "scheduler", f"Failed to refresh '{t_name}': {exc}",
                              {"tournament_id": t_id, "tournament_name": t_name,
                               "wiki_title": t_wiki, "error": str(exc),
                               "traceback": tb},
                              dedup_key=f"refresh_fail_{t_id}_{type(exc).__name__}", dedup_hours=1.0)


def _season_pages() -> set[str]:
    year = datetime.now(timezone.utc).year
    return {f"{year} ATP Tour", f"{year} WTA Tour"}


async def _on_season_page_edit(season_title: str) -> None:
    """
    Called whenever a season overview page (e.g. "2026 ATP Tour") is edited.

    The season page is authoritative for draw links: when a tournament's Singles
    page appears (or changes), it shows up as a new/corrected wiki_page_title here.
    We therefore:
      1. Correct any wiki_page_title that changed, clearing the stale wiki_page_id
         so the next scrape resolves it fresh.
      2. Immediately re-scrape every non-completed tournament that either had its
         title corrected OR hasn't had its draw confirmed yet and its expected draw
         date has already arrived — because the season-page edit is the signal that
         draw links are being added/updated.
    """
    import re
    from app.services.scraper import fetch_wikitext
    from app.services.discovery import parse_season_schedule
    from app.routers.tournaments import _do_scrape

    m = re.match(r'^(\d{4}) (ATP|WTA) Tour$', season_title)
    if not m:
        return
    year = int(m.group(1))
    gender = 'M' if m.group(2) == 'ATP' else 'F'

    try:
        wikitext, _ = await fetch_wikitext(season_title, force_refresh=True)
        discovered = parse_season_schedule(wikitext, year, gender)

        today = date.today()
        to_scrape: list[int] = []  # tournament IDs to scrape

        async with AsyncSessionLocal() as db:
            # Guessed titles need the same combined-event suffix adjustment
            # that discover_tournaments applies, or this handler would flap
            # titles back to the raw gendered guess on every season edit.
            # The other tour's base pages come from the DB here.
            from app.services.discovery import adjust_guessed_titles, title_bases
            other = await db.execute(
                select(Draw.wiki_page_title).where(
                    Draw.year == year,
                    Draw.gender == ("F" if gender == "M" else "M"),
                )
            )
            adjust_guessed_titles(discovered, title_bases(other.scalars().all()))
            disc_by_name = {d.name: d for d in discovered if d.wiki_page_title}

            result = await db.execute(
                select(Draw).where(
                    Draw.year == year,
                    Draw.gender == gender,
                    Draw.status != "completed",
                )
            )
            tournaments = result.scalars().all()

            title_updated = 0
            for t in tournaments:
                d = disc_by_name.get(t.name)
                # A guessed title may only correct an unresolved record;
                # explicit season-page links correct unconditionally.
                if (
                    d and d.wiki_page_title != t.wiki_page_title
                    and (not d.title_is_guess or t.wiki_page_id is None)
                ):
                    logger.info(
                        "Season page edit: correcting %s title %r → %r",
                        t.name, t.wiki_page_title, d.wiki_page_title,
                    )
                    t.wiki_page_title = d.wiki_page_title
                    t.wiki_page_id = None  # clear stale ID — scraper will resolve fresh
                    title_updated += 1
                    to_scrape.append(t.id)

                # Also immediately re-scrape any upcoming tournament whose expected
                # draw date has arrived but draw isn't confirmed yet — the season edit
                # is the signal that draw links are live on the season page.
                if (
                    t.id not in to_scrape
                    and t.draw_released_direct_at is None
                    and t.draw_release_direct is not None
                    and t.draw_release_direct <= today
                ):
                    to_scrape.append(t.id)

            if title_updated:
                await db.commit()
                logger.info(
                    "Season edit %s: corrected %d title(s), queued %d scrape(s)",
                    season_title, title_updated, len(to_scrape),
                )
            else:
                logger.info(
                    "Season edit %s: no title changes; queued %d pending-draw scrape(s)",
                    season_title, len(to_scrape),
                )

        # Scrape outside the session that did the title updates
        if to_scrape:
            async with AsyncSessionLocal() as db:
                for tid in to_scrape:
                    t = await db.get(Draw, tid)
                    if not t:
                        continue
                    try:
                        await asyncio.sleep(2)  # throttle Wikipedia requests
                        await _do_scrape(t, db, force_refresh=True)
                        await db.commit()
                        logger.info(
                            "Season-edit scrape: %s %s (draw now: %s)",
                            t.year, t.name, t.draw_released_direct_at,
                        )
                        # "Draw released" email dispatch is centralized in
                        # _notify_pending_draw_releases — see comment there.
                    except Exception as exc:
                        logger.warning(
                            "Season-edit scrape failed for %s: %s", t.wiki_page_title, exc,
                        )
                        await db.rollback()

        await _sync_subscriptions()
    except Exception as exc:
        logger.warning("Failed to handle season page edit %s: %s", season_title, exc)


async def _refresh_weekly_rankings() -> None:
    """
    Weekly rankings refresh (Sunday 6pm PDT).
    Scrapes TE for both genders if this week's data is missing.
    Errors are logged to system_logs; rankings may occasionally not be published
    this week (grand slam weeks, ATP/WTA schedule gaps).
    """
    from app.services.rankings import ensure_te_week
    from app.services.system_log import app_log

    today = date.today()
    week_date = today - timedelta(days=today.weekday())  # Monday anchor

    logger.info("Weekly rankings check: week %s", week_date)
    try:
        scraped_any = False
        async with AsyncSessionLocal() as db:
            for gender in ("M", "F"):
                scraped = await ensure_te_week(gender, week_date, db, log_errors=True)
                if scraped:
                    scraped_any = True
            if scraped_any:
                await db.commit()

        if scraped_any:
            logger.info("Weekly rankings: stored new data for week %s", week_date)
        else:
            logger.info("Weekly rankings: week %s already populated or not yet published", week_date)
    except Exception as exc:
        logger.error("Weekly rankings job failed: %s", exc)
        await app_log("error", "rankings", f"Weekly rankings job failed: {exc}",
                      {"week_date": str(week_date), "error": str(exc)},
                      dedup_key="weekly_rankings_job_fail", dedup_hours=12)


async def _refresh_elo() -> None:
    from app.services.rankings import refresh_elo_ratings
    await refresh_elo_ratings()


# How long a substantially-complete draw must stay stable (not reverted by a
# later scrape) before the "draw released" email fires. Wikipedia editors often
# place seeded players into their bracket slots as soon as the entry list is
# announced, well before Round-1 pairings are final — that state can briefly
# cross the "substantially complete" threshold and then get corrected within
# minutes. Waiting this long out lets any such flicker settle before emailing.
DRAW_RELEASE_NOTIFY_COOLDOWN = timedelta(minutes=10)

# A week's draws are announced together, so exactly one email covers the week.
# It waits for every draw in that week to be released — see the hold below.


async def _notify_pending_draw_releases() -> None:
    """
    Centralized, idempotent "draw released" email dispatch.

    Every code path that can set draw_released_direct_at (this scheduler's
    daily refresh, season-page-edit re-scrapes, the real-time EventStreams
    listener, and the manual admin "refresh draw" endpoint) funnels through
    _do_scrape, which stamps draw_release_detected_at the first time a draw is
    observed substantially complete. Rather than each of those call sites
    separately trying to detect "was this just released" (which is how a
    tournament like Swedish Open could be released via EventStreams and never
    get an email, since only two of the four paths had that check), this job
    periodically scans for draws that have been stable for the cooldown and
    haven't been notified yet — covering all paths uniformly, and only firing
    once the release has proven stable (fixing the Athens Open early-fire case).
    """
    now = datetime.now(timezone.utc)
    cutoff = now - DRAW_RELEASE_NOTIFY_COOLDOWN
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Draw).where(
                Draw.draw_released_direct_at.isnot(None),
                Draw.draw_release_notified_at.is_(None),
                Draw.draw_release_detected_at.isnot(None),
                Draw.draw_release_detected_at <= cutoff,
            )
        )
        ready = result.scalars().all()
        if not ready:
            return

        # Group by the tennis week the draws belong to. A draw with no week
        # (unparsed start date) can't be batched with anything, so it goes out
        # on its own rather than being held for a group it isn't part of.
        groups: dict[tuple, list[Draw]] = {}
        for t in ready:
            key = (t.year, t.week) if t.week is not None else ("solo", t.id)
            groups.setdefault(key, []).append(t)

        batches: list[tuple[list[int], bool]] = []
        for key, members in groups.items():
            if key[0] == "solo":
                batches.append(([members[0].id], False))
                continue

            year, week = key
            siblings = (await db.execute(
                select(Draw).where(Draw.year == year, Draw.week == week)
            )).scalars().all()

            ready_ids = {t.id for t in members}
            # Already-notified siblings mean this week's digest has gone out, so
            # Any sibling in the week that hasn't been emailed yet holds the
            # batch. A draw that is released but still inside its stability
            # cooldown counts as outstanding, not as absent — Canadian Open's
            # two draws were detected 93 minutes apart and the second was still
            # cooling down when the first was dispatched.
            outstanding = [
                s for s in siblings
                if s.id not in ready_ids and s.draw_release_notified_at is None
            ]

            # No escape hatches. There is exactly one draw-release email per
            # week and it waits for every draw in that week, however long that
            # takes — the lag cap and the pick-deadline guard that used to be
            # here could each release a partial batch, and a partial batch is
            # by definition a second email.
            if outstanding:
                logger.info(
                    "Draw-release digest for %s week %s held: %d ready, waiting on %s",
                    year, week, len(members), [s.name for s in outstanding],
                )
                continue
            batches.append(([t.id for t in members], False))

        if not batches:
            return

        for ids, _ in batches:
            for t in ready:
                if t.id in ids:
                    t.draw_release_notified_at = now
        await db.commit()

    from app.services.notifications import notify_draw_release_batch
    for ids, is_followup in batches:
        asyncio.create_task(notify_draw_release_batch(ids, is_followup=is_followup))
    logger.info("Draw-release notification: dispatched %d batch(es) covering %d draw(s)",
                len(batches), sum(len(ids) for ids, _ in batches))


async def _record_missed_completions() -> None:
    """
    Fire draw-completion for draws that finished without anything noticing.

    notify_tournament_complete is what persists final standings to draw history,
    and it runs from exactly two places: the periodic refresh, on a status flip,
    and espn_monitor. A final written by any other path — a Wikipedia edit
    arriving through EventStreams, an admin refresh, a page-load scrape — flips
    the draw to 'completed' inside _do_scrape without either of them seeing it.
    2026 Washington (M) finished that way: five predictors lost their draw
    history, and because the same gap leaves completion_notified_at null, which
    is what _record_completed_rounds keys on, it also dropped out of its week's
    digest.

    Scoped by end_date rather than by the stamp this is about to write: a draw
    that ended long ago and was never recorded stays that way. Resurrecting one
    would queue a Final round for an event that finished months ago and mail its
    standings out as news.
    """
    from app.services.notifications import notify_tournament_complete

    cutoff = datetime.now(timezone.utc).date() - timedelta(days=3)
    async with AsyncSessionLocal() as db:
        missed = (await db.execute(
            select(Draw.id, Draw.name, Draw.gender).where(
                Draw.status == "completed",
                Draw.completion_notified_at.is_(None),
                Draw.end_date.isnot(None),
                Draw.end_date >= cutoff,
            )
        )).all()

    # Outside the session above: notify_tournament_complete opens its own and
    # writes, and SQLite does not want a second writer under an open read.
    for draw_id, name, gender in missed:
        logger.info("Draw %d (%s %s) completed but was never recorded — firing completion",
                    draw_id, name, gender)
        # Idempotent: completion_notified_at plus a unique claim row, so a
        # redundant call here costs nothing.
        await notify_tournament_complete(draw_id)


async def _record_completed_rounds(db) -> None:
    """
    Find rounds that are finished but were never recorded, and record them.

    Detection used to live only in espn_monitor, firing in the same pass that
    wrote a result. That misses a round whose last winner arrives any other way
    — a Wikipedia scrape, an admin refresh, a backfill — and misses it
    permanently, because nothing ever looks again. Washington (M) and Memphis
    both finished R32 on 2026-07-29 and neither was ever queued.

    Sweeping here instead makes the digest depend on the state of the draw
    rather than on which code path happened to write the deciding result. The
    unique (draw, round) row still makes this idempotent.
    """
    from sqlalchemy.exc import IntegrityError
    from app.models.notification import RoundCompleteNotification

    draws = (await db.execute(
        select(Draw).where(Draw.status.in_(["active", "open"]))
    )).scalars().all()

    # A draw flips to 'completed' the moment its final ends, so the scan above
    # can never catch a round the event-driven path missed — the draw is already
    # out of scope by the time anything looks again. Recently-completed draws are
    # therefore swept too, and for EVERY round, not just the final: a digest
    # waits for every draw in its bucket without exception, so a single
    # unrecorded round on a finished draw would hold that bucket's email open
    # forever. Recording the round is the right way out of that wait — publishing
    # without the draw is not. The recency guard is what stops this queueing
    # rounds for events that finished weeks ago.
    draws += (await db.execute(
        select(Draw).where(
            Draw.status == "completed",
            Draw.completion_notified_at.isnot(None),
            Draw.completion_notified_at >= datetime.now(timezone.utc) - timedelta(days=3),
        )
    )).scalars().all()
    if not draws:
        return

    for d in draws:
        rows = (await db.execute(
            select(
                Match.round_number,
                func.count().label("total"),
                func.sum(case((Match.winner_id.is_(None), 1), else_=0)).label("open"),
            )
            .where(Match.draw_id == d.id, Match.is_bye == False)  # noqa: E712
            .group_by(Match.round_number)
        )).all()

        for round_number, total, still_open in rows:
            if total == 0 or still_open:
                continue
            already = await db.scalar(
                select(RoundCompleteNotification.id).where(
                    RoundCompleteNotification.draw_id == d.id,
                    RoundCompleteNotification.round_number == round_number,
                )
            )
            if already:
                continue
            try:
                async with db.begin_nested():
                    db.add(RoundCompleteNotification(
                        draw_id=d.id, round_number=round_number, recipient_count=0,
                    ))
                logger.info("Round %d of draw %d found complete — queued for digest",
                            round_number, d.id)
            except IntegrityError:
                pass  # recorded concurrently by espn_monitor
    await db.commit()


# Tiers that get their own digest instead of sharing the week's.
#
# A 1000 or a Slam runs 8-14 days, so bucketing it by start-week stalls every
# 250 and 500 that finished days earlier: the week-30 Final digest sat for days
# behind the Canadian Open, which merely *starts* in week 30 and doesn't finish
# until week 31. It also buried a Masters result among four 250s. A major's
# bucket is therefore the EVENT, which is equally what keeps the men's and
# women's draws of a combined event (Canadian Open, Indian Wells, every Slam) in
# one email instead of two.
MAJOR_DIGEST_TIERS = {"GS", "1000"}

# How far past a draw's own end date the digest will wait before treating the
# silence as a fault worth alerting on. It never shortens the wait — the batch
# still holds for the lagging draw — it only stops a stall being invisible.
DIGEST_STALL_DAYS = 3


def _digest_bucket(d: Draw) -> tuple:
    """Which digest a draw's completed rounds belong to.

    Draws sharing a bucket are batched into one email per round label, and each
    holds that batch open until the others have reached the same round.
    """
    if d.scoring_tier in MAJOR_DIGEST_TIERS:
        # tournament_id is what links the M and F draws of one event. Fall back
        # to the name so an unlinked draw still buckets with its sibling rather
        # than emailing on its own.
        return ("event", d.year, d.tournament_id or d.name)
    if d.week is not None:
        return ("week", d.year, d.week)
    return ("solo", d.id, None)


async def _notify_pending_round_digests() -> None:
    """
    Round-completion digest dispatch.

    espn_monitor records each round the moment it completes
    (notifications.record_round_complete); this decides when a batch is worth
    sending. Draws that run alongside each other finish the same round hours or
    days apart, so a per-draw email meant four messages for one afternoon of
    tennis.

    Batches are (bucket, round label). The bucket is the tennis week for 250s
    and 500s and the event itself for 1000s and Slams — see _digest_bucket.
    Grouping on the round *label* rather than the round number matters because
    the same name sits at different numbers in different draw sizes: R32 is
    round 1 of a 32-draw and round 3 of a 128-draw.
    """
    from app.models.notification import RoundCompleteNotification
    from app.services.notifications import notify_round_complete_digest

    # Before the round sweep, not after: it only considers a completed draw's
    # final round once completion_notified_at is set, so an unrecorded
    # completion would otherwise hide that draw's Final for another cycle.
    await _record_missed_completions()

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        await _record_completed_rounds(db)
        pending = (await db.execute(
            select(RoundCompleteNotification)
            .where(RoundCompleteNotification.digest_sent_at.is_(None))
        )).scalars().all()
        if not pending:
            return

        draws = {
            d.id: d for d in (await db.execute(
                select(Draw).where(Draw.id.in_([p.draw_id for p in pending]))
            )).scalars().all()
        }

        groups: dict[tuple, list] = {}
        for p in pending:
            d = draws.get(p.draw_id)
            if not d:
                continue
            groups.setdefault((_digest_bucket(d), d.round_name(p.round_number)), []).append((p, d))

        batches = []
        for (bucket, label), members in groups.items():
            kind = bucket[0]
            if kind == "solo":
                p, d = members[0]
                batches.append(([(d.id, p.round_number)], False, 1, None))
                continue

            if kind == "event":
                _, year, ident = bucket
                event_label = members[0][1].name
                bucket_desc = f"{year} {event_label}"
                q = select(Draw).where(Draw.year == year)
                q = (q.where(Draw.tournament_id == ident) if isinstance(ident, int)
                     else q.where(Draw.name == ident))
            else:
                _, year, week = bucket
                event_label = None
                bucket_desc = f"{year} week {week}"
                q = select(Draw).where(Draw.year == year, Draw.week == week)

            # Re-bucket the candidates rather than trusting the query: a week
            # query still returns the 1000s and Slams starting that week, and
            # those belong to their own digest, not this one.
            siblings = [s for s in (await db.execute(q)).scalars().all()
                        if _digest_bucket(s) == bucket]

            # Which of the bucket's draws will ever produce this round label,
            # and of those, which have not reported it yet. A draw whose bracket
            # never contains this label (a 32-draw has no R128) is not a
            # straggler and must not hold the batch.
            in_scope, outstanding = [], []
            for s in siblings:
                rn = next((r for r in range(1, s.num_rounds + 1) if s.round_name(r) == label), None)
                if rn is None:
                    continue
                in_scope.append(s)
                reported = await db.scalar(
                    select(RoundCompleteNotification.id).where(
                        RoundCompleteNotification.draw_id == s.id,
                        RoundCompleteNotification.round_number == rn,
                    )
                )
                # Unconditional: a draw in the bucket that has not reported this
                # round holds the batch, whatever its status. There used to be an
                # exemption for 'completed' draws, on the reasoning that a
                # finished tournament can no longer produce the round — but that
                # published the bucket without it, which is exactly what a digest
                # must never do. A finished draw that has not reported is a
                # recording failure, and _record_completed_rounds now sweeps every
                # round of a recently-completed draw so the report arrives instead
                # of the batch going out short.
                if not reported:
                    outstanding.append(s)

            # Already-sent siblings mean this bucket's digest for this round has
            # gone; anything arriving now is a late finisher.
            is_followup = await db.scalar(
                select(RoundCompleteNotification.id).where(
                    RoundCompleteNotification.draw_id.in_([s.id for s in in_scope]),
                    RoundCompleteNotification.digest_sent_at.isnot(None),
                    RoundCompleteNotification.round_number.in_([p.round_number for p, _ in members]),
                )
            ) is not None

            # No deadline, and no exceptions: the batch waits until every draw
            # in the bucket that can reach this round has reported, however long
            # that takes. Publishing a bucket while one of its draws is still
            # lagging is the thing a digest exists to prevent — there is no
            # timeout, no partial send, no "send now and follow up later".
            # Bounded because a bucket is either one week of short events or one
            # event, never a week gated on a fortnight-long major.
            if outstanding:
                logger.info(
                    "Round digest %s for %s held: %d ready, waiting on %s",
                    label, bucket_desc, len(members),
                    [f"{s.name} ({s.gender})" for s in outstanding],
                )
                # Waiting is correct; waiting silently forever is not. A draw
                # whose own end date is well past should have reported this round
                # already, so the wait has stopped being normal lag and become a
                # recording failure. Raise it instead of shortening the wait.
                cutoff = date.today() - timedelta(days=DIGEST_STALL_DAYS)
                stalled = [s for s in outstanding if s.end_date and s.end_date < cutoff]
                if stalled:
                    from app.services.system_log import app_log
                    await app_log(
                        "error", "notifications",
                        f"{label} digest for {bucket_desc} is held with {len(members)} "
                        f"draw(s) ready: "
                        f"{', '.join(f'{s.name} ({s.gender})' for s in stalled)} "
                        f"finished on or before {max(s.end_date for s in stalled)} but has "
                        f"never recorded this round, so the email cannot go out",
                        {"round_name": label, "bucket": bucket_desc,
                         "stalled_draw_ids": [s.id for s in stalled],
                         "ready_draw_ids": [d.id for _, d in members]},
                        dedup_key=f"digest_stalled_{bucket_desc}_{label}",
                        dedup_hours=DRAW_HEALTH_REALERT_HOURS,
                    )
                continue
            batches.append((
                [(d.id, p.round_number) for p, d in members],
                is_followup,
                len(in_scope),
                event_label,
            ))

    if not batches:
        return
    for entries, is_followup, span, event_label in batches:
        asyncio.create_task(notify_round_complete_digest(
            entries, is_followup=is_followup, total_in_week=span,
            event_label=event_label,
        ))
    logger.info("Round-complete digest: dispatched %d batch(es) covering %d draw-round(s)",
                len(batches), sum(len(e) for e, _, _, _ in batches))


# Re-alert cadence for the two draw-health checks below — long enough to not
# spam on every run, short enough that a genuinely stuck tournament doesn't
# go unnoticed for days (as Iași Open's title did before anyone looked).
DRAW_HEALTH_REALERT_HOURS = 6.0


async def _check_draw_health() -> None:
    """
    Periodic sanity sweep for two classes of silent failure that were each hit
    in production and neither raises an exception on its own, so nothing else
    would ever flag them:

    1. "Released but not shown as open" (Athens Open) — draw_released_direct_at
       is set, the tournament genuinely hasn't started, and it's within the
       window where computed_status is supposed to report "open" — but it
       doesn't. This directly re-derives the "should be open" condition from
       raw fields (NOT by calling computed_status) so the check stays useful
       even if a future change reintroduces the same kind of ordering bug in
       computed_status itself — a check that just re-asked the buggy property
       what it thinks would never catch its own bug.

    2. "Wiki page never resolves" (Iași Open) — wiki_page_id has never been
       set (every scrape attempt has failed to even locate the page) for a
       tournament whose expected draw-release date has passed (or, when no
       release date is known, that starts within a day).
       Each individual attempt already logs+dedups hourly via
       _refresh_active_tournaments' exception handler; this escalates once
       it's clearly not a transient blip but a wrong/dead title that needs a
       human to fix (as with Iași Open's malformed season-page wikilink).
    """
    from app.services.system_log import app_log

    today = date.today()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Draw).where(Draw.status.notin_(["completed"]))
        )
        tournaments = result.scalars().all()

    for t in tournaments:
        # --- Check 1: released but not open -------------------------------
        should_be_open = (
            t.draw_released_direct_at is not None
            and t.start_date is not None
            and today < t.start_date
            and (t.start_date - today).days <= 30
            and t.status not in ("active", "completed")
        )
        if should_be_open and t.computed_status not in ("open", "active", "completed"):
            await app_log(
                "error", "scheduler",
                f"Draw released but not showing as open: {t.year} {t.name} ({t.gender}) — "
                f"computed_status={t.computed_status!r}, expected 'open'",
                {"tournament_id": t.id, "tournament_name": t.name, "gender": t.gender,
                 "draw_released_direct_at": str(t.draw_released_direct_at),
                 "start_date": str(t.start_date), "computed_status": t.computed_status},
                dedup_key=f"released_not_open_{t.id}", dedup_hours=DRAW_HEALTH_REALERT_HOURS,
            )

        # --- Check 2: wiki page never resolves -----------------------------
        # Only escalate once the draw is actually overdue. Draw pages are
        # normally created on Wikipedia around the release date, so an
        # unresolved page before then is expected, not an error.
        # draw_release_direct is deliberately a floor, not a best guess — it can
        # only land on or before the real release (see draw_dates.py). Escalating
        # the day after it passes would therefore fire on draws that are simply
        # arriving on their normal schedule. Use the LATER of that date and the
        # day before play, by which point a draw genuinely is always out.
        deadline = t.start_date - timedelta(days=1) if t.start_date else None
        if t.draw_release_direct is not None:
            predicted_deadline = t.draw_release_direct + timedelta(days=1)
            deadline = max(deadline, predicted_deadline) if deadline else predicted_deadline
        release_overdue = deadline is not None and today >= deadline
        if t.wiki_page_id is None and release_overdue:
            await app_log(
                "error", "scheduler",
                f"Wiki page never resolved for {t.year} {t.name} ({t.gender}) — "
                f"likely a wrong/dead wiki_page_title: {t.wiki_page_title!r}",
                {"tournament_id": t.id, "tournament_name": t.name, "gender": t.gender,
                 "wiki_page_title": t.wiki_page_title, "draw_release_direct": str(t.draw_release_direct),
                 "start_date": str(t.start_date)},
                dedup_key=f"wiki_never_resolved_{t.id}", dedup_hours=DRAW_HEALTH_REALERT_HOURS,
            )


async def _sync_subscriptions() -> None:
    """Sync EventStreams subscriptions with active/pending tournaments + season pages."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Draw).where(
                Draw.status.in_(["upcoming", "open", "active"])
            )
        )
        tournaments = result.scalars().all()

    # Tournament draw pages: use page_id when known. For unresolved pages,
    # subscribe every plausible title variant ('– Singles' vs gendered) —
    # editors' choice of suffix isn't reliably predictable, and watching all
    # variants means page creation is caught instantly whichever they pick.
    from app.services.scraper import singles_title_variants
    wanted: dict[str, int | None] = {}
    for t in tournaments:
        if t.wiki_page_id is None:
            for v in singles_title_variants(t.wiki_page_title, t.gender):
                wanted.setdefault(v, None)
    for t in tournaments:
        if t.wiki_page_id is not None:
            wanted[t.wiki_page_title] = t.wiki_page_id

    # Season pages: always subscribed by title (we don't store their page IDs)
    for title in _season_pages():
        wanted[title] = None

    current = eventstream.subscriptions
    added = removed = 0
    for title, page_id in wanted.items():
        if title not in current:
            await eventstream.subscribe(title, page_id=page_id)
            added += 1
        elif page_id is not None and eventstream.current_page_id_for(title) != page_id:
            # Title already subscribed but under a stale/wrong page_id — update it.
            await eventstream.subscribe(title, page_id=page_id)
            added += 1

    for title in current - set(wanted):
        await eventstream.unsubscribe(title)
        removed += 1

    # Log full subscription state so we can verify page_ids are correct
    with_id = {pid: t for t, pid in wanted.items() if pid is not None}
    without_id = [t for t, pid in wanted.items() if pid is None]
    logger.info(
        "_sync_subscriptions: added=%d removed=%d | "
        "id_subs=%d %s | title_only=%d %s",
        added, removed,
        len(with_id), with_id,
        len(without_id), without_id,
    )


async def _sync_highest_rank_bot() -> None:
    """Keep the "Highest_Rank" baseline user's picks current for every draw
    that hasn't locked yet. Idempotent full-bracket recompute — see
    highest_rank_bot.py docstring for why a one-shot-before-lock simulation
    (rather than re-simulating after each round) is the correct baseline."""
    from app.services import highest_rank_bot
    from app.services.system_log import app_log

    try:
        async with AsyncSessionLocal() as db:
            synced = await highest_rank_bot.sync_open_draws(db)
        if synced:
            logger.info("Highest_Rank bot: synced picks for %d draw(s)", synced)
    except Exception as exc:
        logger.error("Highest_Rank bot sync failed: %s", exc)
        await app_log("error", "highest_rank_bot", f"Sync job failed: {exc}",
                      {"error": str(exc)}, dedup_key="highest_rank_bot_fail", dedup_hours=6)


def start_scheduler() -> None:
    scheduler.add_job(
        _auto_discover_tournaments,
        "cron",
        hour=0,
        minute=0,
        id="auto_discover",
        misfire_grace_time=3600,
    )
    # Scrape active tournaments every 30 minutes so live scores update promptly.
    scheduler.add_job(
        _refresh_active_tournaments,
        "interval",
        minutes=30,
        id="refresh_active",
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _sync_subscriptions,
        "interval",
        minutes=5,
        id="sync_subscriptions",
        misfire_grace_time=120,
    )
    # Centralized "draw released" email dispatch — see _notify_pending_draw_releases
    # docstring. 10 min cadence matches the 10 min stability cooldown, so worst
    # case a stable release waits one extra tick (up to ~10 min) before emailing.
    scheduler.add_job(
        _notify_pending_draw_releases,
        "interval",
        minutes=10,
        id="notify_draw_releases",
        misfire_grace_time=300,
    )
    # Weekly round-completion digest. 10 min matches the draw-release job: a
    # round that completes the batch waits at most one tick before going out.
    scheduler.add_job(
        _notify_pending_round_digests,
        "interval",
        minutes=10,
        id="notify_round_digests",
        misfire_grace_time=300,
    )
    # Sanity sweep for silent failures (released-but-not-open, wiki title
    # never resolving) — see _check_draw_health docstring.
    scheduler.add_job(
        _check_draw_health,
        "interval",
        minutes=60,
        id="check_draw_health",
        misfire_grace_time=600,
    )
    # Keep the "Highest_Rank" baseline user's picks current as entries/rankings
    # firm up. 10 min cadence matches the draw-release notify job.
    scheduler.add_job(
        _sync_highest_rank_bot,
        "interval",
        minutes=10,
        id="sync_highest_rank_bot",
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _refresh_weekly_rankings,
        "cron",
        day_of_week="sun",
        hour=18,
        minute=0,
        timezone="America/Los_Angeles",  # PDT/PST — always fires at 6pm Pacific
        id="refresh_weekly_rankings",
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _refresh_elo,
        "cron",
        day_of_week="mon",
        hour=1,
        minute=30,
        id="refresh_elo",
        misfire_grace_time=3600,
    )
    eventstream._on_season_page_edit = _on_season_page_edit
    scheduler.start()
    logger.info("Tournament discovery scheduled (daily at midnight UTC)")
    logger.info("Active tournament refresh scheduled (every 30 min)")
    logger.info("EventStreams listener started for real-time draw updates")
    logger.info("Subscription sync scheduled (every 5 min)")
    logger.info("Weekly rankings refresh scheduled (Sunday 6pm PDT)")
    logger.info("Draw-release notification check scheduled (every 10 min)")
    logger.info("Round-complete digest check scheduled (every 10 min)")
    logger.info("Draw health check scheduled (every 60 min)")
    logger.info("Highest_Rank bot sync scheduled (every 10 min)")
    asyncio.create_task(eventstream.start())
    asyncio.create_task(espn_monitor.start())
    # Subscribe immediately on startup so EventStreams catches edits from the
    # first second — don't wait up to 5 min for the interval job to fire.
    asyncio.create_task(_sync_subscriptions())
    # Force-refresh on startup to catch any results that arrived while the
    # server was down.
    asyncio.create_task(_refresh_active_tournaments(force_refresh=True))
    # Catch any draw releases that went stable while the server was down.
    asyncio.create_task(_notify_pending_draw_releases())
    # Catch any tournaments that were already stuck before this restart.
    asyncio.create_task(_check_draw_health())
    # Catch any draws whose entries/rankings firmed up while the server was down.
    asyncio.create_task(_sync_highest_rank_bot())
    # Backfill DOB for any te_players missing it (no-op if all already set).
    from app.services.rankings import backfill_all_dob, refresh_elo_ratings
    asyncio.create_task(backfill_all_dob())
    asyncio.create_task(refresh_elo_ratings())


def stop_scheduler() -> None:
    import asyncio

    asyncio.create_task(eventstream.stop())
    espn_monitor.stop()
    scheduler.shutdown(wait=False)
