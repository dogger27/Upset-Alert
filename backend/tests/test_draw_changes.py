"""What counts as the same player written differently — and what does not."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test")

from app.services.draw_changes import classify_change, same_person

SAME = [
    ("Qinwen Zheng", "Zheng Qinwen"),        # the reported alarm
    ("Zheng Qinwen", "Qinwen Zheng"),
    ("Frances Tiafoe", "Francis Tiafoe"),    # the first one, a one-letter edit
    ("J. Struff", "Jan-Lennard Struff"),
    ("Alex Bublik", "Alexander Bublik"),
    ("Carreno Busta", "Carreño Busta"),
    ("Camila Osorio", "Maria Camila Osorio Serrano"),
    ("Yibing Wu", "Wu Yibing"),
    ("Naomi Osaka", "Osaka Naomi"),
]

DIFFERENT = [
    ("Alexander Zverev", "Mischa Zverev"),   # brothers: a real replacement
    ("Emma Navarro", "Emma Raducanu"),
    ("Qinwen Zheng", "Saisai Zheng"),        # same surname, different player
    ("Zheng Qinwen", "Zheng Saisai"),        # ...and written the other way
    ("Carlos Alcaraz", "Jannik Sinner"),
    ("Taylor Fritz", "Taylor Townsend"),
]

def main():
    bad = 0
    for a, b in SAME:
        ok = same_person(a, b) and classify_change(a, b) is None
        print(('  PASS ' if ok else '  FAIL ') + f'same:      {a!r} == {b!r}')
        bad += not ok
    for a, b in DIFFERENT:
        ok = (not same_person(a, b)) and classify_change(a, b) == "replaced"
        print(('  PASS ' if ok else '  FAIL ') + f'different: {a!r} != {b!r}')
        bad += not ok
    print("ALL PASS" if not bad else f"{bad} FAILURES")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
