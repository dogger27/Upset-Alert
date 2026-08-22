"""
Hands Sofascore the result columns when the evidence says it has earned them,
and takes them back the moment it stops.

Why this is automatic rather than a note in someone's calendar: the decision
depends on a measurement that can only be taken while a tournament is actually
being played, and the window for taking it closes when the tournament ends. A
human who has to remember to run a script on finals day will, eventually, not —
and the cost of forgetting is that the whole exercise waits for the next event.
The machine has no such problem, and this is a judgement it can make correctly
because every input to it is a number.

WHAT IT DECIDES. Only which source writes `winner_id`, `scores_json`,
`started_at` and `completed_at`. Both sweeps keep running and keep writing their
own columns either way, so nothing is lost by being wrong and nothing has to be
migrated back. That is the property that makes this safe to automate: the switch
is a read of one boolean at the top of a write path.

WHAT IT WILL NOT DO. It will not cut over on coverage alone. Agreement across a
draw that finished last week says the parser works; it does not say Sofascore
will see tomorrow's final. The gate below therefore leans on matches that
finished while BOTH sources were watching, and stays shut until there are enough
of them.

AND IT WATCHES AFTERWARDS. A gate that only ever opens is half a mechanism. Once
Sofascore is authoritative the same numbers keep being computed, and a single
winner disagreeing puts ESPN back in charge immediately — before the next
scoring run reads it, rather than after somebody notices their standings are
wrong.
"""

import asyncio
import logging

from app.core.config import settings as env
from app.database import AsyncSessionLocal
from app.services.settings import (load_sofa_authoritative, set_sofa_authoritative,
                                   sofa_authoritative)
from app.services.sofa_compare import compare, timing
from app.services.system_log import app_log

logger = logging.getLogger(__name__)

# Hourly. The measurement only changes when a match finishes, and matches finish
# a few times a day at most — but the interesting ones cluster on finals day and
# waiting until tomorrow to notice would miss the event it needs to be measured
# against.
POLL_INTERVAL = 3600.0

# Settle before the first check. Both sweeps have to have run at least once or
# the comparison is against columns nothing has filled in yet.
STARTUP_DELAY = 600.0

# ── The gate ────────────────────────────────────────────────────────────────
# Every one of these must hold. They are deliberately about DIFFERENT failure
# modes rather than being one threshold expressed five ways.

# Enough of a body of evidence that agreement is not luck. A full ATP draw is 95
# matches, so this is roughly two draws seen through to the end.
MIN_DECIDED = 150

# Matches that finished while both sources were watching. The whole point of the
# exercise: these are the only ones that say anything about tomorrow.
MIN_TIMED = 6

# How far behind ESPN Sofascore may be, on average, in minutes. Negative is
# Sofascore reporting FIRST, which is fine and expected — the tolerance is
# one-sided for that reason. Five minutes is about the gap at which a result
# arriving late would be noticed by someone watching the draw page.
MAX_LAG_AVG_MIN = 5.0

# ...and no single result may straggle. An average hides one match that took
# half an hour, and one match is all it takes for a round-complete digest to go
# out with a hole in it.
MAX_LAG_WORST_MIN = 20.0


def evaluate(result: dict) -> tuple[bool, list[str]]:
    """(pass, reasons it does not). Pure — no I/O, so it can be reasoned about.

    Reasons are phrased as what is still missing, because they are read by
    someone who wants to know how far off this is, not what the rule was.
    """
    t = result.get("totals") or {}
    lag = timing(result.get("deltas") or [])
    why = []

    # Any disagreement about a WINNER disqualifies, whenever it happened. This
    # is the field that decides league scoring; one wrong answer in the record
    # is one too many, and unlike a score it cannot be shrugged off as
    # formatting.
    if t.get("winner_mismatch"):
        why.append(f"{t['winner_mismatch']} winner mismatch(es) on record")

    # A retirement rendered as a clean win is a different match. Historical ones
    # count too: the marker is either captured by the parser or it is not.
    if t.get("retirement_lost"):
        why.append(f"{t['retirement_lost']} retirement/walkover marker(s) lost")

    # These two are restricted to the current regime. Gaps and formatting
    # differences from before the sweep existed are backfill, and holding them
    # against it would mean the gate could never open.
    if t.get("missing_recent"):
        why.append(f"{t['missing_recent']} match(es) ESPN has that Sofascore missed "
                   "since the sweep started")
    if t.get("score_mismatch_recent"):
        why.append(f"{t['score_mismatch_recent']} scoreline(s) differ since the sweep "
                   "started")

    if (t.get("decided") or 0) < MIN_DECIDED:
        why.append(f"only {t.get('decided', 0)} decided matches compared, "
                   f"want {MIN_DECIDED}")

    if lag["n"] < MIN_TIMED:
        why.append(f"only {lag['n']} match(es) finished with both sources watching, "
                   f"want {MIN_TIMED}")
    else:
        if lag["avg"] > MAX_LAG_AVG_MIN:
            why.append(f"Sofascore averages {lag['avg']:.1f} min behind ESPN, "
                       f"limit {MAX_LAG_AVG_MIN}")
        if lag["max"] > MAX_LAG_WORST_MIN:
            why.append(f"worst single result was {lag['max']:.1f} min behind, "
                       f"limit {MAX_LAG_WORST_MIN}")

    return (not why), why


def _summary(result: dict) -> dict:
    t = dict(result.get("totals") or {})
    t["timing"] = timing(result.get("deltas") or [])
    return t


async def _check_once() -> None:
    async with AsyncSessionLocal() as db:
        result = await compare(db)
        if not result.get("draws"):
            return
        t = result["totals"]
        ok, why = evaluate(result)
        live = sofa_authoritative()

        if live:
            # THE WATCHDOG. Only a winner disagreement reverses this, and only
            # winner disagreements — a scoreline that renders differently is
            # cosmetic beside handing scoring back and forth, and flapping
            # between sources would be worse than either.
            if t.get("winner_mismatch"):
                await set_sofa_authoritative(db, False)
                await db.commit()
                logger.error("Sofascore authority REVOKED — %d winner mismatch(es)",
                             t["winner_mismatch"])
                await app_log(
                    "error", "sofascore",
                    f"Sofascore authority REVOKED automatically: "
                    f"{t['winner_mismatch']} winner mismatch(es) against ESPN. "
                    f"ESPN owns results again from now; both sweeps keep running. "
                    f"Nothing needs doing to stay safe — investigate before re-enabling.",
                    _summary(result),
                    dedup_key="sofa_authority_revoked", dedup_hours=1,
                )
            return

        if not ok:
            # Not an alert. Not being ready yet is the expected state for most
            # of the life of this job, and the reasons are on the record in
            # backend.log for anyone who asks.
            logger.info("Sofascore cutover gate closed: %s", "; ".join(why))
            return

        await set_sofa_authoritative(db, True)
        await db.commit()
        lag = timing(result["deltas"])
        logger.warning("Sofascore is now AUTHORITATIVE (decided=%d, n=%d, avg=%.1f min)",
                       t["decided"], lag["n"], lag["avg"])
        await app_log(
            "warning", "sofascore",
            f"Sofascore is now the source of record for match results. "
            f"{t['decided']} decided matches compared with zero winner mismatches, "
            f"{lag['n']} of them finished while both sources were watching "
            f"(Sofascore {'behind' if lag['avg'] > 0 else 'ahead'} by "
            f"{abs(lag['avg']):.1f} min on average, worst {lag['max']:+.1f}). "
            f"ESPN keeps running and keeps its own columns; a single winner "
            f"disagreement from here reverts this automatically.",
            _summary(result),
            dedup_key="sofa_authority_granted", dedup_hours=24,
        )


async def start() -> None:
    """The loop. Silent when there is nothing to say, which is most days."""
    if not env.sofascore_results_enabled:
        # Nothing writes the shadow columns, so there is nothing to compare and
        # a gate reading empty columns would sit closed forever anyway.
        return
    async with AsyncSessionLocal() as db:
        await load_sofa_authoritative(db)
    logger.info("Sofascore cutover watch started (authoritative=%s, interval=%.0fs)",
                sofa_authoritative(), POLL_INTERVAL)
    await asyncio.sleep(STARTUP_DELAY)
    while True:
        try:
            await _check_once()
        except Exception as exc:
            # A failure to MEASURE must never be read as a failure to agree.
            # Leaving whatever is in force in force is the safe answer either
            # way round: not yet cut over stays not cut over, and already cut
            # over is not revoked by our own bug.
            logger.warning("Sofascore cutover check failed: %s", exc)
        await asyncio.sleep(POLL_INTERVAL)
