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
    }.get(pref_key, {
        "title": "Upset Alert test",
        "body": "Push notifications are working on this device.",
        "url": "/",
        "tag": "sample",
    })
