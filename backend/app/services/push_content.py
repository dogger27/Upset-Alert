"""
What each push notification says.

Separated from the code that decides WHEN to send so the "send me a test of
this type" button can reproduce a real notification exactly rather than
approximating one — an approximation is worthless for the thing tests are for,
which is seeing what will actually land on your phone.

Bodies are written for the EXPANDED notification, not the collapsed one. Android
shows a couple of lines until it's pressed and held, then the whole thing, so
the useful detail (which draws, when they close, how many matches) belongs here
rather than being trimmed away to fit a preview nobody reads twice.
"""

from typing import Optional

# Android's expanded view will show far more than the collapsed two lines; this
# is only a guard against an absurd payload, not a display budget.
MAX_BODY = 900

# Item caps for the two list-shaped notifications. MAX_BODY alone is not enough:
# it slices mid-word, so a long batch ended "... — 2 of 6 got" with no way for
# the reader to tell whether that was the end. These cap the item COUNT and say
# how many were left out, which is both honest and readable. A round of 64
# finishing can genuinely produce a dozen minority-correct picks for one user.
MAX_LISTED_CHANGES = 8
MAX_LISTED_PICKS = 5
# Qualifier placements are listed in full, not sampled: this notification says
# "here is who is in the draw now", and a truncated answer to that is worse than
# none. Sixteen covers a Grand Slam's full complement (a 1000 has twelve), and
# at roughly 35 characters a matchup the whole list still clears MAX_BODY.
MAX_LISTED_QUALIFIERS = 16


def tour_label(gender: str) -> str:
    """'ATP' / 'WTA'. Never '(M)' / '(F)'.

    The tour is what the sport calls itself and what a reader recognises at a
    glance; M/F is a database column leaking into a notification. One helper so
    the two can never drift apart across the six places this is rendered.
    """
    return "ATP" if gender == "M" else "WTA"


def tier_label(category: Optional[str], gender: str) -> str:
    """'ATP 1000', 'WTA 500', 'ATP Grand Slam'.

    The tour prefix is always present, including for majors — email's badge
    renders a bare "Grand Slam", which would make the men's and women's lines of
    a Slam week identical here.
    """
    cat = (category or "").upper()
    tour = tour_label(gender)
    if "SLAM" in cat or "GRAND" in cat:
        return f"{tour} Grand Slam"
    tier = "1000" if "1000" in cat else "500" if "500" in cat else "250"
    return f"{tour} {tier}"


def draw_release(draws: list[dict], week_label: str) -> dict:
    """
    draws: [{name, gender, category}, ...] soonest deadline first.

    Name and tier only. Locations and pick deadlines were in here and made a
    six-draw week an unreadable slab on the lock screen — the deadline is on the
    site, and the notification's job is to say which tournaments are open.

    The title deliberately carries NO tournament name. It used to ("Canadian Open
    draws released") and iOS truncated it to "Canadian Open draws…", spending the
    whole line to say less than two words would. Every draw is named in the body
    with its tier, so the name is not lost — it moves to where there is room for
    all of them rather than just the first.
    """
    n = len(draws)
    title = "Draw Released" if n == 1 else "Draws Released"

    lines = [f"{d['name']} · {tier_label(d.get('category'), d['gender'])}" for d in draws]
    body = "\n".join(lines) or "Make your picks before they close."

    return {
        "title": title,
        "body": body[:MAX_BODY],
        "url": "/",
        "tag": f"draw-release-{week_label}",
        "actions": [{"action": "open", "title": "Make picks", "url": "/"}],
    }


def round_complete(
    round_name: str,
    where: str,
    draws: list[dict],
    is_final: bool,
) -> dict:
    """
    draws: [{name, gender, category}, ...] — EVERY draw the digest covers.

    A round digest batches the men's and women's draws of an event (and a whole
    week of smaller events), so listing one of them describes the email wrongly:
    "R32 complete — Canadian Open" with a single ATP line reads as though the
    WTA draw hadn't reported. Same name · tier lines as draw-release, so the two
    notification types are scannable the same way.

    `where` no longer appears in the title — "R32 complete — Canadian Open"
    arrived as "R32 complete — Cana…", and the body names every draw in the
    batch anyway, which is strictly more than the title could fit. It still
    keys the tag, where it stops one event's digest replacing another's.
    """
    title = "Final Standings" if is_final else f"{round_name} Complete"

    body = "\n".join(
        f"{d['name']} · {tier_label(d.get('category'), d['gender'])}" for d in draws
    ) or "See how your picks did"

    return {
        "title": title,
        "body": body[:MAX_BODY],
        "url": "/leagues",
        "tag": f"round-{round_name}-{where}",
        "actions": [{"action": "open", "title": "View standings", "url": "/leagues"}],
    }


def draw_change(draws: list[dict], affects_your_picks: bool, event_seq: int = 0) -> dict:
    """
    draws: [{name, gender, category, id, changes: [...]}, ...] — this ONE user's
    slice of the batch, with each change carrying affects_you.

    The body is the list of swaps, because that is the only thing a reader can
    act on: knowing "the draw changed" without knowing who left tells them
    nothing, and sends them to the site to find out. Expanded, they see every
    swap; collapsed, they see the two lines that matter most, which is why the
    warning about their own picks is first when there is one.

    event_seq is the highest change id in the batch, and only exists to keep the
    tag unique. A tag that repeated would have the second swap of a tournament
    REPLACE the first on the lock screen — two separate events, one of them
    silently gone.
    """
    from app.services.draw_changes import change_line

    total = sum(len(d["changes"]) for d in draws)
    # No tournament name in the title — it truncated ("Draw change — Cincin…").
    # The name is the body's first line instead, where it has the width to
    # survive alongside its tier.
    title = "Draw Changes Made"

    def header(d):
        return f"{d['name']} · {tier_label(d.get('category'), d['gender'])}"

    lines, shown = [], 0
    if len(draws) == 1:
        # Name first, then the warning: the reader needs to know WHICH draw
        # before being told something in it moved.
        lines.append(header(draws[0]))
        if affects_your_picks:
            lines.append("⚠️ One of your picks was replaced.")
        for c in draws[0]["changes"][:MAX_LISTED_CHANGES]:
            lines.append(change_line(c))
            shown += 1
    else:
        # Across several draws the warning belongs to no single one, so it leads.
        if affects_your_picks:
            lines.append("⚠️ One of your picks was replaced.")
        for d in draws:
            if shown >= MAX_LISTED_CHANGES:
                break
            lines.append(header(d))
            for c in d["changes"][:MAX_LISTED_CHANGES - shown]:
                lines.append("• " + change_line(c))
                shown += 1
    if total > shown:
        lines.append(f"…and {total - shown} more change{'' if total - shown == 1 else 's'}")

    url = f"/tournaments/{draws[0]['id']}" if len(draws) == 1 else "/"
    return {
        "title": title,
        "body": "\n".join(lines)[:MAX_BODY],
        "url": url,
        "tag": f"draw-change-{event_seq}",
        "actions": [{"action": "open", "title": "Check your picks", "url": url}],
    }


def matchup_line(change: dict) -> str:
    """'Flavio Cobolli vs Arthur Fils [1]' — a placed qualifier and who they drew.

    The opponent is the point. A list of qualifier names is a list of strangers;
    the same list against their first-round opponents tells a competitor whether
    anything in their bracket just got harder. The seed (or entry type) rides
    along in brackets, because "vs Alcaraz" and "vs Alcaraz [1]" are different
    pieces of news.
    """
    from app.services.draw_changes import entry_suffix, last_name

    # The (Q) is not decoration: in a list of two names per line, it is the only
    # thing marking which of them is the qualifier. Read from the entry rather
    # than hardcoded, so a slot that resolved to something else (LL taking an
    # unclaimed qualifying spot) is labelled as what it actually is.
    name = last_name(change["new_name"]) + entry_suffix(change.get("new_entry_type"))
    if change.get("opponent_bye"):
        return f"{name} — bye"
    opp = change.get("opponent")
    if not opp:
        return f"{name} — opponent TBD"
    status = change.get("opponent_status")
    return f"{name} vs {last_name(opp)}" + (f" [{status}]" if status else "")


def qualifiers_added(draws: list[dict], affects_your_picks: bool, event_seq: int = 0) -> dict:
    """
    draws: [{name, gender, category, id, changes: [...]}, ...] — this user's
    slice, each change a placed qualifier carrying its round-1 opponent.

    Separate from draw_change because it is separate news: the draw is now
    complete, and every line is a matchup rather than a loss. Nothing here is a
    warning, so nothing here leads with one — a competitor who picked a qualifier
    slot gets a note at the end, since their pick has followed the slot and is
    now a real player rather than a placeholder.

    Every matchup is listed rather than the first few: MAX_LISTED_QUALIFIERS
    covers a Slam's full sixteen, and a partial list of "who's in the draw now"
    is the one thing this notification cannot usefully be.
    """
    from app.services.draw_changes import dedupe_matchups

    # The headline counts QUALIFIERS; the list shows MATCHES. They differ when
    # two qualifiers are drawn against each other, and both numbers are true.
    # The headline counts QUALIFIERS; the list shows MATCHES. They differ when
    # two qualifiers are drawn against each other, and both numbers are true.
    #
    # The count stays in the title (it is short and cannot truncate) but the
    # tournament name does not — that is the part that got cut. It leads the
    # body instead, the same shape as every other type.
    total = sum(len(d["changes"]) for d in draws)
    # A Q/LL slot can resolve either way, so the batch is usually qualifiers with
    # a lucky loser or two among them — "Qualifiers Added" covers that. A batch
    # of nothing BUT lucky losers would not, so it says so.
    only_ll = total > 0 and all(
        (c.get("new_entry_type") or "").upper() == "LL"
        for d in draws for c in d["changes"]
    )
    noun = "Lucky Loser" if only_ll else "Qualifier"
    title = f"{noun} Added" if total == 1 else f"{total} {noun}s Added"

    matches = {id(d): dedupe_matchups(d["changes"]) for d in draws}
    total_matches = sum(len(m) for m in matches.values())

    lines, shown = [], 0
    for d in draws:
        if shown >= MAX_LISTED_QUALIFIERS:
            break
        lines.append(f"{d['name']} · {tier_label(d.get('category'), d['gender'])}")
        for c in matches[id(d)][:MAX_LISTED_QUALIFIERS - shown]:
            lines.append(matchup_line(c))
            shown += 1
    if total_matches > shown:
        lines.append(f"…and {total_matches - shown} more")
    if affects_your_picks:
        lines.append("You picked one of these slots — it's a real player now.")

    url = f"/tournaments/{draws[0]['id']}" if len(draws) == 1 else "/"
    return {
        "title": title,
        "body": "\n".join(lines)[:MAX_BODY],
        "url": url,
        "tag": f"qualifiers-added-{event_seq}",
        "actions": [{"action": "open", "title": "View draw", "url": url}],
    }


def standout_pick(picks: list[dict]) -> dict:
    """
    picks: [{draw_name, gender, category, draw_id, winner, loser,
             correct_count, participant_count}, ...] rarest call first.

    One user's correct calls that most of the field missed.

    The result leads the BODY, not the title, and that placement is load-bearing.
    A newline in the title does not break the line on iOS — it truncates there,
    silently dropping everything after it, so "You called it!\\nBergs def. Fritz"
    arrived as bare "You called it!" with the result gone. The title is therefore
    one short line, and the result is the body's first line, which lands
    immediately under the OS's "from Upset Alert" — near enough to the intended
    reading, and the attribution line between them is not ours to move.

    Everything here is written for the COLLAPSED banner, which shows several
    lines and is where this will actually be read. So each line has to fit
    without wrapping: the round ("· R32") was the one thing pushing the draw line
    onto a second row, and it is dropped. The email keeps it, having room.

    The share is a percentage as well as a fraction — "2 / 11" needs arithmetic
    before it means anything, "(18%)" does not. The set-by-set score is
    deliberately absent: it says nothing about the pick being a standout, which
    is the only reason this notification exists.

    Ordered rarest-first by the caller, so the batch leads with its best call and
    the link points at that draw.
    """
    n = len(picks)
    top = picks[0]

    lines = []
    for p in picks[:MAX_LISTED_PICKS]:
        share = round(100 * p["correct_count"] / p["participant_count"])
        lines.append(
            f"{p['winner']} def. {p['loser']}\n"
            f"{p['draw_name']} · {tier_label(p.get('category'), p['gender'])}\n"
            f"Only {p['correct_count']} / {p['participant_count']} ({share}%) got this!"
        )
    if n > MAX_LISTED_PICKS:
        lines.append(f"…and {n - MAX_LISTED_PICKS} more")

    # Constant regardless of batch size: it is the one line guaranteed not to
    # wrap, and the body enumerates whatever else is in there.
    title = "You called it!"

    url = f"/tournaments/{top['draw_id']}"
    return {
        "title": title,
        "body": "\n\n".join(lines)[:MAX_BODY],
        "url": url,
        # Keyed on the matches themselves: two different batches must never
        # collapse into one another on the lock screen.
        "tag": "standout-" + "-".join(str(p["match_id"]) for p in picks[:4]),
        "actions": [{"action": "open", "title": "View draw", "url": url}],
    }


def league_join(new_username: str, league_name: str, league_id: int) -> dict:
    """
    Fixed title, names in the body — the same shape as every other type.

    Both names are variable length, so a title carrying them truncated exactly
    as the tournament ones did. The body says it once, plainly, instead of the
    old title/body pair that said the same thing twice in different words.
    """
    return {
        "title": "New League Member",
        "body": f"@{new_username} joined {league_name}",
        "url": f"/leagues/{league_id}",
        "tag": f"league-join-{league_id}",
        "actions": [{"action": "open", "title": "View league", "url": f"/leagues/{league_id}"}],
    }


def sample(pref_key: str) -> dict:
    """
    Stand-in for a type that has never fired, so the test button still shows the
    shape of the thing rather than erroring.
    """
    return {
        "draw_released": {
            "title": "Draws Released",
            "body": "Cincinnati Open · ATP 1000\nCincinnati Open · WTA 1000",
            "url": "/",
            "tag": "sample-draw-release",
            "actions": [{"action": "open", "title": "Make picks", "url": "/"}],
        },
        "round_standings": {
            "title": "R16 Complete",
            "body": "Canadian Open · ATP 1000\nCanadian Open · WTA 1000",
            "url": "/leagues",
            "tag": "sample-round",
            "actions": [{"action": "open", "title": "View standings", "url": "/leagues"}],
        },
        "tournament_end": {
            "title": "Final Standings",
            "body": "Canadian Open · ATP 1000\nCanadian Open · WTA 1000",
            "url": "/leagues",
            "tag": "sample-final",
            "actions": [{"action": "open", "title": "View standings", "url": "/leagues"}],
        },
        "league_member_joined": {
            "title": "New League Member",
            "body": "@dwightcharles joined BetaTesters",
            "url": "/leagues",
            "tag": "sample-league-join",
            "actions": [{"action": "open", "title": "View league", "url": "/leagues"}],
        },
        "draw_changed": {
            "title": "Draw Changes Made",
            "body": "Cincinnati Open · ATP 1000\n"
                    "⚠️ One of your picks was replaced.\nFils → Bergs (LL)",
            "url": "/",
            "tag": "sample-draw-change",
            "actions": [{"action": "open", "title": "Check your picks", "url": "/"}],
        },
        # Last resort only: _latest_content rebuilds this from the most recent
        # draw that actually has a qualifying field, because an invented
        # three-qualifier ATP 1000 is a number that event cannot produce.
        "qualifiers_added": {
            "title": "12 Qualifiers Added",
            "body": "Cincinnati Open · ATP 1000\nCobolli (Q) vs Fils\n"
                    "Bergs (Q) vs Alcaraz [1]\nDamm (Q) vs de Minaur [7]\n…and 9 more",
            "url": "/",
            "tag": "sample-qualifiers-added",
            "actions": [{"action": "open", "title": "View draw", "url": "/"}],
        },
        "standout_pick": {
            "title": "You called it!",
            "body": "Bergs def. Fritz\nCincinnati Open · ATP 1000\n"
                    "Only 2 / 11 (18%) got this!",
            "url": "/",
            "tag": "sample-standout",
            "actions": [{"action": "open", "title": "View draw", "url": "/"}],
        },
    }.get(pref_key, {
        "title": "Upset Alert test",
        "body": "Push notifications are working on this device.",
        "url": "/",
        "tag": "sample",
    })
