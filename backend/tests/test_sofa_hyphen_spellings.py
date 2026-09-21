"""A hyphen is two spellings — in the Sofascore resolver and the shape check.

2026 Korea Open (draw 146), 2026-09-21: we hold the wildcards "Park So-hyun"
and "Ku Yeon-woo"; Sofascore's cup tree names them "Sohyun Park" and
"Yeonwoo Ku". Both Sofascore matchers split the hyphen and never tried the
joined form, so the resolver left both entries without a sofa_player_id (no
live score could reach their matches) and the shadow comparison warned
"2 in sofascore only; 2 in ours only" every day. "Back Da-yeon" only
resolved by the fuzzy rule's luck.
"""
from app.services.sofa_draw_shape import (
    DrawShape,
    ShapeEntrant,
    compare_to_entries,
    disagreement_summary,
)
from app.services.sofascore import _Candidate, _match_one

# (ours, Sofascore's) — the Korea Open pairs, plus the mirror case where the
# hyphen is on Sofascore's side ("Ma Yexin" / "Ye-Xin Ma").
PAIRS = [
    ("Park So-hyun", "Sohyun Park"),
    ("Ku Yeon-woo", "Yeonwoo Ku"),
    ("Back Da-yeon", "Dayeon Back"),
    ("Ma Yexin", "Ye-Xin Ma"),
]
# Bystanders that must keep matching the way they always have.
OTHERS = [
    ("Felix Auger-Aliassime", "Felix Auger-Aliassime"),
    ("Elena-Gabriela Ruse", "Elena-Gabriela Ruse"),
    ("Zhang Shuai", "Shuai Zhang"),
    ("Lee Hyunyee", "Hyunyee Lee"),
]


class E:
    def __init__(self, name, bracket_position, sofa_name=None):
        self.name = name
        self.bracket_position = bracket_position
        self.sofa_name = sofa_name
        self.seed = None
        self.entry_type = None


def _team(i, name, alpha3="KOR"):
    return {"id": 1000 + i, "name": name, "country": {"alpha3": alpha3}}


# ── the resolver ──────────────────────────────────────────────────────────

def test_the_resolver_matches_a_hyphenated_name_to_its_joined_spelling():
    field = [_team(i, theirs) for i, (_, theirs) in enumerate(PAIRS + OTHERS)]
    cands = [_Candidate(t) for t in field]
    for ours, theirs in PAIRS:
        team, rule = _match_one(ours, "KOR", cands)
        assert team is not None, ours
        assert team["name"] == theirs, (ours, team["name"], rule)


def test_the_joined_spelling_does_not_move_anyone_else():
    field = [_team(i, theirs) for i, (_, theirs) in enumerate(PAIRS + OTHERS)]
    cands = [_Candidate(t) for t in field]
    for ours, theirs in OTHERS:
        team, _ = _match_one(ours, None, cands)
        assert team is not None and team["name"] == theirs, ours


def test_two_players_under_one_joined_spelling_resolve_to_neither():
    """The joined rule is held to the same one-hit rule as every other: two
    candidates answering to it is a case for a human, not a guess."""
    cands = [_Candidate(_team(1, "Sohyun Park")), _Candidate(_team(2, "Park Sohyun"))]
    assert _match_one("Park So-hyun", "KOR", cands) == (None, None)


# ── the shadow comparison ─────────────────────────────────────────────────

def _shape(names):
    return DrawShape(bracket_size=len(names), num_rounds=3, entrants=[
        ShapeEntrant(bracket_position=i + 1, name=n) for i, n in enumerate(names)])


def test_the_shape_check_sees_one_player_under_both_spellings():
    shape = _shape([theirs for _, theirs in PAIRS + OTHERS])
    ours = [E(o, i + 1) for i, (o, _) in enumerate(PAIRS + OTHERS)]
    cmp = compare_to_entries(shape, ours)
    assert cmp["matched"] == len(PAIRS + OTHERS), disagreement_summary(cmp)
    assert disagreement_summary(cmp) is None


def test_the_korea_open_as_it_stood_is_no_disagreement():
    """The exact rows production held: two entries with no sofa_name (the
    resolver had missed them too) and one it had resolved."""
    shape = _shape(["Sohyun Park", "Yeonwoo Ku", "Dayeon Back", "Eva Lys"])
    ours = [E("Park So-hyun", 1), E("Ku Yeon-woo", 2),
            E("Back Da-yeon", 3, sofa_name="Dayeon Back"), E("Eva Lys", 4)]
    cmp = compare_to_entries(shape, ours)
    assert cmp["only_sofascore"] == [] and cmp["only_ours"] == []
    assert disagreement_summary(cmp) is None
