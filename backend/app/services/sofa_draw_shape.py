"""DRAW SHAPE FROM SOFASCORE'S CUP TREE — the fields Wikipedia was sole author of.

THE OWNER'S STANDING DIRECTION is to eliminate Wikipedia wherever it can be
done reliably. Results went first (2026-09-16: "NEVER, EVER, use Wikipedia for
a match result or score"), leaving Wikipedia as sole author of the draw's
SHAPE: who is in it, which slot each holds, their seed, their entry type, and
which slots are byes. That is what kept Hangzhou and Chengdu dark on
2026-09-21 — no article, no draw — and it is why this module exists.

IT IS ALL IN A PAYLOAD WE ALREADY FETCH. `sofascore._field_of` GETs
/unique-tournament/{uid}/season/{id}/cuptrees once per draw and
`_main_draw_teams` reduces every participant to id/name/country/type, dropping
the rest on the floor. The rest is the shape:

    cupTrees[] .rounds[] .blocks[] .participants[]
      block.order        1-based position of the pair within the round
      participant.order  1 or 2 — WHICH SIDE of that pair
      participant.teamSeed  "1".."32" for a seed, else "Q"/"WC"/"LL"/"A"
      block.matchesInRound  0 when nobody plays here: a BYE

  bracket_position = (block.order - 1) * 2 + participant.order

MEASURED AGAINST WIKIPEDIA, NOT ASSUMED. 2026 Guadalajara (draw 142, a
28-entrant field in a 32 bracket) on 2026-09-21:

    bracket positions   28 of 28 agree, ZERO disagree — the only apparent
                        mismatches were diacritics (Bucsa/Bucșa, Jović/Jovic,
                        Frech/Fręch, Zarazua/Zarazúa, Bejlek/Sára Bejlek,
                        Lois/Loïs), which is what name folding is for
    byes                [2, 10, 24, 32] from the cup tree; Wikipedia's absent
                        slots were [2, 10, 24, 32]
    seeds               1-8 present
    entry types         Q, WC and A observed

Then on three more resolved draws, to cover the bracket sizes: Monterrey 28/28
matched with no disagreement at all, Winston-Salem 47/48 (16 byes in a 64
bracket, identical), Cincinnati 94/96 (32 byes in a 128 bracket, identical).
Across all four the only true conflict was vocabulary — "A" against our "Alt" —
which _ENTRY_MARKERS now maps, and a handful of names where the two sources
order the parts differently (Zhang Shuai / Shuai Zhang).

WHAT IT STILL CANNOT DO, stated plainly so nobody builds on a wish:

  * It cannot BOOTSTRAP a draw we know nothing about. `_resolve_against_field`
    identifies a Sofascore tournament by matching its published field against
    OUR entries, so a draw with no entries has nothing to match on — the
    chicken-and-egg that left Hangzhou unresolved (sofa ids NULL) while its
    shape sat on Wikipedia. Identity has to be solved another way before this
    can replace Wikipedia rather than corroborate it.
  * A bye is inferred from `matchesInRound == 0` on a one-participant block.
    That is Sofascore stating it, not us guessing, and it has now been measured
    on four draws across three bracket sizes — Guadalajara and Monterrey
    (4 byes in 32), Winston-Salem (16 in 64) and Cincinnati (32 in 128). The
    bye lists were IDENTICAL to Wikipedia's absent slots in all four.
  * Nationality is not on the participant's team object in the trimmed shape,
    so entries still take it from elsewhere.
  * A GENERATIONAL SUFFIX IS LEFT ALONE ON PURPOSE. Winston-Salem reports
    "Martin Damm Jr" where we hold "Martin Damm", and folding the suffix away
    would make those one key — but Martin Damm Sr is also a real player, so
    that rule would eventually match a father to his son's slot. Reporting a
    difference is the safe answer here and guessing is not; this is the last
    residual difference across the four draws measured.

NOTHING HERE MAKES A REQUEST. It parses a payload the caller already has, so
the shadow comparison below costs no traffic — which is the whole point of
putting it on the resolution path rather than on a timer.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Entry markers Sofascore multiplexes into teamSeed alongside the seed number,
# mapped to THIS project's vocabulary (scraper.ENTRY_TYPES) so a comparison
# reports real conflicts and not two spellings of the same fact. Sofascore
# writes an alternate as "A" and we write "Alt" — which showed up as the only
# "disagreement" across four measured draws (Winston-Salem's Yibing Wu,
# 2026-09-21).
_ENTRY_MARKERS = {
    "Q": "Q", "WC": "WC", "LL": "LL", "PR": "PR", "SE": "SE", "NG": "NG",
    "A": "Alt", "ALT": "Alt",
}
_SEED_RE = re.compile(r"^\d+$")


@dataclass
class ShapeEntrant:
    bracket_position: int
    name: str
    sofa_player_id: Optional[int] = None
    sofa_slug: Optional[str] = None
    seed: Optional[int] = None
    entry_type: Optional[str] = None
    nationality: Optional[str] = None      # IOC code, when the source states it
    te_slug: Optional[str] = None          # Tennis Explorer slug, when the source states it
    ranking: Optional[int] = None          # entry ranking, when the source states it


@dataclass
class DrawShape:
    bracket_size: int                       # slots, so 32 for a 28-entrant field
    num_rounds: int
    entrants: list = field(default_factory=list)
    byes: list = field(default_factory=list)   # the EMPTY slots

    @property
    def entrant_count(self) -> int:
        return len(self.entrants)


def _split_seed(team_seed) -> tuple:
    """teamSeed -> (seed, entry_type). One field carrying two facts."""
    if team_seed is None:
        return None, None
    s = str(team_seed).strip()
    if not s:
        return None, None
    if _SEED_RE.match(s):
        return int(s), None
    return None, _ENTRY_MARKERS.get(s.upper())


def main_tree(payload: dict) -> Optional[dict]:
    """The main draw's tree, never the qualifying one.

    Matched by the ABSENCE of a qualifying marker rather than by position:
    the qualifying tree is not reliably second, and picking by index would
    silently read a qualifying bracket as a main draw.
    """
    trees = payload.get("cupTrees") or []
    for t in trees:
        name = (t.get("name") or "").lower()
        if "qualif" not in name:
            return t
    return None


def main_draw_start(payload: dict):
    """The main draw's first scheduled day, from the cup tree itself.

    WHY NOT `first_main_draw_start`. That reads /events/next/0, which by
    definition only knows about events still to come — so it 404s for a
    tournament that has already been played. Identity has to work for both: a
    finished draw is exactly what you verify a new rule against, and a future
    one is what you need it for. The cup tree's own blocks carry
    `seriesStartDateTimestamp`, so the date comes free with the payload that
    is already in hand, past or future.

    Returns a date, or None when no block carries a timestamp (which is the
    ordinary state for a bracket published before it is scheduled).
    """
    from datetime import datetime, timezone

    tree = main_tree(payload)
    if not tree:
        return None
    rounds = tree.get("rounds") or []
    if not rounds:
        return None
    stamps = [b.get("seriesStartDateTimestamp")
              for b in (rounds[0].get("blocks") or [])
              if b.get("seriesStartDateTimestamp")]
    if not stamps:
        return None
    return datetime.fromtimestamp(min(stamps), tz=timezone.utc).date()


def draw_shape(payload: dict) -> Optional[DrawShape]:
    """Every shape fact the cup tree states. None when there is no main tree.

    A cup tree Sofascore has created but not filled is a row of placeholder
    names (R16P1, R16P2, …) — see sofascore.py's note — and yields entrants
    whose names are those placeholders. Callers must judge that; this function
    reports what the payload says rather than deciding it is unusable.
    """
    tree = main_tree(payload)
    if not tree:
        return None
    rounds = tree.get("rounds") or []
    if not rounds:
        return None
    first = rounds[0]
    blocks = first.get("blocks") or []
    if not blocks:
        return None

    shape = DrawShape(bracket_size=len(blocks) * 2, num_rounds=len(rounds))
    for bi, blk in enumerate(blocks, start=1):
        order = blk.get("order") or bi
        parts = blk.get("participants") or []
        taken = set()
        for p in parts:
            side = p.get("order") or 1
            slot = (order - 1) * 2 + side
            taken.add(side)
            team = p.get("team") or {}
            seed, entry = _split_seed(p.get("teamSeed"))
            shape.entrants.append(ShapeEntrant(
                bracket_position=slot,
                name=(team.get("name") or "").strip(),
                sofa_player_id=team.get("id"),
                sofa_slug=team.get("slug"),
                seed=seed, entry_type=entry))
        # A BYE IS THE ABSENCE OF A MATCH, and Sofascore says so outright:
        # one participant and no match to play in this round. The bye is the
        # side of the pair nobody occupies.
        if len(parts) == 1 and blk.get("matchesInRound") == 0:
            empty = 2 if 1 in taken else 1
            shape.byes.append((order - 1) * 2 + empty)
    shape.entrants.sort(key=lambda e: e.bracket_position)
    shape.byes.sort()
    return shape


def bracket_is_complete(shape: DrawShape) -> bool:
    """Whether every slot in the bracket is accounted for.

    A SOFASCORE CUP TREE FILLS INCREMENTALLY, and that is the difference
    between it and a Wikipedia draw page. Measured 2026-09-21 at 10:58, two
    days before play: Hangzhou and Chengdu each read 20 entrants and 4 byes in
    a 32 bracket — 24 of 32 slots — while the Wikipedia draft of the same draw
    held all 28 entrants including the four qualifier placeholders. Earlier the
    same morning the cup trees 404'd entirely.

    Without this gate the bootstrap would have written a 20-entrant draw and,
    because 20 clears `draw_substantially_complete`'s 50% bar, STAMPED IT
    RELEASED — a half-filled bracket presented as the field, with picks open on
    it. And since the bootstrap only runs on a draw with no entries, it would
    then never revisit it.

    The rule is structural rather than a threshold: a bracket is complete when
    every slot is either occupied or a bye. Verified against the four draws
    measured that day — Guadalajara and Monterrey 28+4=32, Winston-Salem
    48+16=64, Cincinnati 96+32=128 — and against the two incomplete ones,
    20+4=24 in a 32.
    """
    if not shape or not shape.bracket_size:
        return False
    return shape.entrant_count + len(shape.byes) == shape.bracket_size


# ── the shadow comparison ─────────────────────────────────────────────────
# Evidence before authority. This says where Sofascore and Wikipedia disagree
# about a draw we already hold, so the decision to demote Wikipedia can be made
# on a record rather than on one afternoon's spot check.

def _fold(name: str) -> str:
    """Compare names the way the rest of the codebase does.

    Guadalajara's six apparent position mismatches were all diacritics —
    Bucsa/Bucșa, Jović/Jovic, Frech/Fręch, Zarazúa, Sára, Loïs — so a
    comparison that skips folding reports a fault rate of 21% where the real
    one is zero.
    """
    import unicodedata
    n = unicodedata.normalize("NFKD", name or "")
    n = "".join(c for c in n if not unicodedata.combining(c))
    return " ".join(n.lower().replace("-", " ").split())


def _unordered(name: str) -> str:
    """The same name with its parts sorted, for sources that disagree on order.

    Monterrey, 2026-09-21: we hold "Zhang Shuai" and "Liang En-shuo" while
    Sofascore publishes "Shuai Zhang" and "En-Shuo Liang" — surname-first
    against given-name-first, which folding alone reports as two players
    missing from each side. Sorting the parts makes the two spellings one key.
    Deliberately a LAST resort below: it would also equate two real people who
    happen to be anagrams of each other, which is why the entry's own
    `sofa_name` — the mapping the resolver already established and stored — is
    tried first.
    """
    return " ".join(sorted(_fold(name).split()))


_HYPHENS = "-‐‑‒–"


def _joined(name: str) -> str:
    """The order-insensitive form with every hyphen closed up.

    A HYPHEN IS TWO SPELLINGS. 2026 Korea Open (draw 146): we hold the
    wildcards "Park So-hyun" and "Ku Yeon-woo", Sofascore "Sohyun Park" and
    "Yeonwoo Ku". `_fold` spaces the hyphen, so "So-hyun" is two words where
    "Sohyun" is one and no key could meet — "2 in sofascore only; 2 in ours
    only" every day. An EXTRA key, never a substitute: "Auger-Aliassime" is
    two words in every source and must still meet its spaced form.
    """
    return _unordered(re.sub(f"[{_HYPHENS}]", "", name or ""))


def compare_to_entries(shape: DrawShape, entries: list) -> dict:
    """Where the cup tree and our stored draw_entries differ.

    `entries` is our DrawEntry rows (name, bracket_position, seed, entry_type).
    Returns counts plus the specific disagreements, so a caller can log one
    line and a reader can chase any of them.
    """
    # Four keys per entry, most trustworthy first: the name as we hold it,
    # the name SOFASCORE gave the resolver for this very entry (already stored
    # on the row, so this reuses matching that is proven rather than repeating
    # it), the order-insensitive form, and that form with hyphens joined.
    ours: dict = {}
    for e in entries:
        if not (e.name or "").strip():
            continue
        for key in (_fold(e.name), _fold(getattr(e, "sofa_name", "") or ""),
                    _unordered(e.name), _joined(e.name)):
            if key:
                ours.setdefault(key, e)
    out = {"matched": 0, "position": [], "seed": [], "entry_type": [],
           "only_sofascore": [], "only_ours": [],
           "byes_sofascore": list(shape.byes), "byes_ours": []}

    taken = {e.bracket_position for e in entries}
    out["byes_ours"] = sorted(set(range(1, shape.bracket_size + 1)) - taken)

    for s in shape.entrants:
        if not s.name:
            continue
        mine = None
        for key in (_fold(s.name), _unordered(s.name), _joined(s.name)):
            mine = ours.get(key)
            if mine is not None:
                break
        if mine is not None:
            # Drop every key this row answers to, so one entrant is matched once.
            for k in [k for k, v in ours.items() if v is mine]:
                del ours[k]
        if mine is None:
            out["only_sofascore"].append((s.bracket_position, s.name))
            continue
        out["matched"] += 1
        # What Sofascore states that we do not yet hold: a seed or an entry
        # type. Offered to the caller, never written here.
        if (s.seed is not None and mine.seed is None) or (s.entry_type and not mine.entry_type):
            out.setdefault("fillable", []).append((mine, s.seed, s.entry_type))
        if mine.bracket_position != s.bracket_position:
            out["position"].append((s.name, mine.bracket_position, s.bracket_position))
        # A DISAGREEMENT IS TWO VALUES THAT DIFFER. A value we lack and the
        # source states is a fill (above), not a conflict.
        if s.seed is not None and mine.seed is not None and mine.seed != s.seed:
            out["seed"].append((s.name, mine.seed, s.seed))
        if s.entry_type and mine.entry_type and mine.entry_type != s.entry_type:
            out["entry_type"].append((s.name, mine.entry_type, s.entry_type))
    out["only_ours"] = sorted({e.name for e in ours.values()})
    return out


def disagreement_summary(cmp: dict) -> Optional[str]:
    """One line naming every disagreement, or None when the two agree."""
    bits = []
    if cmp["position"]:
        bits.append(f"{len(cmp['position'])} position(s): " + ", ".join(
            f"{n} ours {a} vs sofa {b}" for n, a, b in cmp["position"][:4]))
    if cmp["seed"]:
        bits.append(f"{len(cmp['seed'])} seed(s): " + ", ".join(
            f"{n} ours {a} vs sofa {b}" for n, a, b in cmp["seed"][:4]))
    if cmp["entry_type"]:
        bits.append(f"{len(cmp['entry_type'])} entry type(s): " + ", ".join(
            f"{n} ours {a} vs sofa {b}" for n, a, b in cmp["entry_type"][:4]))
    if cmp["byes_sofascore"] != cmp["byes_ours"]:
        bits.append(f"byes ours {cmp['byes_ours']} vs sofa {cmp['byes_sofascore']}")
    if cmp["only_sofascore"]:
        bits.append(f"{len(cmp['only_sofascore'])} in sofascore only")
    if cmp["only_ours"]:
        bits.append(f"{len(cmp['only_ours'])} in ours only")
    return "; ".join(bits) or None


# ── the adapter: a Sofascore shape, in the form the existing writer eats ───

def shape_to_parsed(shape: DrawShape):
    """A DrawShape as a scraper.ParsedDraw, so the PROVEN writer does the work.

    THIS IS THE WHOLE POINT OF THE ADAPTER. `routers/tournaments._do_scrape`
    already knows how to turn a ParsedDraw into draw_entries and matches — it
    upserts rather than deletes, stamps the draw release, assigns rankings,
    detects qualifiers and repairs picks. Writing a second path to do that from
    a cup tree would mean a second set of those decisions to keep in step, and
    the first one is battle-tested. So Sofascore becomes an alternative SOURCE
    for the same structure, not a parallel system.

    THE BRACKET CONVENTION, read off production rather than assumed
    (draws 122 and 142, 2026-09-21):

      round 1      one match per block, match_number = block order
      a bye        is_bye, player2 None, and the occupant IS the winner —
                   they advance, and that is how later rounds inherit them
      round r > 1  match n joins the winners of round r-1 matches 2n-1 and 2n,
                   so a bye occupant lands pre-placed on the correct SIDE
                   (p1 from the odd feeder, p2 from the even one) and every
                   other slot stays empty until a result arrives

    NO RESULTS ARE CARRIED, deliberately. The cup tree holds scores and
    winners, but this returns the SHAPE only: a draw whose matches arrive with
    no winners cannot clear a winner the result pipeline has already written —
    the hazard recorded in feedback_scraper_clears_espn_winner. Bye winners are
    the one exception, and they are structural rather than a result.
    """
    from app.services.scraper import MatchResult, ParsedDraw, PlayerEntry

    players = [
        PlayerEntry(bracket_position=e.bracket_position, name=e.name,
                    nationality=e.nationality, seed=e.seed, entry_type=e.entry_type)
        for e in shape.entrants
    ]
    byes = set(shape.byes)
    occupied = {e.bracket_position for e in shape.entrants}

    matches: list = []
    # Round 1: one match per pair of slots, in slot order.
    winners_by_match: dict = {}
    for n in range(1, shape.bracket_size // 2 + 1):
        lo, hi = n * 2 - 1, n * 2
        a = lo if lo in occupied else None
        b = hi if hi in occupied else None
        is_bye = (lo in byes) or (hi in byes)
        if is_bye:
            # The occupant plays nobody and advances.
            who = a if a is not None else b
            matches.append(MatchResult(
                round_number=1, match_number=n, player1_position=who,
                player2_position=None, winner_position=who, is_bye=True))
            winners_by_match[n] = who
        else:
            matches.append(MatchResult(
                round_number=1, match_number=n, player1_position=a,
                player2_position=b, winner_position=None, is_bye=False))

    # Later rounds: skeletons, carrying only the advancers already known.
    prev = winners_by_match
    count = shape.bracket_size // 2
    for rnd in range(2, shape.num_rounds + 1):
        count //= 2
        nxt: dict = {}
        for n in range(1, count + 1):
            matches.append(MatchResult(
                round_number=rnd, match_number=n,
                player1_position=prev.get(n * 2 - 1),
                player2_position=prev.get(n * 2),
                winner_position=None, is_bye=False))
        prev = nxt          # nothing is decided beyond a first-round bye

    named = [p for p in players if (p.name or "").strip()]
    return ParsedDraw(
        draw_size=shape.bracket_size,
        num_rounds=shape.num_rounds,
        players=players,
        matches=matches,
        has_direct_draw=bool(named),
        has_qualifiers=any(p.entry_type == "Q" for p in players),
        has_final_winner=False,
        carries_dates=False,        # shape only: the writer leaves dates alone
        carries_results=False,      # and judges status from the matches it holds
    )
