"""The qualifying field's own order — the inferred seed for a qualifying row.

The shape of the singles badge (services/upsets.py::_compute_draw_ranks) and
of the doubles pair's (services/doubles_rank.py), for the one field neither of
them can describe: `draw_entries` holds the MAIN draw, which a qualifier
reaches only by winning through and never reaches at all if they lose, so a
qualifying row had no badge behind its name.

Kept apart from the router that feeds it so the ORDER can be proved without a
database: what goes in is what we know about each player in the field, what
comes out is where each of them sits in it.
"""
def qualifying_places(field: dict) -> dict:
    """{key: (seed, ranking)} -> {key: place in the field}.

    The order is the bracket's: seeds first, in seed order, then everyone else
    by ranking. A player with no ranking sorts LAST, not first — no ranking
    held is not a good one — and ties break on the key, so a page polled every
    ten seconds does not shuffle its badges.

    The PLACES are then handed out 1..N down that order, rather than each seed
    keeping its own number as a main-draw entry does. The difference only
    shows when the seeds are not all known, and that is exactly the case this
    has to survive: a qualifying field's seeds are read off whichever rows the
    feeds happened to mark, and Hangzhou's 2026-09-22 arrived with one of its
    seeds stated — the [7]. Numbering the unseeded on from the highest KNOWN
    seed put fifteen players into places 8 to 22 in a field of sixteen, which
    is a badge that cannot be true. Down a single order, a field of N always
    numbers 1..N.

    Where every seed IS known — the ordinary case, and every main draw — the
    two rules agree exactly: eight seeds take 1-8 and the rest follow at 9.
    """
    order = sorted(field.items(),
                   key=lambda kv: (kv[1][0] is None,          # seeds lead
                                   kv[1][0] or 0,             # …in seed order
                                   kv[1][1] is None,          # then the ranked
                                   kv[1][1] or 0,             # …best first
                                   kv[0]))
    return {key: place for place, (key, _v) in enumerate(order, 1)}
