"""The serve-split guard, checked against figures actually observed.

Sofascore counts nearly every serve as a FIRST serve while a match is in play
and corrects the split about ten minutes after the final point. There is no
structural test for it — the broken payload is internally consistent — so the
guard tests plausibility, and these are the real numbers it has to separate.

    .venv/bin/python tests/test_serve_split_guard.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.sofascore_stats import (          # noqa: E402
    SPLIT_DEPENDENT, _split_is_impossible,
)


def row(home, away):
    return [{"section": "Serve", "label": "First serve %",
             "home": list(home), "away": list(away)}]


def check(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    return cond


def main():
    ok = True

    # Event 16901511, read repeatedly through the live match. Every sample sat
    # between 93% and 99% — impossible, and the reason this guard exists.
    ok &= check("live 138/140 + 122/130 (99%/94%) is rejected",
                _split_is_impossible(row((138, 140), (122, 130))))
    ok &= check("live 105/112 + 95/108 (94%/88%) is rejected",
                _split_is_impossible(row((105, 112), (95, 108))))

    # The SAME match ten minutes after it finished: denominators untouched,
    # forty serves reclassified. This is the figure a reader should see.
    ok &= check("corrected 98/140 + 74/130 (70%/57%) is accepted",
                not _split_is_impossible(row((98, 140), (74, 130))))

    # Three matches that were already over when first read.
    ok &= check("finished 40/81 + 44/76 (49%/58%) is accepted",
                not _split_is_impossible(row((40, 81), (44, 76))))

    # One side alone being impossible is enough: the split is per match, and a
    # payload that has it wrong for one player has it wrong.
    ok &= check("one impossible side rejects the pair",
                _split_is_impossible(row((60, 100), (122, 130))))

    # A genuinely big serving day must still get through, or the guard would
    # hide real data. 80% is high but has been done.
    ok &= check("a real 80% match is accepted",
                not _split_is_impossible(row((80, 100), (78, 100))))

    # No denominator yet — a match that has not started cannot be judged.
    ok &= check("0/0 is not called impossible",
                not _split_is_impossible(row((0, 0), (0, 0))))

    ok &= check("every split-derived row is named in SPLIT_DEPENDENT",
                SPLIT_DEPENDENT == {
                    "First serve %", "First serve points won",
                    "Second serve points won", "1st serve return points won",
                    "2nd serve return points won"})

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
