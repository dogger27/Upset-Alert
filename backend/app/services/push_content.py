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

from datetime import datetime
from typing import Optional

# Android's expanded view will show far more than the collapsed two lines; this
# is only a guard against an absurd payload, not a display budget.
MAX_BODY = 900


def _fmt_close(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    return dt.strftime("%a %-d %b, %-I:%M%p").replace("AM", "am").replace("PM", "pm")


def draw_release(draws: list[dict], week_label: str) -> dict:
    """
    draws: [{name, gender, tier, closing_time, location}, ...] soonest first.
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

    lines = []
    for d in draws:
        bits = [f"{d['name']} ({d['gender']})"]
        if d.get("location"):
            bits.append(d["location"])
        closes = _fmt_close(d.get("closing_time"))
        if closes:
            bits.append(f"picks close {closes}")
        lines.append(" · ".join(bits))
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
    draws: [{label, matches, upsets}, ...] — one entry per draw in the batch.
    """
    title = (f"Final standings — {where}" if is_final
             else f"{round_name} complete — {where}")

    lines = []
    for d in draws:
        bits = [d["label"]]
        if d.get("matches"):
            bits.append(f"{d['matches']} matches")
        if d.get("upsets"):
            bits.append(f"{d['upsets']} upsets")
        lines.append(" · ".join(bits))
    detail = "\n".join(lines)
    lead = "See how your picks did" if len(draws) == 1 else f"{len(draws)} draws reported"
    body = f"{lead}\n{detail}" if detail else lead

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
            "body": "Cincinnati Open (M) · Cincinnati, United States · picks close Sun 10 Aug, 11:00am\n"
                    "Cincinnati Open (F) · Cincinnati, United States · picks close Sun 10 Aug, 11:00am",
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
