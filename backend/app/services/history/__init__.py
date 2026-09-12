"""Our own match history and the ratings built from it.

Three layers, each a module:

    db.py       the history database (a separate SQLite file) and its schema
    tml.py      the TennisMyLife sync: every results file they publish, kept current
    link.py     OUR tournaments and players paired with THEIR ids, exactly where
                possible, and our own finished matches exported beside theirs
    ratings.py  a chronological Elo over the whole record — overall and per
                surface — and the current rating of every player in a draw

The principle the owner set (2026-09-12): use our own data wherever possible,
keep collecting it, and treat name matching as the backup, not the method.

STATUS (2026-09-12): the record, the linkage and the nightly recompute are
live; the rating itself is wired into the standings but switched off
(winprob/models.json "own".fitted) because on this season's matches it
judges behind Tennis Abstract's Elo — see scripts/fit_own_elo.py, which is
the only thing allowed to flip that switch.
"""
