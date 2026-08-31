"""Facts about a match's live state that more than one poller has to agree on.

Both writers of Match.live_scores_json — the Sofascore poller and the ESPN
monitor — observe the same transitions, and a rule implemented twice is a rule
that will eventually be implemented differently.
"""

from datetime import datetime, timezone
from typing import Optional


def is_suspended(live) -> bool:
    """Does this live_scores payload say play has stopped?

    The status is the fifth element of the ESPN-shaped list. Absent means
    "playing" — the flag is only ever appended when there is something to say.
    """
    return (isinstance(live, (list, tuple)) and len(live) > 4
            and live[4] == "suspended")


def note_resumption(match, new_live) -> Optional[datetime]:
    """Stamp resumed_at when a match comes back on court, and return it.

    Called with the payload about to be written, BEFORE it is assigned, so the
    match still holds the previous one to compare against. Only the
    suspended -> playing edge counts: started_at is the first point of the
    match and must not move, or a resumed match would lose the fact that it
    began yesterday, which is the whole reason its row is on today's sheet.

    Stamped once per resumption. A match that goes out and comes back twice in
    a day keeps the latest, which is the one its row should be printing.
    """
    if not is_suspended(getattr(match, "live_scores_json", None)):
        return None
    if is_suspended(new_live):
        return None
    now = datetime.now(timezone.utc)
    match.resumed_at = now
    return now
