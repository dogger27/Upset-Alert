"""
What a Live Activity SAYS. Never when to send it.

push_content.py's twin, and separate from the dispatcher for the same reason it
is separate from push.py: the wording and shape of a message are a different
question from the policy that decides it should exist, and testing either one
against the other's bugs is how both end up wrong.

This module owns CONTENT_VERSION. ActivityKit decodes `content-state` into a
Swift Codable struct, so a shape change breaks every install that has not
updated — SILENTLY, because APNs still returns 200 for a payload the app cannot
decode. Nothing else may construct these dicts.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

# Bump ONLY together with a client release, and only after the dispatcher
# learns to keep emitting the old shape to activities that recorded the old
# version (live_activities.content_version).
CONTENT_VERSION = 1

# How long the client should treat a state as current before greying itself
# out. The best defence against a frozen-looking Lock Screen: if we go quiet for
# any reason, iOS dims the activity WITHOUT needing a push from us.
#
# IT MUST EXCEED OUR OWN WORST GAP DURING PLAY, or the activity greys itself
# out while the match is being played normally — a false alarm that trains
# people to distrust it. Measured with scripts/la_budget_sim.py over 88 real
# matches: the longest gap the throttle produces while the feed is continuous
# is 3.0 minutes, which happens when a long game yields no visible change and
# no priority-10 event. 240s clears that with margin. The first value here was
# 150s, chosen to mirror FRESH_SECONDS before the simulator existed to say
# otherwise.
STALE_AFTER_SECONDS = 240

STATUS_IN_PROGRESS = "in_progress"
STATUS_SUSPENDED = "suspended"
STATUS_FINAL = "final"
STATUS_NO_RESULT = "ended_no_result"


def build_attributes(match, p1_name: str, p2_name: str, *,
                     p1_entry_id: Optional[int] = None,
                     p1_seed: Optional[int] = None,
                     p2_seed: Optional[int] = None,
                     round_name: str = "", event_label: str = "") -> dict:
    """The immutable half, sent once when the activity starts.

    Anything that cannot change during a match belongs here rather than in the
    content state, because the content state is re-sent on every update and
    every byte of it is paid for repeatedly.

    p1_entry_id travels because ORIENTATION IS NOT OBVIOUS. The poller flips
    Sofascore's home/away into the match's own order, and the score-history
    endpoint already returns player1_id for exactly this reason — a client that
    assumes its own ordering will silently swap the players on some matches.
    """
    return {
        "match_id": match.id,
        "p1_entry_id": p1_entry_id,
        "p1_name": p1_name,
        "p2_name": p2_name,
        "p1_seed": p1_seed,
        "p2_seed": p2_seed,
        "round_name": round_name,
        "event_label": event_label,
    }


def build_content_state(
    point: Optional[dict],
    *,
    status: str = STATUS_IN_PROGRESS,
    winner: Optional[int] = None,
    final_line: Optional[str] = None,
    pick_side: Optional[int] = None,
    pick_correct: Optional[bool] = None,
    at: Optional[datetime] = None,
    version: int = CONTENT_VERSION,
) -> dict:
    """The mutable half — about 250 bytes, sent on every update.

    `point` is renderable_point()'s output, unchanged: sets, games, current
    point, serving, tiebreak flags. Taking it from that one helper rather than
    re-deriving it is what keeps the Lock Screen agreeing with the website.

    THE POINT IS NULL, NOT "0"-"0", WHEN WE DO NOT HAVE ONE. ESPN publishes
    game counts only, so a match sourced from it has no current point at all,
    and renderable_history already draws that distinction. Sending zeros would
    have the Lock Screen confidently show love-all through an entire game.
    """
    now = at or datetime.now(timezone.utc)
    games = (point or {}).get("games")

    state = {
        "v": version,
        "games": games,
        "point": (point or {}).get("point") if point else None,
        "tiebreak": bool((point or {}).get("tiebreak")),
        "match_tiebreak": bool((point or {}).get("match_tiebreak")),
        "serving": (point or {}).get("serving"),
        "sets_won": _sets_won(games),
        "status": status,
        "winner": winner,
        "final_line": final_line,
        # THIS user's pick. The whole reason a fantasy app's Lock Screen is
        # worth more than a scores app's: the number that matters is not the
        # score, it is whether the score is going your way.
        "pick": {"side": pick_side, "correct": pick_correct},
        "at": now.isoformat(),
        "stale_after": (now + timedelta(seconds=STALE_AFTER_SECONDS)).isoformat(),
    }
    return state


def build_payload(
    content_state: dict,
    *,
    event: str = "update",              # start | update | end
    timestamp: int,
    attributes: Optional[dict] = None,
    attributes_type: Optional[str] = None,
    dismissal_seconds: Optional[int] = None,
    relevance: int = 100,
    alert: Optional[dict] = None,
) -> dict:
    """The full APNs body.

    `timestamp` MUST strictly increase per activity. ActivityKit silently
    discards an update whose timestamp is not greater than the last one it
    accepted, and with coalescing and retries in play out-of-order sends are
    entirely possible — so the caller tracks it rather than trusting the clock.
    """
    aps = {
        "timestamp": timestamp,
        "event": event,
        "content-state": content_state,
        "relevance-score": relevance,
    }
    stale = content_state.get("stale_after")
    if stale and event != "end":
        aps["stale-date"] = int(datetime.fromisoformat(stale).timestamp())
    if event == "start":
        # push-to-start needs the type name and the immutable half, because
        # there is no client-side Activity to have supplied them.
        aps["attributes-type"] = attributes_type
        aps["attributes"] = attributes or {}
    if event == "end" and dismissal_seconds is not None:
        aps["dismissal-date"] = int(
            (datetime.now(timezone.utc) + timedelta(seconds=dismissal_seconds)).timestamp()
        )
    if alert:
        aps["alert"] = alert
    return {"aps": aps}


def final_line(games: Optional[list]) -> Optional[str]:
    """"6-4 3-6 7-6" from the games grid, for the end push."""
    if not games or len(games) != 2:
        return None
    a, b = games
    return " ".join(f"{x}-{y}" for x, y in zip(a, b) if x != "" or y != "") or None


def _sets_won(games: Optional[list]) -> list:
    """Completed sets won by each side.

    Counted here rather than sent by the poller because it is a rendering
    decision — a set is "won" once it is complete, and the set in progress is
    the one the client is drawing live.
    """
    if not games or len(games) != 2:
        return [0, 0]
    won = [0, 0]
    for x, y in zip(games[0], games[1]):
        try:
            gx, gy = int(x), int(y)
        except (TypeError, ValueError):
            continue
        # A set is over at 6 with two clear, or at 7. Anything else is still
        # being played and belongs to neither total yet.
        if max(gx, gy) >= 6 and abs(gx - gy) >= 2:
            won[0 if gx > gy else 1] += 1
        elif max(gx, gy) == 7:
            won[0 if gx > gy else 1] += 1
    return won
