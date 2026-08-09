"""
Telling a real player swap apart from Wikipedia tidying its own spelling.

A released draw's entries are re-scraped every 30 minutes, and the scraper
overwrites DrawEntry.name in place. Most of the time a changed name means what
it looks like — a withdrawal filled by a lucky loser, or a qualifier placed —
but a meaningful minority of changes are an editor renaming the article,
restoring a diacritic, or expanding an initial. Those must not reach anyone's
phone as "your player has been replaced", so the comparison happens here rather
than at the call site, where it would have been a bare `!=`.

Shared by the recording side (routers/tournaments.py) and the sending side
(notifications / push_content / email) so the wording of a swap is written once.
"""

import re
import unicodedata
from typing import Optional

# Entry types worth naming in a notification: they explain HOW the new player
# got in, which is the whole story of a draw change. A seeded direct entrant
# carries no such badge and needs no suffix.
_NOTABLE_ENTRY_TYPES = {"Q", "LL", "WC", "Alt", "SE", "PR"}


def normalize_name(name: str) -> str:
    """Casefolded, accent-stripped, punctuation-flattened form of a name.

    Used only for deciding whether two spellings denote the same person, never
    for display — 'Carreño Busta' must still render with its tilde everywhere a
    reader sees it.
    """
    s = unicodedata.normalize("NFKD", (name or "").strip())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split()).casefold()


def same_person(old: str, new: str) -> bool:
    """
    True when two names are the same player written differently.

    Two tests, both deliberately narrow. Identical once normalised catches the
    common case (a diacritic restored, a hyphen added, capitalisation fixed).
    Same surname with one given name a prefix of the other catches the rest
    ('J. Struff' → 'Jan-Lennard Struff', 'Alex Bublik' → 'Alexander Bublik').

    Requiring the surname to match is what keeps this from swallowing real
    swaps: a withdrawal is filled from the qualifying draw or the alternate
    list, so the incoming player shares a surname with the outgoing one about as
    often as any two random players do. The residual risk — a genuine
    replacement by a same-surname player whose first name is also a prefix — is
    a notification not sent, which is strictly better than telling everyone
    their pick was replaced because an editor added an accent.
    """
    a, b = normalize_name(old).split(), normalize_name(new).split()
    if not a or not b:
        return False
    if a == b:
        return True
    if a[-1] != b[-1]:
        return False
    return a[0].startswith(b[0]) or b[0].startswith(a[0])


def classify_change(old_name: str, new_name: str) -> Optional[str]:
    """
    "replaced", "filled", or None when this change is not news.

    None covers three cases that all look like a change and none of which a user
    should hear about: the same player respelled, a slot going blank (a parse
    hiccup or mid-edit vandalism — the real event is the name that replaces it,
    which arrives on a later scrape), and no change at all.
    """
    old, new = (old_name or "").strip(), (new_name or "").strip()
    if not new or old == new:
        return None
    if not old:
        return "filled"
    if same_person(old, new):
        return None
    return "replaced"


def slot_label(entry_type: Optional[str], bracket_position: int) -> str:
    """What to call a slot that had no player in it.

    Mirrors the bracket's own placeholder ('Qualifier') so the notification
    names the thing the user actually tapped when they made the pick.
    """
    return "Qualifier" if (entry_type or "").upper() == "Q" else f"Slot {bracket_position}"


def entry_suffix(entry_type: Optional[str]) -> str:
    """' (LL)' for the entry types that explain how a player got into the draw."""
    et = (entry_type or "").strip()
    return f" ({et})" if et in _NOTABLE_ENTRY_TYPES else ""


def dedupe_matchups(changes: list[dict]) -> list[dict]:
    """
    Collapse a qualifier-vs-qualifier pair into the one match it actually is.

    Two qualifiers drawn against each other are two entries pointing at the same
    first-round match, so listing per qualifier printed it from both sides —
    "Jones vs Tararudee" immediately followed by "Tararudee vs Jones". 2026
    Canadian Open (WTA) had three such pairs among its sixteen qualifiers.

    Round-1 matches occupy consecutive bracket positions from 1, so (pos-1)//2
    names the match without needing the match row itself. A qualifier drawn
    against a non-qualifier is the only holder of its key and always survives.

    The COUNT of qualifiers is deliberately not derived from this — sixteen
    qualifiers really did enter, they just produce thirteen matches.
    """
    seen, out = set(), []
    for c in changes:
        key = (c["bracket_position"] - 1) // 2
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def change_line(change: dict) -> str:
    """
    One swap as a single line: 'Arthur Fils → Zizou Bergs (LL)'.

    Shared by push and email so the two channels can never describe the same
    event differently. `change` is the dict shape built in
    notifications._gather_draw_change_payload.
    """
    src = (
        change["old_name"]
        if change["kind"] == "replaced"
        else slot_label(change.get("old_entry_type"), change["bracket_position"])
    )
    return f"{src} → {change['new_name']}{entry_suffix(change.get('new_entry_type'))}"
