"""
Notification dispatch helpers.

Called from the scheduler after each successful tournament scrape, once the
DB session has been committed.  Each function opens its own session so it is
independent of the caller's transaction.
"""

import asyncio
import html
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone as tz
from typing import Optional

from sqlalchemy import func, select, or_
from sqlalchemy.orm import selectinload

from app.core.security import create_unsubscribe_token
from app.database import AsyncSessionLocal
from app.services.email import API_BASE, _tournament_label
from app.models.league import League, LeagueMember
from app.models.notification import NotificationPreference
from app.models.prediction import UserPrediction
from app.models.tournament import Draw, DrawEntry, Match
from app.models.user import User
from app.services.draw_changes import change_line, last_name as _last_name
from app.services.scoring import rank_users, score_user

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Round-complete notification
# ---------------------------------------------------------------------------

# Max competitors shown in the Global block of a round-complete email.
GLOBAL_ROWS = 9
# Sort weight for a player with no ranking, so those matches land at the bottom
# of their group instead of the top (None can't be compared to an int, and 0
# would read as "better than world #1").
_UNRANKED = 10**6


def _email_round_label(round_name: str) -> str:
    """Email-specific round label: R128/R64/R32/R16, Quarter-Finals, Semi-Finals, Final."""
    mapping = {
        "Final": "Final",
        "Semifinals": "Semi-Finals",
        "Quarterfinals": "Quarter-Finals",
    }
    if round_name in mapping:
        return mapping[round_name]
    if round_name.startswith("Round of "):
        return "R" + round_name[len("Round of "):]
    return round_name


def _entry_status(entry) -> str:
    """
    The badge the draw shows against a player: seed number, else entry type
    (WC / Q / LL / PR / SE / Alt / NG).

    Seed and entry_type are mutually exclusive in the data — 0 rows carry both —
    so this is one value, not two.

    Still sanitised, but as a backstop rather than a workaround: the scraper
    used to store what it swallowed whole ('&nbsp;', '<small>1/WC</small>') and
    now strips wrapper tags and entities itself, with those rows re-parsed. This
    stays because entry_type is arbitrary scraped wikitext reaching an email —
    the one place where markup that slipped through would either render live or
    show as visible tags.
    """
    if entry is None:
        return ""
    if entry.seed:
        return str(entry.seed)
    raw = re.sub(r"<[^>]+>", "", entry.entry_type or "")
    return html.unescape(raw).replace("\xa0", " ").strip()


def _strip_tiebreak(val: str) -> str:
    idx = val.find("(")
    return val[:idx] if idx != -1 else val


_WALKOVER_RE = re.compile(r"^w/?o$", re.I)


def _match_score_str(match: Match) -> str:
    """Set-by-set score with tiebreak points stripped, e.g. '6-4, 3-6, 7-6'
    (never '7-6(12)') — kept compact for the round-complete email widget.

    Two markers travel inside the score cells rather than beside them, and both
    used to leak out raw. A walkover is stored the way Wikipedia writes it — the
    withdrawing side's only cell is the literal "w/o" — which rendered as the
    bare "-w/o"; and a retirement appends "r" to the last game count, which
    rendered as "1r-0". Neither is a score, so both are read out and said in
    words instead."""
    if not match.scores_json or len(match.scores_json) < 2:
        return ""
    p1_sets, p2_sets = match.scores_json[0], match.scores_json[1]

    # No games were played, so there is nothing to format — only to name.
    if any(_WALKOVER_RE.match(str(v or "").strip())
           for side in (p1_sets, p2_sets) for v in (side or [])):
        return "w/o"

    retired = any(str(v or "").strip().lower().endswith("r")
                  for side in (p1_sets, p2_sets) for v in (side or []))
    own, opp = (p1_sets, p2_sets) if match.winner_id == match.player1_id else (p2_sets, p1_sets)
    parts = []
    for i in range(max(len(own), len(opp))):
        a = _strip_tiebreak(own[i]) if i < len(own) else ""
        b = _strip_tiebreak(opp[i]) if i < len(opp) else ""
        if not a and not b:
            continue
        # The "r" marks WHICH player retired, which the winner's name already
        # says; kept in the cell it would read as part of the game count.
        parts.append(f"{a.rstrip('rR')}-{b.rstrip('rR')}")
    score = ", ".join(parts)
    return f"{score} (ret.)" if score and retired else score


def _ordinal(n: int) -> str:
    """1 -> '1st', 2 -> '2nd', 11 -> '11th'."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


async def record_round_complete(tournament_id: int, round_number: int) -> None:
    """
    Mark a round as finished, without emailing anyone yet.

    Round emails are a weekly digest — one message covering every draw in the
    week that has reached the same round — so detection and dispatch are
    separate steps. This claims (draw_id, round_number) the moment the round
    completes; scheduler._notify_pending_round_digests decides when the week's
    batch is ready and sends it. The unique constraint makes the claim the
    idempotency guard it always was: a re-triggered completion (a winner being
    cleared and re-set by a later scrape) silently loses the race and no second
    email is ever queued.
    """
    from sqlalchemy.exc import IntegrityError
    from app.services.system_log import app_log
    from app.models.notification import RoundCompleteNotification

    async with AsyncSessionLocal() as db:
        db.add(RoundCompleteNotification(
            draw_id=tournament_id, round_number=round_number, recipient_count=0,
        ))
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            logger.debug(
                "Round %d of draw %d already recorded — not re-queued",
                round_number, tournament_id,
            )
            return
    await app_log("info", "notifications",
                  f"Round {round_number} complete for draw {tournament_id} — queued for weekly digest",
                  {"draw_id": tournament_id, "round_number": round_number})


async def _gather_round_payload(
    db,
    tournament: Draw,
    round_number: int,
) -> Optional[dict]:
    """
    Everything one draw's completed round contributes to the digest.

    Returns None when there is nothing to report. Recipient selection is
    deliberately NOT final here: the digest merges several draws first and only
    then decides who to email, because a user may be eligible in one draw of the
    week and not another.
    """
    round_name = _email_round_label(tournament.round_name(round_number))
    is_final_round = round_number == tournament.num_rounds

    m_res = await db.execute(
        select(Match)
        .options(selectinload(Match.player1), selectinload(Match.player2), selectinload(Match.winner))
        # is_bye excluded: a bye is not a contest. It is stamped completed with
        # an auto-advanced winner, and stray picks do exist on those rows, so
        # scoring them hands out free points (see _persist_tournament_results).
        .where(Match.draw_id == tournament.id, Match.status == "completed",
               Match.is_bye == False)  # noqa: E712
    )
    completed_matches = m_res.scalars().all()

    round_matches = sorted(
        (m for m in completed_matches
         if m.round_number == round_number and not m.is_bye and m.winner_id),
        key=lambda m: m.match_number,
    )
    # (match_id, winner_id, w_last, w_status, w_rank, l_last, l_status, l_rank, score)
    round_match_info = []
    for m in round_matches:
        winner_entry = m.winner
        loser_entry = m.player2 if m.winner_id == m.player1_id else m.player1
        if not winner_entry or not loser_entry:
            continue
        round_match_info.append((
            m.id, m.winner_id,
            _last_name(winner_entry.name), _entry_status(winner_entry), winner_entry.ranking,
            _last_name(loser_entry.name), _entry_status(loser_entry), loser_entry.ranking,
            _match_score_str(m),
        ))

    total_res = await db.execute(
        select(func.count()).where(Match.draw_id == tournament.id, Match.is_bye == False)  # noqa: E712
    )
    total_matches = total_res.scalar_one()
    if total_matches == 0:
        return None

    pred_res = await db.execute(
        select(UserPrediction).where(
            UserPrediction.draw_id == tournament.id,
            UserPrediction.predicted_winner_id.isnot(None),
        )
    )
    preds_by_user: dict[int, list] = defaultdict(list)
    for p in pred_res.scalars().all():
        preds_by_user[p.user_id].append(p)

    # Competing = at least one pick. A partial bracket is a real entry that
    # simply forfeits the matches it left unpicked, so it belongs in the
    # standings and its owner gets the digest like anyone else.
    eligible = {uid for uid, preds in preds_by_user.items() if preds}
    if not eligible:
        return None

    global_scores = {
        uid: score_user(uid, preds_by_user[uid], completed_matches, tournament, None)
        for uid in eligible
    }
    global_ranked = rank_users(list(global_scores.values()), tournament.num_rounds)

    lg_res = await db.execute(select(League).options(selectinload(League.members)))
    league_data: dict[int, dict] = {}
    for lg in lg_res.scalars().all():
        participants = eligible & {m.user_id for m in lg.members}
        if len(participants) < 2:
            continue
        lg_scores = {
            uid: score_user(uid, preds_by_user[uid], completed_matches, tournament, None)
            for uid in participants
        }
        lg_ranked = rank_users(list(lg_scores.values()), tournament.num_rounds)
        league_data[lg.id] = {
            "name": lg.name,
            "ranked": lg_ranked,
            "member_ids": {s.user_id for s in lg_ranked},
        }

    user_league_ids: dict[int, list] = defaultdict(list)
    for lg_id, data in league_data.items():
        for uid in data["member_ids"]:
            user_league_ids[uid].append(lg_id)

    users_res = await db.execute(
        select(User.id, User.username).where(User.id.in_(eligible))
    )
    usernames = {r[0]: r[1] for r in users_res.all()}

    def _row_of(ranked: list, idx: int, me: int) -> tuple:
        s = ranked[idx]
        return (idx + 1, usernames.get(s.user_id, "—"), s.total_points, s.user_id == me)

    def _standings_rows(ranked: list, me: int, limit: Optional[int] = None) -> list[tuple]:
        """Competitor list for a group as (rank, username, score, is_you).

        With `limit` set, shows the top `limit` competitors — unless the
        recipient sits outside it, in which case the last of those slots goes
        to them, preceded by a "…" gap row: (None, '…', None, False). So the
        recipient is always present and the block never exceeds `limit`.
        """
        if limit is None or len(ranked) <= limit:
            return [_row_of(ranked, i, me) for i in range(len(ranked))]
        me_idx = next((i for i, s in enumerate(ranked) if s.user_id == me), 0)
        if me_idx < limit:
            return [_row_of(ranked, i, me) for i in range(limit)]
        rows = [_row_of(ranked, i, me) for i in range(limit - 1)]
        rows.append((None, "…", None, False))
        rows.append(_row_of(ranked, me_idx, me))
        return rows

    global_place = {s.user_id: i + 1 for i, s in enumerate(global_ranked)}
    label = _tournament_label(tournament.name, tournament.category or "", tournament.gender or "M")

    per_user: dict[int, dict] = {}
    for uid in eligible:
        user_preds_by_match = {p.match_id: p.predicted_winner_id for p in preds_by_user.get(uid, [])}
        # Ordered per recipient, not in bracket order: the picks they got right
        # lead, then the biggest names. "Highest ranked" is read as the best
        # rank present in the match, not the winner's — a seed going out in the
        # first round is the result you want at the top of its group, and
        # ranking by the winner would bury it under the match that produced it.
        # Unranked players sort last rather than first, which an absent ranking
        # would otherwise do.
        ordered = []
        for (mid, winner_id, w_last, w_status, w_rank,
             l_last, l_status, l_rank, score) in round_match_info:
            is_correct = user_preds_by_match.get(mid) == winner_id
            ranks = [r for r in (w_rank, l_rank) if r is not None]
            ordered.append((
                (not is_correct, min(ranks) if ranks else _UNRANKED),
                (w_last, w_status, l_last, l_status, score, is_correct),
            ))
        ordered.sort(key=lambda t: t[0])
        match_results = [row for _, row in ordered]

        leagues = []
        if len(eligible) >= 2:
            # Global shows at most 9 competitors, always including the recipient —
            # _standings_rows anchors the leaders and drops in a "…" gap row when
            # the recipient sits outside that head.
            g_limit = GLOBAL_ROWS if len(global_ranked) > GLOBAL_ROWS else None
            leagues.append(("Global", _standings_rows(global_ranked, uid, g_limit)))
        for lg_id in sorted(user_league_ids.get(uid, [])):
            data = league_data[lg_id]
            leagues.append((data["name"], _standings_rows(data["ranked"], uid)))
        if not leagues:
            continue

        hits = sum(1 for r in match_results if r[5])
        place = global_place.get(uid)
        per_user[uid] = {
            "section": {
                "id": tournament.id,
                "label": label,
                "city": tournament.city,
                "round_name": round_name,
                "leagues": leagues,
                "match_results": match_results,
            },
            "summary": (
                label,
                f"{hits}/{len(match_results)}",
                f"{_ordinal(place)} of {len(global_ranked)}" if place else "—",
            ),
        }

    return {
        "id": tournament.id,
        "round_number": round_number,
        "round_name": round_name,
        "is_final_round": is_final_round,
        "eligible": eligible,
        "per_user": per_user,
    }


async def notify_round_complete_digest(
    entries: list[tuple],
    is_followup: bool = False,
    total_in_week: Optional[int] = None,
    only_user_ids: Optional[set] = None,
    claim: bool = True,
    event_label: Optional[str] = None,
) -> None:
    """
    Send ONE round-completion email per user, covering every draw in `entries`.

    entries: [(draw_id, round_number), ...] — all the same round *label* in the
    same digest bucket. Round label rather than number, because the same name
    sits at a different number in different draw sizes: R32 is round 1 of a
    32-draw and round 3 of a 128-draw.

    event_label: set when the bucket is a single 1000/Slam event rather than a
    tennis week (scheduler._digest_bucket). The batch is then that event's own
    draws — both genders where it hosts both — and the email is titled after the
    event instead of the week.

    Recipients are unioned across the draws and then sliced back per user: a
    user eligible in two of the week's three draws gets those two sections and
    a two-row summary, not a blank third.
    """
    from sqlalchemy import update as sa_update
    from app.services.email import send_round_complete_digest
    from app.services.system_log import app_log
    from app.models.notification import RoundCompleteNotification

    if not entries:
        return

    async with AsyncSessionLocal() as db:
        payloads = []
        for draw_id, round_number in entries:
            tournament = await db.get(Draw, draw_id)
            if not tournament:
                continue
            payload = await _gather_round_payload(db, tournament, round_number)
            if payload:
                payloads.append(payload)
        if not payloads:
            return

        round_name = payloads[0]["round_name"]
        starts = [
            d.start_date for d in
            (await db.execute(select(Draw).where(Draw.id.in_([p["id"] for p in payloads])))).scalars().all()
            if d.start_date
        ]
        week_start = min(starts) if starts else None
        week_label = f"{week_start.strftime('%B')} {week_start.day}" if week_start else "this week"

        # Everyone eligible in at least one of the week's draws.
        candidates: set[int] = set()
        for p in payloads:
            candidates |= set(p["per_user"].keys())
        if not candidates:
            return

        # "Final" is a round label like any other, so a batch carrying it is
        # every draw in the week that finished — this IS the draw-completion
        # digest. There is no separate per-draw "Final Standings" email any
        # more; sending one meant a message per tournament instead of one for
        # the week, and it duplicated what this already reports.
        is_final_batch = bool(payloads) and all(p["is_final_round"] for p in payloads)

        if only_user_ids is not None:
            # Forced/test send: target these directly, ignoring opt-in/verified.
            to_notify = candidates & only_user_ids
            end_only = set()
        else:
            pref_res = await db.execute(
                select(NotificationPreference.user_id)
                .join(User, User.id == NotificationPreference.user_id)
                .where(
                    NotificationPreference.pref_key == "round_standings",
                    NotificationPreference.user_id.in_(candidates),
                    User.email_verified == True,  # noqa: E712
                )
            )
            to_notify = {r[0] for r in pref_res.all()}

            # 'tournament_end' means "only tell me how draws finished, not every
            # round" — the settings UI offers it exactly when round emails are
            # off. Those users belong in this batch and no other, so the final
            # round is the one time the audience is wider than round_standings.
            end_only = set()
            if is_final_batch:
                end_res = await db.execute(
                    select(NotificationPreference.user_id)
                    .join(User, User.id == NotificationPreference.user_id)
                    .where(
                        NotificationPreference.pref_key == "tournament_end",
                        NotificationPreference.user_id.in_(candidates),
                        User.email_verified == True,  # noqa: E712
                    )
                )
                end_only = {r[0] for r in end_res.all()} - to_notify
                to_notify |= end_only

        emails_res = await db.execute(select(User.id, User.email).where(User.id.in_(to_notify)))
        emails = {r[0]: r[1] for r in emails_res.all()}

        if claim:
            now = datetime.now(tz.utc)
            await db.execute(
                sa_update(RoundCompleteNotification)
                .where(
                    RoundCompleteNotification.draw_id.in_([p["id"] for p in payloads]),
                    RoundCompleteNotification.round_number.in_([p["round_number"] for p in payloads]),
                    RoundCompleteNotification.digest_sent_at.is_(None),
                )
                .values(digest_sent_at=now, recipient_count=len(to_notify))
            )
            await db.commit()

    if not to_notify:
        logger.debug("Round digest %s week of %s: no opted-in recipients", round_name, week_label)
        return

    reached = len(payloads)
    span = total_in_week if total_in_week is not None else reached

    sent = 0
    for uid in to_notify:
        email = emails.get(uid)
        if not email:
            continue
        sections, summary_rows = [], []
        for p in payloads:
            entry = p["per_user"].get(uid)
            if not entry:
                continue
            sections.append(entry["section"])
            summary_rows.append(entry["summary"])
        if not sections:
            continue
        # Unsubscribe has to drop the preference that actually put this email in
        # their inbox, or the link silently does nothing for the final-round-only
        # audience.
        pref_key = "tournament_end" if uid in end_only else "round_standings"
        try:
            await send_round_complete_digest(
                email, sections, round_name, week_label,
                reached=reached, total_in_week=span, summary_rows=summary_rows,
                unsubscribe_url=(
                    f"{API_BASE}/unsubscribe?token="
                    f"{create_unsubscribe_token(uid, pref_key)}"
                ),
                unsubscribe_label=(
                    "draw-completion emails" if pref_key == "tournament_end"
                    else "round-completion emails"
                ),
                is_final=is_final_batch,
                is_followup=is_followup,
                event_label=event_label,
            )
            sent += 1
        except Exception as exc:
            logger.warning("Failed to send round digest to user %d: %s", uid, exc)

    # Push mirrors the email: one per batch, same moment, and — now — the same
    # audience rule, built the same way a few dozen lines above.
    #
    # round_standings covers every round INCLUDING the Final; tournament_end is
    # the narrower opt-in for people who want only the Final. So a final batch
    # goes to both, and every other round goes to round_standings alone. This
    # used to pick one preference per batch — tournament_end for a final,
    # round_standings otherwise — which meant someone holding only Round
    # completion got no push for the Final, the round they care most about,
    # while the settings grid greyed out Draw completion telling them it was
    # covered. Email never had the bug; it unions the two audiences.
    #
    # A set, not a list: a user holding both preferences would otherwise be
    # pushed to twice.
    try:
        from app.services.push import send_push_to_users, users_with_push
        push_uids = set(await users_with_push("round_standings"))
        if is_final_batch:
            push_uids |= set(await users_with_push("tournament_end"))
        if push_uids:
            # Name the event when the batch is one: event_label covers the
            # 1000s and Slams (bucketed by event), and a week that happens to
            # hold a single draw is named from that draw. Only a genuinely
            # mixed week falls back to the date, where no single name is true.
            # Fetched fresh rather than read off the payload: name, gender and
            # category are draw columns, and the payload only carries per-user
            # sections (an earlier version reached for payloads[0]["label"] and
            # raised KeyError straight into the wrapper below).
            async with AsyncSessionLocal() as db:
                batch = (await db.execute(
                    select(Draw).where(Draw.id.in_([p["id"] for p in payloads]))
                )).scalars().all()
            by_id = {d.id: d for d in batch}
            ordered = [by_id[p["id"]] for p in payloads if p["id"] in by_id]

            if event_label:
                where = event_label
            elif len(ordered) == 1:
                where = ordered[0].name
            else:
                where = f"week of {week_label}"

            from app.services import push_content
            content = push_content.round_complete(
                round_name, where,
                [{"name": d.name, "gender": d.gender, "category": d.category}
                 for d in ordered],
                is_final_batch,
            )
            await send_push_to_users(push_uids, **content)
    except Exception as exc:
        logger.warning("Round-digest push failed: %s", exc)

    kind = "Draw-completion" if is_final_batch else "Round-complete"
    await app_log("info", "notifications",
                  f"{kind} {'follow-up' if is_followup else 'digest'} ({round_name}, "
                  f"{event_label or f'week of {week_label}'}) sent to {sent} user(s) "
                  f"covering {reached} draw(s)",
                  {"draw_ids": [p["id"] for p in payloads], "round_name": round_name,
                   "recipient_count": sent, "is_followup": is_followup,
                   "is_final": is_final_batch, "final_round_only_recipients": len(end_only),
                   "event_label": event_label})


async def notify_round_complete(
    tournament_id: int,
    round_number: int,
    only_user_ids: Optional[set] = None,
    force: bool = False,
) -> None:
    """Single-draw immediate send — the admin/test path (send_test_round_email.py).

    The real pipeline no longer goes through here: espn_monitor records the
    round and the scheduler batches it into the week's digest. This renders the
    same template with one section and never claims, so a test send can't
    suppress the genuine digest.
    """
    await notify_round_complete_digest(
        [(tournament_id, round_number)],
        only_user_ids=only_user_ids,
        claim=not force,
        total_in_week=1,
    )


# ---------------------------------------------------------------------------
# Match-start notification
# ---------------------------------------------------------------------------

# Draw-release emails are a single on/off. They were once selectable per tier
# ('draw_open:ATP 250', …), which stopped making sense when the email became a
# weekly digest: one message covers every draw released that week, so a per-tier
# opt-in could only ever have filtered rows out of a mail the user was getting
# regardless. The old keys are migrated into this one (see database.py).
DRAW_RELEASED_PREF = "draw_released"


async def notify_draw_release_batch(draw_ids: list[int], is_followup: bool = False) -> None:
    """
    Email every user with draw-release notifications on — one message covering
    every draw in the batch.

    Draws for a given week are announced together, so they are emailed together
    (scheduler.py's _notify_pending_draw_releases decides when a week's batch is
    ready) rather than as five separate messages.

    Claiming (draw_id) in draw_release_notifications is the hard,
    unique-constrained backstop behind the caller's coarse
    draw_release_notified_at check, which is a plain SELECT-then-UPDATE with no
    protection against two overlapping executions (a misfire re-run, or a
    migration resetting the detection timestamp, as happened 2026-07-12). Each
    claim gets its own savepoint: one already-claimed draw must drop out of the
    batch, not poison the session and abort the other four.
    """
    from datetime import datetime, timedelta, timezone as tz
    from sqlalchemy import update as sa_update
    from sqlalchemy.exc import IntegrityError
    from app.services.email import send_draw_release_digest, fmt_close, _tier_badge
    from app.services.system_log import app_log
    from app.models.notification import DrawReleaseNotification

    if not draw_ids:
        return

    async with AsyncSessionLocal() as db:
        draws = (await db.execute(select(Draw).where(Draw.id.in_(draw_ids)))).scalars().all()

        # Claim first, send second. A draw that fails to claim has already been
        # emailed by an overlapping run and must be dropped from this batch.
        claimed = []
        for d in draws:
            try:
                async with db.begin_nested():
                    db.add(DrawReleaseNotification(draw_id=d.id, recipient_count=0))
                claimed.append(d)
            except IntegrityError:
                await app_log(
                    "warning", "notifications",
                    f"Draw-released email for draw {d.id} already sent — resend blocked",
                    {"tournament_id": d.id},
                    dedup_key=f"draw-release-dupe-{d.id}",
                )
        if not claimed:
            await db.rollback()
            return

        now_naive = datetime.now(tz.utc).replace(tzinfo=None)
        payload = []
        for d in claimed:
            location = ", ".join(p for p in (d.city, d.country) if p)
            payload.append({
                "id": d.id,
                "name": d.name,
                "gender": d.gender,
                "tier": _tier_badge(d.category or "", d.gender),
                "location": location or None,
                "surface": d.surface,
                "draw_size": d.draw_size,
                # Left raw: the display string is per-recipient, rendered in
                # each reader's own zone in the send loop below. closes_soon is
                # an absolute-instant comparison, so it is zone-independent.
                "closing_time": d.closing_time,
                "closes_soon": bool(
                    d.closing_time and (d.closing_time - now_naive) < timedelta(hours=24)
                ),
                "_sort": d.closing_time or datetime.max,
            })
        payload.sort(key=lambda p: p["_sort"])

        starts = [d.start_date for d in claimed if d.start_date]
        week_start = min(starts) if starts else None
        week_label = f"{week_start.strftime('%B')} {week_start.day}" if week_start else "this week"

        rows = (await db.execute(
            select(User.email, User.id, User.timezone)
            .join(NotificationPreference, NotificationPreference.user_id == User.id)
            .where(
                NotificationPreference.pref_key == DRAW_RELEASED_PREF,
                User.email_verified == True,
            )
            .order_by(User.id)
        )).all()
        # Keyed by email, not user id: one address gets one message even if it
        # somehow appears on two accounts (first by id wins).
        recipients: dict[str, tuple[int, Optional[str]]] = {}
        for email, uid, user_tz in rows:
            recipients.setdefault(email, (uid, user_tz))

        await db.execute(
            sa_update(DrawReleaseNotification)
            .where(DrawReleaseNotification.draw_id.in_([d.id for d in claimed]))
            .values(recipient_count=len(recipients))
        )
        await db.commit()

    if not recipients:
        logger.debug("notify_draw_release_batch: no users opted in to %s", DRAW_RELEASED_PREF)
        return

    for email, (uid, user_tz) in recipients.items():
        unsubscribe_url = (
            f"{API_BASE}/unsubscribe?token="
            f"{create_unsubscribe_token(uid, DRAW_RELEASED_PREF)}"
        )
        rows_for_user = [
            {**p, "closes": fmt_close(p["closing_time"], user_tz) if p["closing_time"] else None}
            for p in payload
        ]
        await send_draw_release_digest(
            email, rows_for_user, week_label,
            is_followup=is_followup, unsubscribe_url=unsubscribe_url,
            tz_known=bool(user_tz),
        )

    # Exactly ONE push per week, after every draw in that week is out.
    #
    # The batch already guarantees the "after every draw" half —
    # _notify_pending_draw_releases holds a week until none of its draws are
    # outstanding. It does NOT guarantee the "exactly one" half: a draw added to
    # a week whose batch has already gone out forms a second batch of its own,
    # which would be a second push for the same week. Email tolerates that as a
    # follow-up; a phone notification should not, so this sends only for the
    # first announced batch of a given week.
    #
    # Runs after the emails and can never raise: the batch is already claimed by
    # this point, so a push failure must not unwind a send that has happened.
    try:
        from app.services.push import send_push_to_users, users_with_push

        claimed_ids = [d.id for d in claimed]
        weeks = {(d.year, d.week) for d in claimed if d.week is not None}

        async with AsyncSessionLocal() as db:
            already_announced = False
            if len(weeks) == 1:
                year, week = next(iter(weeks))
                # Any sibling in this week that was notified before this batch
                # means the week has already had its push.
                already_announced = bool((await db.execute(
                    select(Draw.id)
                    .where(
                        Draw.year == year,
                        Draw.week == week,
                        Draw.draw_release_notified_at.isnot(None),
                        Draw.id.notin_(claimed_ids),
                    )
                    .limit(1)
                )).scalar())

        push_uids = [] if already_announced else await users_with_push(DRAW_RELEASED_PREF)

        if already_announced:
            logger.info("Draw-release push skipped: week already announced")
        elif push_uids:
            from app.services import push_content
            content = push_content.draw_release(
                [{"name": d.name, "gender": d.gender, "category": d.category}
                 for d in sorted(claimed, key=lambda d: d.closing_time or datetime.max)],
                week_label,
            )
            delivered = await send_push_to_users(push_uids, **content)
            logger.info("Draw-release push: %d delivered to %d user(s)", delivered, len(push_uids))
    except Exception as exc:
        logger.warning("Draw-release push failed: %s", exc)

    from app.services.push_content import tour_label
    names = ", ".join(f"{d.year} {d.name} ({tour_label(d.gender)})" for d in claimed)
    await app_log("info", "notifications",
                  f"Draw-release {'follow-up' if is_followup else 'digest'} sent to "
                  f"{len(recipients)} user(s) covering {len(claimed)} draw(s): {names}",
                  {"draw_ids": [d.id for d in claimed], "recipient_count": len(recipients),
                   "week_label": week_label, "is_followup": is_followup})


# ---------------------------------------------------------------------------
# Draw-change notification (a player swapped after the draw was announced)
# ---------------------------------------------------------------------------

DRAW_CHANGED_PREF = "draw_changed"

# Qualifier placements are their own notification, not a flavour of draw change.
# The two answer different questions and land differently: a replacement is
# "someone you picked is gone, go look", a qualifier placement is "the draw is
# complete, here is who plays whom". Merging them meant one message opening with
# a warning and then listing routine slot fills underneath it.
QUALIFIERS_ADDED_PREF = "qualifiers_added"

# DrawChangeEvent.kind → the preference that carries it.
_KIND_PREF = {"replaced": DRAW_CHANGED_PREF, "filled": QUALIFIERS_ADDED_PREF}


async def _round1_matchups(db, draw_id: int, entry_ids: set) -> dict:
    """
    entry_id → (opponent_name, opponent_status, is_bye) for round 1.

    A qualifier's name on its own says nothing worth acting on; who they drew is
    the whole story, and it is what makes the notification answer "does this
    change my bracket". opponent_status is the badge the draw shows — seed
    number, else entry type — via the same _entry_status used by the round
    emails, so a qualifier drawn against the top seed reads as one.

    Missing entries are simply absent from the result: a slot can be filled on
    the page before the pairing is parsed, and "opponent not known yet" is a
    real state rather than an error.
    """
    if not entry_ids:
        return {}
    res = await db.execute(
        select(Match)
        .options(selectinload(Match.player1), selectinload(Match.player2))
        .where(Match.draw_id == draw_id, Match.round_number == 1)
    )
    out: dict = {}
    for m in res.scalars().all():
        for mine, theirs in ((m.player1_id, m.player2), (m.player2_id, m.player1)):
            if mine in entry_ids:
                out[mine] = (
                    theirs.name if theirs else None,
                    _entry_status(theirs) if theirs else "",
                    bool(m.is_bye),
                )
    return out


async def draw_is_fully_transcribed(db, draw_id: int) -> bool:
    """
    True when no slot in the draw is still waiting for a name.

    An unfilled qualifier slot exists as a DrawEntry with entry_type 'Q' and an
    empty name — that is what the bracket renders as "Qualifier N" — so a blank
    name anywhere is the page telling us it is not finished. Checking blanks of
    ANY entry type rather than just Q, because a half-transcribed main draw is
    equally not the moment to announce that the field is set.

    Deliberately not a count against draw_size: that column holds the bracket
    size, not the number of players. 2026 Canadian Open is stored as 128 with 96
    entries, so "entries == draw_size" is false for every 96- and 56-draw event
    and would have held their notification forever.
    """
    blanks = (await db.execute(
        select(func.count()).select_from(DrawEntry).where(
            DrawEntry.draw_id == draw_id,
            func.trim(func.coalesce(DrawEntry.name, "")) == "",
        )
    )).scalar() or 0
    return blanks == 0


async def _gather_qualifier_payload(db, draw: Draw) -> Optional[dict]:
    """
    Every qualifier in the draw and the first-round match each one creates.

    Sourced from the draw's own Q entries rather than from the pending change
    events, because the message is "here is the qualifying field" and that has to
    be the whole field. Qualifiers can arrive in more than one wave, and some may
    have been placed before the draw was announced (nothing is recorded then —
    see the draw_release_notified_at gate in _do_scrape), so the events say WHEN
    to send and the draw says WHAT to send.
    """
    pick_res = await db.execute(
        select(UserPrediction.user_id, UserPrediction.predicted_winner_id).where(
            UserPrediction.draw_id == draw.id,
            UserPrediction.predicted_winner_id.isnot(None),
        )
    )
    picked_entries: dict[int, set] = defaultdict(set)
    for uid, entry_id in pick_res.all():
        picked_entries[uid].add(entry_id)
    if not picked_entries:
        return None

    # Q and LL both, because they are the same slot. Wikipedia reserves it as
    # "Q/LL" — a qualifier OR a lucky loser — and which one arrives is not known
    # until allocation completes. Selecting only Q dropped the lucky loser from
    # the announcement of the very field it belongs to: 2026 Cincinnati had one
    # in each draw, at a slot whose seed cell literally reads "Q/LL".
    quals = (await db.execute(
        select(DrawEntry)
        .where(DrawEntry.draw_id == draw.id, DrawEntry.entry_type.in_(("Q", "LL")))
        .order_by(DrawEntry.bracket_position)
    )).scalars().all()
    quals = [q for q in quals if (q.name or "").strip()]
    if not quals:
        return None

    from app.services.email import _tier_badge

    opponents = await _round1_matchups(db, draw.id, {q.id for q in quals})
    changes = []
    for q in quals:
        opp_name, opp_status, opp_bye = opponents.get(q.id, (None, "", False))
        changes.append({
            "entry_id": q.id,
            "bracket_position": q.bracket_position,
            "kind": "filled",
            "old_name": None,
            "new_name": q.name,
            "old_entry_type": "Q",
            "new_entry_type": q.entry_type,
            "old_seed": None,
            "opponent": opp_name,
            "opponent_status": opp_status,
            "opponent_bye": opp_bye,
        })

    return {
        "id": draw.id,
        "name": draw.name,
        "gender": draw.gender,
        "category": draw.category,
        "label": _tournament_label(draw.name, draw.category or "", draw.gender or "M"),
        "tier": _tier_badge(draw.category or "", draw.gender),
        "locked": draw.is_locked,
        "changes": changes,
        "competitors": set(picked_entries.keys()),
        "picked_entries": picked_entries,
    }


async def _gather_draw_change_payload(db, draw: Draw, events: list) -> Optional[dict]:
    """
    One draw's pending swaps, plus who in that draw is affected by each.

    "Affected" is exact rather than inferred: the scraper rewrites DrawEntry in
    place, so a prediction whose predicted_winner_id equals the rewritten
    entry's id IS a pick on the player who just left. That user's bracket now
    silently backs someone they never chose, which is the entire reason this
    notification exists.
    """
    pick_res = await db.execute(
        select(UserPrediction.user_id, UserPrediction.predicted_winner_id).where(
            UserPrediction.draw_id == draw.id,
            UserPrediction.predicted_winner_id.isnot(None),
        )
    )
    picked_entries: dict[int, set] = defaultdict(set)
    for uid, entry_id in pick_res.all():
        picked_entries[uid].add(entry_id)
    if not picked_entries:
        # Nobody is competing in this draw, so nobody is affected by a change to
        # it. The events are still claimed by the caller — an unclaimed batch
        # would be reconsidered every ten minutes forever.
        return None

    from app.services.email import _tier_badge

    # Only the qualifier notification renders an opponent, but resolving it here
    # keeps the round-1 lookup to one query for the whole draw rather than one
    # per slot, and leaves the payload shape the same for both kinds.
    opponents = await _round1_matchups(
        db, draw.id, {e.entry_id for e in events if e.kind == "filled" and e.entry_id}
    )

    # IS THE PICK THIS MESSAGE IS ABOUT STILL CHANGEABLE?
    #
    # draw.is_locked answers for the DRAW, and under match-by-match locking it
    # stays False for hours after individual matches have started — so a swap
    # whose match is already on court was announced as "picks still open",
    # inviting a change the server would refuse. The honest question is about
    # the matches these events actually touch.
    from app.services.locking import match_in_play
    changed_entry_ids = {e.entry_id for e in events if e.entry_id}
    affected_open = False
    if changed_entry_ids:
        affected = (await db.execute(
            select(Match).where(
                Match.draw_id == draw.id,
                or_(Match.player1_id.in_(changed_entry_ids),
                    Match.player2_id.in_(changed_entry_ids))))).scalars().all()
        affected_open = any(not match_in_play(m) for m in affected)

    changes = []
    for e in sorted(events, key=lambda e: e.bracket_position):
        opp_name, opp_status, opp_bye = opponents.get(e.entry_id, (None, "", False))
        changes.append({
            "entry_id": e.entry_id,
            "bracket_position": e.bracket_position,
            "kind": e.kind,
            "old_name": e.old_name,
            "new_name": e.new_name,
            "old_entry_type": e.old_entry_type,
            "new_entry_type": e.new_entry_type,
            "old_seed": e.old_seed,
            "opponent": opp_name,
            "opponent_status": opp_status,
            "opponent_bye": opp_bye,
        })
    return {
        "id": draw.id,
        "name": draw.name,
        "gender": draw.gender,
        "category": draw.category,
        "label": _tournament_label(draw.name, draw.category or "", draw.gender or "M"),
        "tier": _tier_badge(draw.category or "", draw.gender),
        # Locked for this message's purposes when the draw is locked OR
        # every match it names has already started.
        "locked": draw.is_locked or not affected_open,
        "changes": changes,
        "competitors": set(picked_entries.keys()),
        "picked_entries": picked_entries,
    }


async def notify_draw_change_batch(draw_ids: list[int], kind: str = "replaced") -> None:
    """
    Tell everyone competing in these draws what moved in their bracket.

    `kind` selects both the events claimed and the message sent — "replaced" is
    the draw-change notification, "filled" is qualifiers-added. They are claimed
    separately so a draw with both pending sends one of each rather than a single
    message that opens with a warning and then lists routine slot fills.

    Audience is competitors only — a user with at least one pick in the draw,
    the same "participant" bar the standings and round digests use. Someone who
    has not entered has nothing to re-check, and neither message is an
    invitation to enter.

    Claim first, send second, exactly as notify_draw_release_batch does: the
    conditional UPDATE on notified_at is the guard, so a dispatch run overlapping
    the previous one finds nothing left to claim rather than sending twice.
    """
    from sqlalchemy import update as sa_update
    from app.services.email import send_draw_change_digest, send_qualifiers_added_digest
    from app.services.system_log import app_log
    from app.models.notification import DrawChangeEvent

    if not draw_ids:
        return

    is_qualifiers = kind == "filled"
    pref = _KIND_PREF[kind]

    async with AsyncSessionLocal() as db:
        now = datetime.now(tz.utc)

        # A draw announces its qualifying field exactly once. The unique primary
        # key is the hard guard; a draw that fails to claim drops out of the
        # batch, and its events are still stamped below so they do not queue
        # forever. Each claim gets its own savepoint so one already-announced
        # draw cannot abort the rest.
        if is_qualifiers:
            from sqlalchemy.exc import IntegrityError
            from app.models.notification import QualifiersAddedNotification
            fresh = []
            for draw_id in draw_ids:
                try:
                    async with db.begin_nested():
                        db.add(QualifiersAddedNotification(draw_id=draw_id))
                    fresh.append(draw_id)
                except IntegrityError:
                    logger.info("Qualifiers already announced for draw %d — "
                                "later placements reach users as draw changes", draw_id)
            await db.commit()
        else:
            fresh = list(draw_ids)

        claim = await db.execute(
            sa_update(DrawChangeEvent)
            .where(
                DrawChangeEvent.draw_id.in_(draw_ids),
                DrawChangeEvent.kind == kind,
                DrawChangeEvent.notified_at.is_(None),
            )
            .values(notified_at=now)
        )
        if claim.rowcount == 0:
            await db.rollback()
            logger.debug("%s batch %s already claimed — nothing to send", kind, draw_ids)
            return
        await db.commit()

        if not fresh:
            return

        claimed = (await db.execute(
            select(DrawChangeEvent).where(
                DrawChangeEvent.draw_id.in_(fresh),
                DrawChangeEvent.kind == kind,
                DrawChangeEvent.notified_at == now,
            )
        )).scalars().all()

        by_draw: dict[int, list] = defaultdict(list)
        for e in claimed:
            by_draw[e.draw_id].append(e)

        payloads = []
        # Qualifiers are keyed off the DRAW, not the events: the events say when
        # to send, the draw says what to send (see _gather_qualifier_payload).
        for draw_id in (fresh if is_qualifiers else list(by_draw.keys())):
            draw = await db.get(Draw, draw_id)
            if not draw:
                continue
            payload = (await _gather_qualifier_payload(db, draw) if is_qualifiers
                       else await _gather_draw_change_payload(db, draw, by_draw[draw_id]))
            if payload:
                payloads.append(payload)
        if not payloads:
            return

        # Everyone competing in at least one of the changed draws.
        candidates: set[int] = set()
        for p in payloads:
            candidates |= p["competitors"]

        pref_res = await db.execute(
            select(NotificationPreference.user_id)
            .join(User, User.id == NotificationPreference.user_id)
            .where(
                NotificationPreference.pref_key == pref,
                NotificationPreference.user_id.in_(candidates),
                User.email_verified == True,  # noqa: E712
            )
        )
        to_email = {r[0] for r in pref_res.all()}

        emails_res = await db.execute(select(User.id, User.email).where(User.id.in_(to_email)))
        emails = {r[0]: r[1] for r in emails_res.all()}

        await db.execute(
            sa_update(DrawChangeEvent)
            .where(DrawChangeEvent.notified_at == now,
                   DrawChangeEvent.kind == kind,
                   DrawChangeEvent.draw_id.in_([p["id"] for p in payloads]))
            .values(recipient_count=len(to_email))
        )
        if is_qualifiers:
            from app.models.notification import QualifiersAddedNotification
            for p in payloads:
                await db.execute(
                    sa_update(QualifiersAddedNotification)
                    .where(QualifiersAddedNotification.draw_id == p["id"])
                    .values(recipient_count=len(to_email),
                            qualifier_count=len(p["changes"]))
                )
        await db.commit()

    def _sections_for(uid: int) -> list[dict]:
        """This user's slice of the batch: only draws they compete in, with each
        change flagged when it is one of their own picks that moved."""
        out = []
        for p in payloads:
            if uid not in p["competitors"]:
                continue
            mine = p["picked_entries"].get(uid, set())
            out.append({
                **{k: p[k] for k in ("id", "name", "gender", "category", "label", "tier", "locked")},
                "changes": [{**c, "affects_you": c["entry_id"] in mine} for c in p["changes"]],
            })
        return out

    sent = 0
    for uid in to_email:
        email = emails.get(uid)
        sections = _sections_for(uid)
        if not email or not sections:
            continue
        send = send_qualifiers_added_digest if is_qualifiers else send_draw_change_digest
        try:
            await send(
                email, sections,
                unsubscribe_url=(
                    f"{API_BASE}/unsubscribe?token="
                    f"{create_unsubscribe_token(uid, pref)}"
                ),
            )
            sent += 1
        except Exception as exc:
            logger.warning("Failed to send %s email to user %d: %s", pref, uid, exc)

    # Push is built per user, unlike every other type here, because the one line
    # that matters most — whether the swap hit a pick of theirs — differs per
    # recipient and is what the collapsed notification leads with. Two shared
    # payloads would be cheaper and would tell half the audience the wrong thing.
    try:
        from app.services.push import send_push_to_users, users_with_push
        from app.services import push_content

        push_uids = set(await users_with_push(pref)) & candidates
        newest_event = max((e.id for e in claimed), default=0)
        builder = push_content.qualifiers_added if is_qualifiers else push_content.draw_change
        for uid in push_uids:
            sections = _sections_for(uid)
            if not sections:
                continue
            affected = any(c["affects_you"] for s in sections for c in s["changes"])
            content = builder(sections, affected, newest_event)
            await send_push_to_users([uid], **content)
    except Exception as exc:
        logger.warning("%s push failed: %s", pref, exc)

    total_changes = sum(len(p["changes"]) for p in payloads)
    label = "Qualifiers-added" if is_qualifiers else "Draw-change"
    await app_log("info", "notifications",
                  f"{label} notification sent to {sent} user(s) covering "
                  f"{total_changes} change(s) in {len(payloads)} draw(s)",
                  {"draw_ids": [p["id"] for p in payloads], "recipient_count": sent,
                   "changes": [change_line(c) for p in payloads for c in p["changes"]]})


# ---------------------------------------------------------------------------
# Standout-pick notification (a correct call most of the field missed)
# ---------------------------------------------------------------------------

STANDOUT_PICK_PREF = "standout_pick"

# A pick is a standout when strictly fewer than half the draw's competitors
# called the same match right. Strict, so a field split down the middle is not
# flattered into "you saw something they didn't".
STANDOUT_MAX_SHARE = 0.5

# Minimum number of competitors who actually picked the match before it can be
# called a standout. Below this the share is noise rather than insight — in a
# field of two the only outcomes are 0%, 50% and 100%, so every correct minority
# call is a solo one and says nothing about the pick.
#
# Measured on picks for THAT MATCH, not on entrants in the draw. It is the
# stricter of the two readings and implies the other: everyone who picked the
# match is by definition a participant, so prediction_count >= 6 guarantees
# participant_count >= 6 as well.
STANDOUT_MIN_PREDICTIONS = 6


async def record_standout_picks(db, draw: Draw, since=None) -> int:
    """
    Measure every newly-finished match in this draw against the field.

    Records a row for EVERY match measured, not just the standouts — the row is
    the claim, and a match that most of the field called right must be recorded
    too or the sweep would re-measure it on every pass forever.

    `since` bounds how far back an unmeasured match will be picked up. A match
    that finished before it is skipped silently and permanently: with no row of
    its own it stays a candidate, but it can never come back into the window, so
    the effect is the same as having been measured. That is what stops a draw
    whose participant pool changes late from suddenly qualifying a whole
    tournament's worth of old results for notification.

    Returns the number of matches newly measured. Does not commit; the caller
    owns the transaction.
    """
    from app.models.notification import StandoutPickNotification

    participants_res = await db.execute(
        select(UserPrediction.user_id)
        .where(
            UserPrediction.draw_id == draw.id,
            UserPrediction.predicted_winner_id.isnot(None),
        )
        .group_by(UserPrediction.user_id)
    )
    participants = {r[0] for r in participants_res.all()}
    # No match in a draw this small can clear the prediction floor, since every
    # picker of a match is one of these participants.
    if len(participants) < STANDOUT_MIN_PREDICTIONS:
        return 0

    measured_res = await db.execute(
        select(StandoutPickNotification.match_id).where(
            StandoutPickNotification.draw_id == draw.id
        )
    )
    measured = {r[0] for r in measured_res.all()}

    # is_bye excluded for the same reason it is everywhere else: nobody predicted
    # a contest that was never played, and stray picks do exist on those rows.
    q = select(Match).where(
        Match.draw_id == draw.id,
        Match.winner_id.isnot(None),
        Match.is_bye == False,  # noqa: E712
    )
    if since is not None:
        # completed_at is null on results imported before it was stamped, and a
        # null must not read as "recent" — those are exactly the historical rows
        # this window exists to exclude.
        q = q.where(Match.completed_at.isnot(None), Match.completed_at >= since)
    matches_res = await db.execute(q)
    fresh = [m for m in matches_res.scalars().all() if m.id not in measured]
    if not fresh:
        return 0

    picks_res = await db.execute(
        select(UserPrediction.match_id, UserPrediction.user_id, UserPrediction.predicted_winner_id)
        .where(UserPrediction.match_id.in_([m.id for m in fresh]))
    )
    correct_by_match: dict[int, set] = defaultdict(set)
    picked_by_match: dict[int, set] = defaultdict(set)
    winner_of = {m.id: m.winner_id for m in fresh}
    for match_id, uid, picked in picks_res.all():
        if uid not in participants or picked is None:
            continue
        picked_by_match[match_id].add(uid)
        if picked == winner_of.get(match_id):
            correct_by_match[match_id].add(uid)

    for m in fresh:
        db.add(StandoutPickNotification(
            match_id=m.id,
            draw_id=draw.id,
            correct_count=len(correct_by_match.get(m.id, ())),
            participant_count=len(participants),
            prediction_count=len(picked_by_match.get(m.id, ())),
        ))
    return len(fresh)


async def _gather_standout_payload(db, rows: list) -> list[dict]:
    """
    Turn measured matches into per-match payloads, keeping only the standouts.

    A row with nobody correct is dropped here rather than filtered at the
    recording step: it still had to be recorded (see record_standout_picks), it
    simply has no audience.
    """
    from app.services.email import _tier_badge

    keep = [
        r for r in rows
        if r.correct_count
        and r.prediction_count >= STANDOUT_MIN_PREDICTIONS
        and r.participant_count > 0
        and r.correct_count / r.participant_count < STANDOUT_MAX_SHARE
    ]
    if not keep:
        return []

    matches_res = await db.execute(
        select(Match)
        .options(selectinload(Match.player1), selectinload(Match.player2), selectinload(Match.winner))
        .where(Match.id.in_([r.match_id for r in keep]))
    )
    match_by_id = {m.id: m for m in matches_res.scalars().all()}

    # Who was right, per match, in one query. The frozen correct_count on the row
    # is the historical measure of the field; this is the audience to notify, and
    # it is re-read rather than derived from that count because the two can
    # legitimately disagree (an admin editing picks between measurement and
    # send). The audience must be whoever actually holds the pick now.
    winner_of = {m.id: m.winner_id for m in match_by_id.values()}
    picked_winner_res = await db.execute(
        select(UserPrediction.match_id, UserPrediction.user_id, UserPrediction.predicted_winner_id)
        .where(UserPrediction.match_id.in_([r.match_id for r in keep]))
    )
    correct_by_match: dict[int, set] = defaultdict(set)
    for match_id, uid, picked in picked_winner_res.all():
        if picked is not None and picked == winner_of.get(match_id):
            correct_by_match[match_id].add(uid)

    out = []
    for r in keep:
        m = match_by_id.get(r.match_id)
        if not m or not m.winner or not m.player1 or not m.player2:
            continue
        draw = await db.get(Draw, r.draw_id)
        if not draw:
            continue
        loser = m.player2 if m.winner_id == m.player1_id else m.player1
        correct_now = correct_by_match.get(r.match_id, set())
        if not correct_now:
            continue
        out.append({
            "match_id": m.id,
            "draw_id": draw.id,
            "draw_name": draw.name,
            "gender": draw.gender,
            "category": draw.category,
            "label": _tournament_label(draw.name, draw.category or "", draw.gender or "M"),
            "tier": _tier_badge(draw.category or "", draw.gender),
            "round_name": _email_round_label(draw.round_name(m.round_number)),
            "winner": m.winner.name,
            "loser": loser.name,
            "score": _match_score_str(m),
            "correct_count": r.correct_count,
            "participant_count": r.participant_count,
            "correct_users": correct_now,
        })
    # Rarest call first — that is the one worth leading with when a user has
    # several, and the one whose draw the notification links to.
    out.sort(key=lambda p: p["correct_count"] / p["participant_count"])
    return out


async def notify_standout_picks(match_ids: list[int]) -> None:
    """
    One message per user covering every minority-correct call they just made.

    Batched rather than per match: a round finishing writes results in waves,
    and a user who called three of them right wants one notification listing
    three, not three notifications.
    """
    from sqlalchemy import update as sa_update
    from app.services.email import send_standout_pick_digest
    from app.services.system_log import app_log
    from app.models.notification import StandoutPickNotification

    if not match_ids:
        return

    async with AsyncSessionLocal() as db:
        now = datetime.now(tz.utc)
        claim = await db.execute(
            sa_update(StandoutPickNotification)
            .where(
                StandoutPickNotification.match_id.in_(match_ids),
                StandoutPickNotification.notified_at.is_(None),
            )
            .values(notified_at=now)
        )
        if claim.rowcount == 0:
            await db.rollback()
            logger.debug("Standout-pick batch already claimed — nothing to send")
            return
        await db.commit()

        rows = (await db.execute(
            select(StandoutPickNotification).where(
                StandoutPickNotification.match_id.in_(match_ids),
                StandoutPickNotification.notified_at == now,
            )
        )).scalars().all()

        payloads = await _gather_standout_payload(db, rows)
        if not payloads:
            return

        candidates: set[int] = set()
        for p in payloads:
            candidates |= p["correct_users"]
        if not candidates:
            return

        pref_res = await db.execute(
            select(NotificationPreference.user_id)
            .join(User, User.id == NotificationPreference.user_id)
            .where(
                NotificationPreference.pref_key == STANDOUT_PICK_PREF,
                NotificationPreference.user_id.in_(candidates),
                User.email_verified == True,  # noqa: E712
            )
        )
        to_email = {r[0] for r in pref_res.all()}
        emails_res = await db.execute(select(User.id, User.email).where(User.id.in_(to_email)))
        emails = {r[0]: r[1] for r in emails_res.all()}

        await db.execute(
            sa_update(StandoutPickNotification)
            .where(StandoutPickNotification.match_id.in_([p["match_id"] for p in payloads]))
            .values(recipient_count=len(to_email))
        )
        await db.commit()

    def _picks_of(uid: int) -> list[dict]:
        return [p for p in payloads if uid in p["correct_users"]]

    sent = 0
    for uid in to_email:
        email = emails.get(uid)
        picks = _picks_of(uid)
        if not email or not picks:
            continue
        try:
            await send_standout_pick_digest(
                email, picks,
                unsubscribe_url=(
                    f"{API_BASE}/unsubscribe?token="
                    f"{create_unsubscribe_token(uid, STANDOUT_PICK_PREF)}"
                ),
            )
            sent += 1
        except Exception as exc:
            logger.warning("Failed to send standout-pick email to user %d: %s", uid, exc)

    # Per-user push for the same reason the email is per-user: the whole content
    # is "the calls YOU made that the field missed". There is no shared payload
    # that could be correct for two different recipients.
    try:
        from app.services.push import send_push_to_users, users_with_push
        from app.services import push_content

        push_uids = set(await users_with_push(STANDOUT_PICK_PREF)) & candidates
        for uid in push_uids:
            picks = _picks_of(uid)
            if not picks:
                continue
            await send_push_to_users([uid], **push_content.standout_pick(picks))
    except Exception as exc:
        logger.warning("Standout-pick push failed: %s", exc)

    await app_log("info", "notifications",
                  f"Standout-pick notification sent to {sent} user(s) covering "
                  f"{len(payloads)} match(es)",
                  {"match_ids": [p["match_id"] for p in payloads],
                   "recipient_count": sent,
                   "picks": [f"{p['winner']} def. {p['loser']} "
                             f"({p['correct_count']}/{p['participant_count']})" for p in payloads]})


# ---------------------------------------------------------------------------
# Tournament results persistence
# ---------------------------------------------------------------------------

async def _persist_tournament_results(
    db,
    tournament_id: int,
    all_participants: set,
    preds_by_user: dict,
    completed_matches: list,
    tournament,
    all_leagues: list,
) -> None:
    """Upsert TournamentResult rows for every participant in every group."""
    from datetime import datetime, timezone as tz
    from app.models.draw_history import TournamentResult

    now = datetime.now(tz.utc).replace(tzinfo=None)

    # Global scores
    global_scores = {
        uid: score_user(uid, preds_by_user[uid], completed_matches, tournament, None)
        for uid in all_participants
    }
    global_ranked = rank_users(list(global_scores.values()), tournament.num_rounds)
    global_rank_of = {s.user_id: i + 1 for i, s in enumerate(global_ranked)}
    global_total = len(all_participants)

    rows = []
    for uid in all_participants:
        s = global_scores[uid]
        rows.append({
            "user_id": uid,
            "draw_id": tournament_id,
            "league_id": None,
            "league_name": "Global",
            "rank": global_rank_of[uid],
            "total_participants": global_total,
            "points": s.total_points,
            "correct_count": s.correct_count,
            "saved_at": now,
        })

    # Per-league scores
    for lg in all_leagues:
        member_ids = {m.user_id for m in lg.members}
        participants = all_participants & member_ids
        if len(participants) < 2:
            continue
        lg_scores = {
            uid: score_user(uid, preds_by_user[uid], completed_matches, tournament, None)
            for uid in participants
        }
        lg_ranked = rank_users(list(lg_scores.values()), tournament.num_rounds)
        lg_rank_of = {s.user_id: i + 1 for i, s in enumerate(lg_ranked)}
        for uid in participants:
            s = lg_scores[uid]
            rows.append({
                "user_id": uid,
                "draw_id": tournament_id,
                "league_id": lg.id,
                "league_name": lg.name,
                "rank": lg_rank_of[uid],
                "total_participants": len(participants),
                "points": s.total_points,
                "correct_count": s.correct_count,
                "saved_at": now,
            })

    # Delete existing results for this tournament before re-inserting.
    # ON CONFLICT DO UPDATE cannot match NULL league_id in SQLite (NULL != NULL),
    # so upsert silently inserts duplicates for Global rows.
    from sqlalchemy import delete as _delete
    await db.execute(_delete(TournamentResult).where(TournamentResult.draw_id == tournament_id))
    for row in rows:
        db.add(TournamentResult(**row))
    await db.commit()
    logger.info("Saved %d result row(s) for tournament %d", len(rows), tournament_id)


# ---------------------------------------------------------------------------
# Draw completion — persist final standings (no email; see below)
# ---------------------------------------------------------------------------

async def notify_tournament_complete(tournament_id: int) -> None:
    """
    Persist final standings to draw history for every participant.

    **Sends nothing.** This used to email each participant a per-draw "Final
    Standings" message the moment its final ended, which meant one email per
    tournament — four in a week where four draws finish. The result of a draw
    now arrives in the Final-round entry of the weekly round digest
    (notify_round_complete_digest), which already carries the same match
    results, pick ✓/✗ and league standings for every draw that finished that
    week, in one message.

    Draw history is a different concern and stays here: it is recorded for ALL
    participants (not just the opted-in, not just complete brackets) and must
    land when the draw ends, not when an email happens to go out.

    Idempotent: claims (draw_id) in tournament_complete_notifications before
    doing any work — the unique-constrained primary key is the hard guard.
    Draw.completion_notified_at is kept as a cheap early-exit column, but a
    plain check-then-set-then-commit column alone isn't safe against two
    overlapping callers (this function can be triggered by the same
    process-restart race documented on MatchStartNotification), so it's no
    longer the sole guard.
    """
    from sqlalchemy.exc import IntegrityError
    from app.services.system_log import app_log
    from app.models.notification import TournamentCompleteNotification
    from datetime import datetime, timezone as tz

    async with AsyncSessionLocal() as db:
        tournament = await db.get(Draw, tournament_id)
        if not tournament:
            return

        if tournament.completion_notified_at is not None:
            return  # cheap early exit — the claim insert below is the real guard
        tournament.completion_notified_at = datetime.now(tz.utc)
        db.add(TournamentCompleteNotification(draw_id=tournament_id))
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            await app_log(
                "warning", "notifications",
                f"Draw {tournament_id} completion already recorded — re-run blocked",
                {"tournament_id": tournament_id},
                dedup_key=f"tournament-complete-dupe-{tournament_id}",
            )
            return

        # All completed matches (needed for scoring)
        m_res = await db.execute(
            select(Match)
            .options(selectinload(Match.player1), selectinload(Match.player2), selectinload(Match.winner))
            # is_bye excluded: a bye is not a contest. It is stamped completed with
            # an auto-advanced winner, and stray picks do exist on those rows, so
            # scoring them hands out free points (see _persist_tournament_results).
            .where(Match.draw_id == tournament_id, Match.status == "completed",
                   Match.is_bye == False)  # noqa: E712
        )
        completed_matches = m_res.scalars().all()

        total_res = await db.execute(
            select(func.count()).where(
                Match.draw_id == tournament_id,
                Match.is_bye == False,
            )
        )
        total_matches = total_res.scalar_one()
        if total_matches == 0:
            return

        # All predictions for this tournament
        pred_res = await db.execute(
            select(UserPrediction).where(
                UserPrediction.draw_id == tournament_id,
                UserPrediction.predicted_winner_id.isnot(None),
            )
        )
        all_preds = pred_res.scalars().all()

        preds_by_user: dict[int, list] = defaultdict(list)
        for p in all_preds:
            preds_by_user[p.user_id].append(p)

        # Every user with any predictions — a partial bracket competes and is
        # ranked alongside the rest, so it belongs in draw history too.
        all_participants = set(preds_by_user.keys())

        # Load all leagues (needed for both results persistence and notifications)
        lg_res = await db.execute(
            select(League).options(selectinload(League.members))
        )
        all_leagues = lg_res.scalars().all()

        # Persist final standings for ALL participants (draw history)
        if all_participants:
            await _persist_tournament_results(
                db, tournament_id, all_participants, preds_by_user,
                completed_matches, tournament, all_leagues,
            )

        logger.info(
            "Draw %d complete — final standings recorded for %d participant(s); "
            "the result reaches users in this week's Final-round digest",
            tournament_id, len(all_participants),
        )
