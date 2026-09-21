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


def compare_to_entries(shape: DrawShape, entries: list) -> dict:
    """Where the cup tree and our stored draw_entries differ.

    `entries` is our DrawEntry rows (name, bracket_position, seed, entry_type).
    Returns counts plus the specific disagreements, so a caller can log one
    line and a reader can chase any of them.
    """
    # Three keys per entry, most trustworthy first: the name as we hold it,
    # the name SOFASCORE gave the resolver for this very entry (already stored
    # on the row, so this reuses matching that is proven rather than repeating
    # it), and finally the order-insensitive form.
    ours: dict = {}
    for e in entries:
        if not (e.name or "").strip():
            continue
        for key in (_fold(e.name), _fold(getattr(e, "sofa_name", "") or ""),
                    _unordered(e.name)):
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
        for key in (_fold(s.name), _unordered(s.name)):
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
        if mine.bracket_position != s.bracket_position:
            out["position"].append((s.name, mine.bracket_position, s.bracket_position))
        if s.seed is not None and mine.seed != s.seed:
            out["seed"].append((s.name, mine.seed, s.seed))
        if s.entry_type and (mine.entry_type or None) != s.entry_type:
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
