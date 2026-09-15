/* IS PLAY ACTUALLY HAPPENING? — one reading, for the schedule.
 *
 * The server already answers this. `status` is computed per row at serve time
 * (routers/schedule.py), and it weighs the live payload, the sheet, the venue
 * clock and the match's result together before deciding between "live",
 * "to_be_completed", "postponed" and the rest. A client that consults
 * `live_scores[4]` on its own is holding a second opinion built from one of
 * those inputs, and that input is stale by construction for the rows that
 * matter most.
 *
 * 2026-09-16, SP Open: Tuesday's rain carried three R32 matches into
 * Wednesday, and the sheet printed "Not before 2:00 PM" against each of them.
 * The page showed no time at all on those three rows — the only rows on the
 * day with nothing in the time line — because `underWay` read the frozen
 * `live_scores[4] === 'suspended'` from the night play stopped as "on court
 * right now". The flag was not wrong; it means "the score stands where play
 * stopped", which is exactly true of a match waiting to resume tomorrow. It
 * simply does not mean anyone is playing. `mobile/schedule.js` already gated
 * its own `isSuspended` on the status for this reason; the web was the copy
 * that never got the gate.
 */

/** Play has stopped mid-match and the score stands — a sub-state of live.
 *  Never true of a row waiting for a NEW slot: a carried or postponed match
 *  keeps the suspended flag in its frozen payload forever. */
export function isSuspended(e) {
  return e?.status === 'live'
    && (e?.live_scores?.[4] === 'suspended' || !!e?.live_point?.suspended)
}

/** On court, finished, or stopped mid-match: the row's time line goes away,
 *  because the badge and the score say more than the hour would.
 *
 *  NOT postponed or to-be-completed, though both have played some tennis.
 *  Those rows are waiting for a new slot, and when they will resume is the one
 *  thing a reader actually wants from them. */
export function isUnderWay(e) {
  return e?.status === 'live' || e?.status === 'completed' || isSuspended(e)
}
