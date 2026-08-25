"""
The law of the schedule: every shape a day's entries must satisfy, as CODE.

Each rule here exists because a real bug shipped it — the header of every
check names the incident. The LLM verifier judges; this module does not: it
runs on every ingest, on a 15-minute sweep, and UNDER the verifier's verdict
(the runner re-checks and overrides a "clean" that an invariant contradicts).
An LLM checklist has loopholes; a law does not.

THE RATCHET: when a new schedule bug is fixed — by a human or by the
verifier — a check for its class is added HERE in the same commit. That is
what makes the system converge on "never again" instead of on a longer
checklist.
"""

import re

from sqlalchemy import select

from app.models.schedule import ScheduleEntry
from app.services.oop_parser import COUNTRY_CODES

# The sheet's own words, in the places a name can pick them up. A slot wording
# printed on its own line sits directly above or below a name and has been
# absorbed by both ends of the parse before now.
_SLOT_WORDING_RE = re.compile(
    r'\b(?:TB[ACD]|followed\s+by|not\s+bef|start(?:s|ing)?\s+at|'
    r'to\s+be\s+(?:arranged|confirmed|announced|advised|determined))\b', re.I)
_TRAILING_SEED_RE = re.compile(r'(?:\s*\[[^\]]*\])+\s*$')
_TRAILING_CODE_RE = re.compile(r'\s([A-Z]{3})$')
# Order-of-play sheets print the SURNAME in capitals, every tour, every tier.
# A stored name with no capitalised run therefore did not come from the sheet.
_SHEET_CAPS_RE = re.compile(r'(?<![A-Za-z])[A-Z]{2,}(?![a-z])')
# The qualifying round tokens, enumerated — "QF" starts with Q and is not one.
_QUALI_ROUND_RE = re.compile(r'^(?:Q\d?|FQ)$', re.I)


async def check_day(db, tournament_id: int, play_date) -> list[dict]:
    """Every violation in one tournament-day. Empty list = lawful."""
    rows = (await db.execute(
        select(ScheduleEntry).where(
            ScheduleEntry.tournament_id == tournament_id,
            ScheduleEntry.play_date == play_date,
        ))).scalars().all()

    v: list[dict] = []

    # 2026-08-25, "CHOINSKI or ROTTGERING" beside a bracket that already knew
    # Rottgering had won: an unresolved side whose deciding match is complete
    # asserts an open question the draw has closed. The resolver
    # (schedule.resolve_settled_alternatives) collapses these from every
    # winner-writing path; this is the tripwire if any path forgets.
    from app.models.tournament import Draw, DrawEntry, Match
    from app.services.schedule import _fold
    draw_ids = (await db.execute(
        select(Draw.id).where(Draw.tournament_id == tournament_id))).scalars().all()
    dents = (await db.execute(
        select(DrawEntry).where(DrawEntry.draw_id.in_(draw_ids)))).scalars().all() if draw_ids else []
    by_fold = {}
    for de in dents:
        by_fold.setdefault(_fold(de.name), []).append(de.id)
    decided = {frozenset((m.player1_id, m.player2_id)): m.winner_id
               for m in (await db.execute(
                   select(Match).where(Match.draw_id.in_(draw_ids),
                                       Match.winner_id.isnot(None)))).scalars().all()
               if m.player1_id and m.player2_id} if draw_ids else {}
    # Every real bracket pairing, decided or not. `decided` above only holds
    # finished matches; linking a slot is about the pairing existing at all.
    pair_match = {frozenset((m.player1_id, m.player2_id)): m.id
                  for m in (await db.execute(
                      select(Match).where(Match.draw_id.in_(draw_ids),
                                          Match.player1_id.isnot(None),
                                          Match.player2_id.isnot(None)))).scalars().all()
                  } if draw_ids else {}

    def flag(code, entry, detail):
        v.append({"code": code, "entry_id": entry.id if entry else None,
                  "court": getattr(entry, "court", None), "detail": detail})

    seen_pairings: dict[frozenset, int] = {}
    court_orders: dict[tuple, int] = {}

    for e in rows:
        players = list(e.players or [])
        na = [p for p in players if p.side == "a"]
        nb = [p for p in players if p.side == "b"]
        tbd_side = e.tbd_side or ""

        if e.is_tbd:
            for side_key in (e.tbd_side or "ab"):
                rows_side = [p for p in players if p.side == side_key]
                if len(rows_side) < 2:
                    continue
                ids = []
                for r in rows_side:
                    if r.draw_entry_id:
                        ids.append(r.draw_entry_id); continue
                    cand = by_fold.get(_fold(r.raw_name)) or []
                    if len(cand) == 1:
                        ids.append(cand[0])
                    else:
                        ids = None; break
                if ids and frozenset(ids) in decided:
                    flag("alternatives_already_decided", e,
                         f"side {side_key}: "
                         + " or ".join(r.raw_name or "" for r in rows_side)
                         + " — feeder match has a winner")

        # tbd_side must be one of a/b/ab — anything else means a writer
        # invented a value nothing downstream reads. (Defensive; no incident.)
        if e.tbd_side not in (None, "", "a", "b", "ab"):
            flag("tbd_side_invalid", e, f"tbd_side={e.tbd_side!r}")

        # 2026-08-25, Medvedev vs "DAMM / SHELBAYH": a singles slot stored an
        # unresolved "A or B" as two players on one side with no tbd flag, and
        # the site rendered a phantom doubles team. Two names on a singles
        # side are legal ONLY when that side is declared unresolved.
        if e.discipline == "singles":
            for side_key, side in (("a", na), ("b", nb)):
                if len(side) > 1 and side_key not in tbd_side:
                    flag("singles_side_stacked", e,
                         f"side {side_key}: " + " / ".join(p.raw_name or "" for p in side))

        # 2026-08-24, "KRAJICEK / MEKTIC vs CABRAL": a doubles team of one,
        # because an all-caps given name was dropped by the parser. A doubles
        # side that is neither empty (slot not yet decided) nor declared
        # unresolved must hold exactly two.
        if e.discipline == "doubles":
            for side_key, side in (("a", na), ("b", nb)):
                if side and len(side) != 2 and side_key not in tbd_side:
                    flag("doubles_side_not_two", e,
                         f"side {side_key} has {len(side)}: "
                         + " / ".join(p.raw_name or "" for p in side))

        # 2026-08-25, Monterrey "Alexandra PANOVA TBC": Cancha 4's last slot
        # printed a bare "TBC" where a start time would go, one line below the
        # doubles pair above it. Three capitals on their own line is also how
        # the layout wraps a nationality, so the parser read it as one and gave
        # Panova a country nobody has. The sheet's own words are never part of
        # a name, and where a name ends in a country code it has to BE a
        # country — LUZ, GUO and TBC all have the shape.
        for p in players:
            raw = (p.raw_name or "").strip()
            if _SLOT_WORDING_RE.search(raw):
                flag("name_holds_slot_wording", e,
                     f"side {p.side}: {raw!r} contains a slot wording")
            stripped = _TRAILING_SEED_RE.sub("", raw)
            m = _TRAILING_CODE_RE.search(stripped)
            if m and m.group(1) not in COUNTRY_CODES:
                before = stripped[:m.start()].split()
                # Only where a country would stand: after a SURNAME, which the
                # sheets print in capitals. "Orlando LUZ" ends in three
                # capitals too and is a whole name.
                if any(w.isupper() and any(c.isalpha() for c in w) for w in before):
                    flag("name_trailing_noncountry", e,
                         f"side {p.side}: {raw!r} ends in {m.group(1)!r}, not a country")

        # 2026-08-25, "Mees ROTTGERING vs Tomas MACHAC": the draw stores
        # "Mees Röttgering", `rankings._norm` expands the umlaut the German
        # way to "roettgering", and the sheets print plain ASCII — so the
        # ingest's two matchers never met the draw and a main-draw R32 sat on
        # the live page with no round badge, no player links and no scores
        # while the bracket had held the pairing for a day. `schedule._fold`
        # existed for exactly this and only one caller had been moved onto it.
        # A settled main-draw singles slot whose sides each name exactly one
        # draw entry, and whose pair IS a bracket match, must be linked to it.
        if (e.discipline == "singles" and e.stage == "main"
                and e.match_id is None and not e.is_tbd and na and nb):
            sides = [{i for p in side
                      for i in (by_fold.get(_fold(p.raw_name)) or [])}
                     for side in (na, nb)]
            if all(len(c) == 1 for c in sides):
                pair = frozenset((next(iter(sides[0])), next(iter(sides[1]))))
                if len(pair) == 2 and pair in pair_match:
                    flag("bracket_match_missed", e,
                         " vs ".join(p.raw_name or "" for p in (na[0], nb[0]))
                         + f" is bracket match {pair_match[pair]}, "
                           "but match_id is NULL")

        # 2026-08-25, Medvedev vs Damm: the row was created from a revision
        # that printed the slot unresolved, the bracket resolver replaced both
        # players with their DRAW names, and `raw_name` was write-once — so
        # two later revisions printing "[WC] Martin DAMM USA" could not undo
        # it. The page showed one line in Title Case with no flag and no [WC]
        # beside sixteen carrying both. Four rows across three tournaments
        # were frozen that way. A settled side must read as the sheet prints
        # it; an unresolved side is exempt, because sheets abbreviate the
        # alternatives they offer ("D. Parry or D. Vekic").
        for p in players:
            raw = (p.raw_name or "").strip()
            if raw and p.side not in tbd_side and not _SHEET_CAPS_RE.search(raw):
                flag("name_not_sheet_form", e,
                     f"side {p.side}: {raw!r} has no capitalised surname — "
                     f"not the sheet's rendering")

        # 2026-08-24, Winston-Salem's three main-draw doubles matches, two of
        # them badged "Q": _classify's last-resort qualifying inference is
        # evidence about the SINGLES draw (not in `draw_entries`; surname seen
        # on a qualifying row this week) and it was being applied to doubles
        # rows, where the first half is vacuously true — we store no doubles
        # draw — and the second is the ordinary career of a doubles player who
        # also entered singles qualifying. A doubles row may only be qualifying
        # when the SHEET said so, which reaches us as a qualifying round label.
        if (e.discipline == "doubles" and e.stage == "qualifying"
                and not _QUALI_ROUND_RE.match((e.round_label or "").strip())):
            flag("doubles_qualifying_unstated", e,
                 f"doubles row filed stage=qualifying with round_label="
                 f"{e.round_label!r} — nothing on the sheet says qualifying")

        # An entry with no players on either side describes nothing; it can
        # only be parser debris. (Defensive; near-miss during the Winston-Salem
        # blank-qualifier work — blanks are meant to be filtered, not stored.)
        if not players:
            flag("entry_empty", e, "no players on either side")

        # 2026-08-24, Sonego-Kopriva: a superseded pairing survived a lucky-
        # loser substitution and the day showed 16 matches for a 15-match
        # sheet. Two settled entries naming the same players are one slot.
        if not e.is_tbd and players:
            key = frozenset((p.raw_name or "").strip().lower() for p in players)
            if key in seen_pairings:
                flag("pairing_duplicated", e,
                     f"same players as entry {seen_pairings[key]}")
            else:
                seen_pairings[key] = e.id

        # Two entries at one court_order on one court means the renumber pass
        # broke; the schedule page would show them in arbitrary order.
        if e.court and e.court_order is not None:
            ck = (e.court, e.court_order)
            if ck in court_orders:
                flag("court_order_duplicated", e,
                     f"{e.court} #{e.court_order} also entry {court_orders[ck]}")
            else:
                court_orders[ck] = e.id

    return v


async def check_and_log(db, tournament, play_date) -> list[dict]:
    """Run the law and put violations where the alert digest reads."""
    from app.services.system_log import app_log

    violations = await check_day(db, tournament.id, play_date)
    if violations:
        await app_log(
            "error", "order_of_play",
            f"{len(violations)} schedule invariant violation(s) in "
            f"{tournament.name} on {play_date}: "
            + "; ".join(f"{x['code']} ({x['detail'][:60]})" for x in violations[:5]),
            {"tournament_id": tournament.id, "play_date": str(play_date),
             "violations": violations[:20]},
            dedup_key=f"sched_invariants_{tournament.id}_{play_date}",
            dedup_hours=6)
    return violations


async def sweep(db) -> int:
    """The law applied to every tournament-day near now.

    Entries keep changing AFTER ingest — dedupe absorbs rows, alternatives
    resolve to winners, courts renumber — so checking only at ingest time
    would miss a violation those passes introduce. Returns total violations.
    """
    from datetime import date, timedelta

    from app.models.tournament import Tournament

    today = date.today()
    days = [today - timedelta(days=1), today, today + timedelta(days=1)]
    pairs = (await db.execute(
        select(ScheduleEntry.tournament_id, ScheduleEntry.play_date)
        .where(ScheduleEntry.play_date.in_(days)).distinct())).all()
    total = 0
    for tid, day in pairs:
        t = await db.get(Tournament, tid)
        if t is None:
            continue
        total += len(await check_and_log(db, t, day))
    return total


if __name__ == "__main__":  # pragma: no cover
    # `python -m app.services.schedule_invariants [tournament_id play_date]`
    # — the verifier's first move, and the runner's gate under its verdict.
    # Prints one JSON line; exit code 1 when violations exist.
    import asyncio
    import json as _json
    import sys

    async def _main():
        from app.database import AsyncSessionLocal
        from app.models.tournament import Tournament

        async with AsyncSessionLocal() as db:
            if len(sys.argv) >= 3:
                t = await db.get(Tournament, int(sys.argv[1]))
                out = await check_day(db, int(sys.argv[1]), sys.argv[2]) if t else []
            else:
                n = await sweep(db)
                out = [{"code": "sweep_total", "detail": str(n)}] if n else []
        print(_json.dumps(out))
        sys.exit(1 if out else 0)

    asyncio.run(_main())
