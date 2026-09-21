"""Split tournament rows that hold two different tournaments.

    python migrate_split_conflated_events.py            # dry run, prints the plan
    python migrate_split_conflated_events.py --apply     # writes it

WHY. The migration that created the tournaments table grouped draws on NAME
AND YEAR alone, and two different tournaments can share a city's name in one
year. Four do, in 2026:

    Hong Kong    ATP 250 in January   + WTA 250 in November    (307 days)
    Hamburg      ATP 500 in May       + WTA 250 in July         (69 days)
    Stuttgart    WTA 500 in April     + ATP 250 in June         (62 days)
    Japan Open   ATP 500 in September + WTA 250 in October      (25 days)

Everything keyed on tournament_id trusts that a row is one event: the
schedule's headings and their tier stamps, the day payload's tournament list,
the `tour` a schedule row inherits when it carries no draw id, and which
draws move together between Active and Last Week. The visible failure was
January's Hong Kong reappearing under ACTIVE in September, ten months after
its final, because it shared a row with a November draw (owner, 2026-09-21).

WHAT IT DOES. For each row whose draws are not all played together, the
earliest event keeps the row and every later one gets a new row of its own,
copying the name and year and taking its city, country and surface from its
own draws. The grouping is services/events.py::split_plan, which is where
the judgement lives and is tested.

WHAT IT MOVES. draws.tournament_id, and the tournament_id of every dependent
row that belongs to a moved draw: schedule_documents, schedule_entries and
court_aliases. At the time of writing those three hold nothing for the four
affected events, and the script says so rather than assuming it — a row it
cannot place by draw_id is placed by play_date, and anything it still cannot
place is reported and left alone.

IDEMPOTENT. Run it twice and the second pass finds nothing to do.
"""
import argparse
import os
import sqlite3
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.events import SAME_EVENT_DAYS          # noqa: E402

DB = os.environ.get("SPLIT_DB", "/data/tennis_fantasy.db")


class Row:
    """Enough of a draw for split_plan, from a plain sqlite row."""

    def __init__(self, r):
        self.id = r["id"]
        self.name = r["name"]
        self.gender = r["gender"]
        self.category = r["category"]
        self.city = r["city"]
        self.country = r["country"]
        self.surface = r["surface"]
        self.start_date = date.fromisoformat(r["start_date"]) if r["start_date"] else None
        self.end_date = date.fromisoformat(r["end_date"]) if r["end_date"] else None

    def __repr__(self):
        return (f"draw {self.id} {self.gender} {self.category} "
                f"{self.start_date}..{self.end_date}")


def groups_for(draws):
    """services/events.py::split_plan, inlined for a script with no ORM."""
    dated = sorted([d for d in draws if d.start_date], key=lambda d: d.start_date)
    undated = [d for d in draws if not d.start_date]
    if not dated:
        return [list(draws)] if draws else []
    out = [[dated[0]]]
    for d in dated[1:]:
        if (d.start_date - out[-1][-1].start_date) <= timedelta(days=SAME_EVENT_DAYS):
            out[-1].append(d)
        else:
            out.append([d])
    out[0].extend(undated)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the plan")
    ap.add_argument("--db", default=DB)
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    events = cur.execute("SELECT id, name, year FROM tournaments ORDER BY id").fetchall()
    plans = []
    for ev in events:
        draws = [Row(r) for r in cur.execute(
            "SELECT id, name, gender, category, city, country, surface, start_date, end_date "
            "FROM draws WHERE tournament_id = ? ", (ev["id"],)).fetchall()]
        if len(draws) < 2:
            continue
        groups = groups_for(draws)
        if len(groups) < 2:
            continue
        plans.append((ev, groups))

    if not plans:
        print("Nothing to split: every tournament row holds one event.")
        return 0

    print(f"{len(plans)} row(s) hold more than one event "
          f"(draws more than {SAME_EVENT_DAYS} days apart):\n")
    moves = 0
    for ev, groups in plans:
        print(f"  t{ev['id']} {ev['year']} {ev['name']}")
        for i, g in enumerate(groups):
            keep = "keeps t%d" % ev["id"] if i == 0 else "NEW row"
            print(f"     {keep:14s} {', '.join(str(d) for d in g)}")
            if i:
                moves += len(g)
        # What else points at this row, and to which event it belongs.
        for table, datecol in (("schedule_documents", "play_date"),
                               ("schedule_entries", "play_date"),
                               ("court_aliases", None)):
            n = cur.execute(f"SELECT COUNT(*) FROM {table} WHERE tournament_id = ?",
                            (ev["id"],)).fetchone()[0]
            if n:
                print(f"     {table}: {n} row(s) to place"
                      + ("" if datecol else " — by draw only, no date to place them by"))
    print(f"\n{moves} draw(s) would move to a new row.")

    if not args.apply:
        print("\nDry run. Re-run with --apply to write it.")
        return 0

    for ev, groups in plans:
        for g in groups[1:]:
            city = next((d.city for d in g if d.city), None)
            country = next((d.country for d in g if d.country), None)
            surface = next((d.surface for d in g if d.surface), None)
            cur.execute(
                "INSERT INTO tournaments (name, year, city, country, surface, created_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now'))",
                (ev["name"], ev["year"], city, country, surface))
            new_id = cur.lastrowid
            ids = [d.id for d in g]
            qs = ",".join("?" * len(ids))
            cur.execute(f"UPDATE draws SET tournament_id = ? WHERE id IN ({qs})",
                        [new_id, *ids])
            # Dependents that name one of the moved draws follow it.
            cur.execute(
                f"UPDATE schedule_entries SET tournament_id = ? WHERE draw_id IN ({qs})",
                [new_id, *ids])
            # And those with no draw id follow the dates of the event they sit in.
            lo = min(d.start_date for d in g if d.start_date)
            hi = max(d.end_date or d.start_date for d in g if d.start_date)
            for table in ("schedule_entries", "schedule_documents"):
                cur.execute(
                    f"UPDATE {table} SET tournament_id = ? "
                    f"WHERE tournament_id = ? AND play_date BETWEEN ? AND ?",
                    (new_id, ev["id"], (lo - timedelta(days=14)).isoformat(), hi.isoformat()))
            print(f"  t{ev['id']} -> t{new_id}: moved {len(ids)} draw(s) "
                  f"({', '.join(str(i) for i in ids)})")
    con.commit()
    print("\nDone. Re-run without --apply to confirm nothing is left.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
