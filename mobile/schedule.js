/*
 * Reading one line of an order-of-play sheet.
 *
 * THREE SOURCES OF SCORE, IN PRIORITY ORDER, and they are not interchangeable:
 *
 *   live_point   Sofascore. Games AND the current point (40-30). Best.
 *   live_scores  ESPN. Games only — it has no point to give, so showing "0-0"
 *                would confidently invent love-all through an entire game.
 *   scores       the final result, once the match is over.
 *
 * Everything here is display-only. Nothing infers a result.
 */

export function sideName(players, side) {
  const ps = (players || []).filter(p => p.side === side)
  if (!ps.length) return 'TBD'
  // entry_name is proper case; `name` is the sheet's SURNAME IN CAPS. Doubles
  // has two per side, joined the way a scoreboard does.
  return ps.map(p => p.entry_name || p.name || 'TBD').join(' / ')
}

/* The flag codes for a side, in the order the names are joined — so doubles
   shows both. Deliberately parallel to sideName: if one shows two names, the
   other must offer two flags or they cannot be lined up. */
export function sideFlags(players, side) {
  return (players || []).filter(p => p.side === side).map(p => p.nationality || null)
}

export function sideSeed(players, side) {
  const p = (players || []).find(x => x.side === side && x.seed)
  return p?.seed ?? null
}

/* The inferred seed, for the badge to fall back to. Main-draw singles only —
   the server withholds it for doubles and qualifying, where a draw_entry_id
   points at the player's SINGLES row and any number read off it would describe
   a different event. */
export function sideDrawRank(players, side) {
  const p = (players || []).find(x => x.side === side && x.draw_rank != null)
  return p?.draw_rank ?? null
}

/** [[a games], [b games]] from whichever source has them, or null. */
export function gamesOf(e) {
  if (e?.live_point?.games) return e.live_point.games
  if (Array.isArray(e?.live_scores) && e.live_scores.length >= 2) {
    return [e.live_scores[0], e.live_scores[1]]
  }
  if (e?.scores) return e.scores
  return null
}

/** ["40","30"] while the point is known, else null. Never fabricated. */
export function pointOf(e) {
  const p = e?.live_point?.point
  return Array.isArray(p) && p.length === 2 ? p : null
}

export function servingSide(e) {
  const s = e?.live_point?.serving
    ?? (Array.isArray(e?.live_scores) ? e.live_scores[2] : null)
  return s === 1 ? 'a' : s === 2 ? 'b' : null
}

export function winnerSide(e) {
  if (e?.winner_side === 0) return 'a'
  if (e?.winner_side === 1) return 'b'
  return null
}

export function isLive(e) {
  return e?.status === 'live' || !!e?.live_point?.suspended
}

export function isSuspended(e) {
  return e?.live_scores?.[4] === 'suspended' || !!e?.live_point?.suspended
}

/* When it starts, in the words the sheet used.
   start_note carries the sheet's own phrasing ("Followed By", "Not Before
   2:00 PM") and that is more honest than a clock we computed — those matches
   genuinely have no time. */
export function whenLabel(e) {
  if (e?.status === 'completed') return 'Final'
  if (isSuspended(e)) return 'Suspended'
  if (e?.status === 'live') return 'On court'
  if (e?.start_time_local) return e.start_time_local
  if (e?.start_note) return e.start_note
  return ''
}
