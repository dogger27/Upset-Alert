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

# Mirrors PUSH_PREFIX in services/push.py and pushKey() on the client.
PUSH_PREFIX = "push_"


def push_key(email_pref_key: str) -> str:
    return f"{PUSH_PREFIX}{email_pref_key}"


# Every key a user can hold, both channels.
ALL_KEYS = tuple(ALL_EMAIL_KEYS) + tuple(push_key(k) for k in ALL_EMAIL_KEYS)
