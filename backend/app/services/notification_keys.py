"""
The canonical set of notification preference keys, server-side.

This list existed in three places that could not derive it from each other —
auth.py's defaults, main.py's unsubscribe labels, and the frontend's
constants/notifications.js. Adding a type meant remembering all of them, and
missing one produced a notification nobody receives and nothing reports as
broken. Everything server-side now reads it from here.

ADDING A TYPE: add the key below, and the matching row to the frontend's
ALL_NOTIFICATION_KEYS + Navbar's NOTIF_GROUPS. Nothing else is needed — the
seed in database.py enrols every existing user automatically, skipping anyone
who has explicitly opted out of it.
"""

# Email preference keys. The push twin of each is push_<key>.
ALL_EMAIL_KEYS = (
    "draw_released",
    "draw_changed",
    "qualifiers_added",
    "round_standings",
    "tournament_end",
    "league_member_joined",
)

# OFF UNTIL ASKED FOR. Everything else is on by default; these two are not,
# from 2026-09-12, on the owner's instruction — they were 30% of the mail bill
# (199 sends in thirty days, ~28 per round and seven rounds a Slam) and the
# free tier's limit is a DAILY 100 that a single fan-out can half fill.
#
# They stay in ALL_EMAIL_KEYS and therefore in the settings screen, unticked:
# "disabled for everyone, re-enablable by hand" is exactly a key that exists,
# is offered, and is not enrolled. A user who ticks it gets a preference row
# and their opt-out row deleted (routers/auth.put_notification_prefs), so the
# choice sticks across the boot enrolment.
#
# The PUSH twins are NOT affected: push costs nothing and no quota.
DEFAULT_OFF_EMAIL_KEYS = (
    "round_standings",
    "tournament_end",
)

# Mirrors PUSH_PREFIX in services/push.py and pushKey() on the client.
PUSH_PREFIX = "push_"


def push_key(email_pref_key: str) -> str:
    return f"{PUSH_PREFIX}{email_pref_key}"


# Every key a user can hold, both channels. The full registry: what the
# settings screen offers, what an unsubscribe link may name, and what counts
# as "declined" when a user saves their settings without ticking it.
ALL_KEYS = tuple(ALL_EMAIL_KEYS) + tuple(push_key(k) for k in ALL_EMAIL_KEYS)

# What a NEW OR NEWLY VERIFIED ACCOUNT is enrolled on, and what the boot pass
# hands to existing accounts. ALL_KEYS minus the default-off email keys —
# their push twins stay.
DEFAULT_ON_KEYS = tuple(k for k in ALL_KEYS if k not in DEFAULT_OFF_EMAIL_KEYS)
