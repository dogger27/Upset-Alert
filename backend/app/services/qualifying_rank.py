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

    The bracket's rule, which the grey badge beside a main-draw name already
    follows:

    * a SEEDED player's place is their seed — a field's [1] is its first
      player, whatever the rankings say about who else is in it;
    * the unseeded follow in ranking order, numbered on from the last seed, so
      in a field of sixteen with eight seeds the best unseeded player is 9th
      and never 1st;
    * a player with no ranking sorts LAST, not first: no ranking held is not a
      good one. Ties break on the key, so the same field always numbers the
      same way.
    """
    seeded = {k: v[0] for k, v in field.items() if v[0] is not None}
    places = dict(seeded)
    offset = max(seeded.values(), default=0)
    unseeded = sorted(((k, v[1]) for k, v in field.items() if k not in seeded),
                      key=lambda kv: (kv[1] is None, kv[1] or 0, kv[0]))
    for i, (key, _ranking) in enumerate(unseeded):
        places[key] = offset + i + 1
    return places

