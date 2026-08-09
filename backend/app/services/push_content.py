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


def tier_label(category: Optional[str], gender: str) -> str:
    """'ATP 1000', 'WTA 500', 'ATP Grand Slam'.

    The tour prefix is always present, including for majors — email's badge
    renders a bare "Grand Slam", which would make the men's and women's lines of
    a Slam week identical here.
    """
    cat = (category or "").upper()
    tour = "ATP" if gender == "M" else "WTA"
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
    """
    n = len(draws)
    names = {d["name"] for d in draws}
    labelled = [f"{d['name']} ({d['gender']})" for d in draws]

    # One event (a Slam or 1000 is two draws of the same tournament) reads by
    # name; a genuinely mixed week can only be described by its date.
    if len(names) == 1:
        name = draws[0]["name"]
        title = (f"{name} ({draws[0]['gender']}) draw released" if n == 1
                 else f"{name} draws released")
    else:
        title = f"{n} draws released — {week_label}"

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
    """
    title = (f"Final standings — {where}" if is_final
             else f"{round_name} complete — {where}")

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
    if len(draws) == 1:
        d = draws[0]
        where = f"{d['name']} ({d['gender']})"
        title = f"Draw change — {where}" if total == 1 else f"{total} draw changes — {where}"
    else:
        title = f"{total} draw changes — {len(draws)} draws"

    lines = []
    if affects_your_picks:
        lines.append("⚠️ One of your picks was replaced.")
    shown = 0
    for d in draws:
        if shown >= MAX_LISTED_CHANGES:
            break
        if len(draws) > 1:
            lines.append(f"{d['name']} · {tier_label(d.get('category'), d['gender'])}")
        for c in d["changes"][:MAX_LISTED_CHANGES - shown]:
            lines.append(("• " if len(draws) > 1 else "") + change_line(c))
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


def standout_pick(picks: list[dict]) -> dict:
    """
    picks: [{draw_name, gender, category, draw_id, winner, loser, score,
             correct_count, participant_count}, ...] rarest call first.

    One user's correct calls that most of the field missed. The body names the
    draw, both players and who won — the three things needed to remember the
    pick without opening anything — and the tap goes to that draw, which is
    where the bracket showing it lives.

    Ordered rarest-first by the caller, so the single line a collapsed
    notification shows is the best call of the batch, and the link points at its
    draw when the batch spans several.
    """
    n = len(picks)
    top = picks[0]
    if n == 1:
        title = f"You called it — {top['winner']} def. {top['loser']}"
    else:
        title = f"{n} picks the field missed"

    lines = []
    for p in picks[:MAX_LISTED_PICKS]:
        head = f"{p['draw_name']} · {tier_label(p.get('category'), p['gender'])} · {p['round_name']}"
        result = f"{p['winner']} def. {p['loser']}"
        if p.get("score"):
            result += f" {p['score']}"
        lines.append(f"{head}\n{result} — {p['correct_count']} of "
                     f"{p['participant_count']} got it")
    if n > MAX_LISTED_PICKS:
        lines.append(f"…and {n - MAX_LISTED_PICKS} more")

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
    return {
        "title": f"{new_username} joined {league_name}",
        "body": f"{new_username} is now competing in {league_name}.",
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
            "title": "Cincinnati Open draws released",
            "body": "Cincinnati Open · ATP 1000\nCincinnati Open · WTA 1000",
            "url": "/",
            "tag": "sample-draw-release",
            "actions": [{"action": "open", "title": "Make picks", "url": "/"}],
        },
        "round_standings": {
            "title": "R16 complete — Canadian Open",
            "body": "2 draws reported\nCanadian Open ATP1000 · 8 matches · 3 upsets\n"
                    "Canadian Open WTA1000 · 8 matches · 2 upsets",
            "url": "/leagues",
            "tag": "sample-round",
            "actions": [{"action": "open", "title": "View standings", "url": "/leagues"}],
        },
        "tournament_end": {
            "title": "Final standings — Canadian Open",
            "body": "2 draws reported\nCanadian Open ATP1000 · 1 match · 1 upset",
            "url": "/leagues",
            "tag": "sample-final",
            "actions": [{"action": "open", "title": "View standings", "url": "/leagues"}],
        },
        "league_member_joined": {
            "title": "someone joined your league",
            "body": "A new competitor is now in one of your leagues.",
            "url": "/leagues",
            "tag": "sample-league-join",
            "actions": [{"action": "open", "title": "View league", "url": "/leagues"}],
        },
        "draw_changed": {
            "title": "2 draw changes — Cincinnati Open (M)",
            "body": "⚠️ One of your picks was replaced.\n"
                    "Arthur Fils → Zizou Bergs (LL)\nQualifier → Flavio Cobolli (Q)",
            "url": "/",
            "tag": "sample-draw-change",
            "actions": [{"action": "open", "title": "Check your picks", "url": "/"}],
        },
        "standout_pick": {
            "title": "You called it — Bergs def. Fritz",
            "body": "Cincinnati Open · ATP 1000 · R32\n"
                    "Bergs def. Fritz 7-6, 4-6, 6-3 — 2 of 11 got it",
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
