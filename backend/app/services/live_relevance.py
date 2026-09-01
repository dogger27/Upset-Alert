"""
Which live match is worth a Lock Screen, for THIS user.

THE PROBLEM IS THE OPPOSITE OF A SCORES APP'S. Upset Alert is a full-bracket
game: every competitor picks a winner for every match in the draw. So "matches
I picked" selects the entire draw and is not a filter at all — and on the first
Monday of a Slam, thirty singles matches are live at once against one Lock
Screen.

The standout logic in notifications.py cannot help: it needs Match.winner_id
and is therefore retrospective, describing a match that is already over.
upsets.py is the right machinery because it works on an UNFINISHED match — its
rank computation and its forward resolution of a user's own predicted winners
are exactly what "how much does this one matter to you" needs.
"""

from typing import Optional

from app.services.upsets import _compute_draw_ranks, _resolve_match_entrants

# Nothing below this is worth interrupting someone for. Returning no
# suggestion is a better answer than a weak one — a prompt for a match the user
# does not care about teaches them to dismiss the prompt.
MIN_SCORE = 2.0

W_STAKE = 3.0
W_UPSET = 2.0
W_ROUND = 1.5
W_TIER = 1.0
W_CLOSE = 1.5
W_DECIDED = -2.0


def is_upset(match_id: int, picks: dict, ranks: dict, entrants: dict) -> bool:
    """Did this user pick the lower-ranked entrant?

    Extracted so has_upset_pick and this scorer cannot disagree. upsets.py's
    whole stated reason for existing is to mirror what the bracket's Upset
    Alert bell shows, and a second copy of the comparison is how that promise
    quietly breaks.
    """
    predicted = picks.get(match_id)
    if predicted is None:
        return False
    p1, p2 = entrants.get(match_id, (None, None))
    if p1 is None or p2 is None:
        return False
    r1 = ranks.get(p1, float("inf"))
    r2 = ranks.get(p2, float("inf"))
    expected = p1 if r1 <= r2 else p2
    return predicted != expected


def stake(match_id: int, matches: list, picks: dict, entrants: dict) -> int:
    """How many LATER matches in this user's bracket depend on this one.

    The number that makes a full-bracket game different from a scores app. A
    quarter-finalist the user picked to lift the trophy is carrying five more
    predictions behind them; an R64 match they expect nothing further from is
    carrying none. Both are "a match I picked", and only one is worth a Lock
    Screen.

    Counted from the user's own predicted cascade, which _resolve_match_entrants
    already computes — so this is a walk over data we have, not a second model
    of the draw.
    """
    winner = picks.get(match_id)
    if winner is None:
        return 0
    by_id = {m.id: m for m in matches}
    this = by_id.get(match_id)
    if this is None:
        return 0
    count = 0
    for m in matches:
        if m.round_number <= this.round_number:
            continue
        p1, p2 = entrants.get(m.id, (None, None))
        if winner in (p1, p2):
            count += 1
    return count


def closeness(point: Optional[dict]) -> float:
    """How tense the match is right now, from renderable_point()'s own output.

    Reading the same helper the website reads means the score that justified
    the suggestion is the score the user will see when they tap it.
    """
    if not point:
        return 0.0
    games = point.get("games")
    if not games or len(games) != 2:
        return 0.0
    score = 0.0
    if point.get("tiebreak") or point.get("match_tiebreak"):
        score += 1.0
    try:
        completed = sum(1 for a, b in zip(*games) if a != "" and b != "")
        # A set apiece, or a deciding set, is the whole reason to look.
        if completed >= 1:
            from app.services.live_activity_content import _sets_won
            won = _sets_won(games)
            if won[0] == won[1] and sum(won) > 0:
                score += 1.0
        cur = [int(x or 0) for x in (games[0][-1], games[1][-1])]
        if max(cur) >= 5 and abs(cur[0] - cur[1]) <= 1:
            score += 1.0
    except (TypeError, ValueError, IndexError):
        pass
    return score


def decided_against(point: Optional[dict], pick_side: Optional[int]) -> bool:
    """Is the user's pick two sets down — i.e. is this already grief?

    Dropped hard rather than merely deprioritised. A Lock Screen counting down
    someone's elimination is not a feature.
    """
    if not point or pick_side not in (1, 2):
        return False
    games = point.get("games")
    if not games:
        return False
    from app.services.live_activity_content import _sets_won
    won = _sets_won(games)
    theirs, other = won[pick_side - 1], won[2 - pick_side]
    return other - theirs >= 2


def score_match(
    match, *, picks: dict, ranks: dict, entrants: dict, matches: list,
    point: Optional[dict], num_rounds: int, tier_weight: float = 0.5,
) -> tuple:
    """(score, reason) for one live match, for one user."""
    mid = match.id
    upset = is_upset(mid, picks, ranks, entrants)
    st = stake(mid, matches, picks, entrants)
    rnd = (match.round_number / num_rounds) if num_rounds else 0.0
    close = closeness(point)

    pick_side = _pick_side(match, picks.get(mid), entrants)
    lost = decided_against(point, pick_side)

    total = (W_STAKE * min(st, 4) / 4.0
             + W_UPSET * (1.0 if upset else 0.0)
             + W_ROUND * rnd
             + W_TIER * tier_weight
             + W_CLOSE * min(close, 3.0) / 3.0
             + W_DECIDED * (1.0 if lost else 0.0))

    # The reason is what makes an offer feel considered rather than random, and
    # it costs nothing to carry.
    # SAY WHAT THE USER DID, NOT WHAT THEY "ARE".
    # "Your upset pick is on court" reads as though the user is the upset. The
    # thing that actually happened is that they picked the lower-ranked player,
    # so say that: an upset pick IS picking the underdog.
    #
    # And never fall back to "You picked this match". Every competitor picks
    # every match in the draw — it is a full-bracket game — so that sentence
    # carries no information whatsoever and is true of all 127 matches at once.
    if lost:
        reason = "The player you picked is two sets down"
    elif upset and close >= 2:
        reason = "You picked the underdog, and it's tight"
    elif upset:
        reason = "You picked the underdog here"
    elif st >= 3:
        # The concrete number beats the vague claim: "5 of your later picks
        # ride on this" is checkable, "your bracket leans on this one" is not.
        reason = f"{st} of your later picks ride on this"
    elif close >= 2:
        reason = "This one is close"
    elif rnd >= 0.8:
        reason = "Late in the draw"
    else:
        # Scored above MIN_SCORE without any single standout cause — usually
        # round and tier together. Say that plainly rather than inventing one.
        reason = "A big match in this draw"
    return (round(total, 3), reason)


def _pick_side(match, predicted_winner_id, entrants) -> Optional[int]:
    if predicted_winner_id is None:
        return None
    p1, p2 = entrants.get(match.id, (None, None))
    if predicted_winner_id == p1:
        return 1
    if predicted_winner_id == p2:
        return 2
    return None


def rank_live_matches(
    live_matches: list, *, predictions: list, all_matches: list,
    entries: list, points: dict, num_rounds: int, tier_weight: float = 0.5,
) -> list:
    """Every live match this user has a stake in, best first.

    Ranks and entrants are computed ONCE for the draw rather than per match —
    _resolve_match_entrants walks the whole bracket, and calling it per match
    would make an offer O(matches squared) on the busiest day of the year.
    """
    picks = {p.match_id: p.predicted_winner_id
             for p in predictions if p.predicted_winner_id is not None}
    if not picks:
        return []
    ranks = _compute_draw_ranks(entries)
    entrants = _resolve_match_entrants(all_matches, picks)

    scored = []
    for m in live_matches:
        s, reason = score_match(
            m, picks=picks, ranks=ranks, entrants=entrants, matches=all_matches,
            point=points.get(m.id), num_rounds=num_rounds, tier_weight=tier_weight,
        )
        if s >= MIN_SCORE:
            scored.append({"match_id": m.id, "score": s, "reason": reason})
    scored.sort(key=lambda x: -x["score"])
    return scored
