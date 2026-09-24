"""Tennis Explorer's qualifying round labels, in the app's words.

ONE READER FOR BOTH TE PAGES (owner, 2026-09-24): the head-to-head meetings
and a player's form list come off the same site in the same vocabulary, and
the form list was printing "Q QF" where the head-to-head had long said "Q2".

TE labels a qualifying round three ways:
  * numbered — "Q-1R", "Q-2R" ("Qualification - 1. round"): stated, so used;
  * by the size of the qualifying draw — "Q-R32", "Q-R16";
  * by the stage of it — "Q-QF", which is the round of eight.
The last two do not say which qualifying round they are without the draw's
size. A Slam's qualifying is 128 → 64 → 32 (three rounds); every other
tour-level event's is two, from a draw of 32 or of 16, so the round of
sixteen and the round of eight are both its SECOND and last round (Q2) — the
round that makes a qualifier — and the round of thirty-two its first.
"""
from typing import Optional

GRAND_SLAMS = {"australian open", "french open", "roland garros", "wimbledon", "us open"}
_BY_SIZE_GS = {"R128": "Q1", "R64": "Q2", "R32": "Q3"}
_BY_SIZE_STD = {"R64": "Q1", "R32": "Q1", "R16": "Q2", "R8": "Q2"}
# A stage names a draw size: the quarter-finals are the round of eight.
_STAGE = {"QF": "R8", "SF": "R4", "F": "R2"}


def normalize_qual_round(round_str: Optional[str], tournament: Optional[str]) -> Optional[str]:
    if not round_str or not round_str.upper().startswith("Q-"):
        return round_str
    core = round_str[2:].strip().upper()
    if len(core) >= 2 and core[:-1].isdigit() and core.endswith("R"):
        return f"Q{core[:-1]}"                       # "Q-2R": TE numbered it
    core = _STAGE.get(core, core)
    is_gs = bool(tournament) and any(g in tournament.strip().lower() for g in GRAND_SLAMS)
    return (_BY_SIZE_GS if is_gs else _BY_SIZE_STD).get(core, round_str)


def normalize_rounds(data: dict) -> dict:
    """A head-to-head payload with every meeting's round read the same way —
    applied on the way OUT, so rows cached before this reader existed are
    read by it too."""
    if not isinstance(data, dict) or not isinstance(data.get("matches"), list):
        return data
    return {**data, "matches": [
        {**m, "round": normalize_qual_round(m.get("round"), m.get("tournament"))}
        if isinstance(m, dict) else m
        for m in data["matches"]]}
