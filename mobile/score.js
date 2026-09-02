/* The site's score rules (utils/score.jsx parseSet and MatchScoreCard's
   CompetitorRows), as plain functions so the schedule row and the history
   sheet draw a score the same way and the rules can be tested under node.

   A cell is a string the way the feeds print it: "6", "7(7)" — games with the
   tiebreak in brackets — "0r" for the set a player retired in, "w/o" for a
   walkover. The site renders the tiebreak as a superscript and the marker as
   a word before the tick; "7(7)" and "0r" printed raw were this app's bug. */

export function parseSet(cell) {
  const m = cell != null ? String(cell).replace(/r$/i, '').match(/^(\d+)(?:\((\d+)\))?/) : null
  return m ? { g: m[1], tb: m[2] ?? null } : { g: '', tb: null }
}

/* How a side's match ended, off its own cells: 'w/o' marks the player who
   ADVANCED, 'ret.' the player who QUIT. Null for an ordinary result. */
export function endedWith(scores, side) {
  const cells = (scores || [])[side] || []
  if (cells.some(c => /^w\/?o$/i.test(String(c ?? '').trim()))) return 'w/o'
  if (cells.some(c => /r$/i.test(String(c ?? '')))) return 'ret.'
  return null
}

/* ONE source per render, the site's rule: the live snapshot while a match is
   under way, the record once it is over. Mixing them put a point beside a set
   score that had already moved on. A stopped row (postponed, carried) keeps
   the record if it has one and the frozen snapshot otherwise. */
export function scoreSets(e) {
  if (!e) return null
  const lp = e.live_point ?? null
  const fromLive = lp?.games ?? (Array.isArray(e.live_scores) && e.live_scores.length >= 2
    ? [e.live_scores[0], e.live_scores[1]] : null)
  if (e.status === 'live') return fromLive ?? e.scores ?? null
  if (e.status === 'completed') return e.scores ?? null
  return e.scores ?? fromLive
}

export function setCount(sets) {
  return sets ? Math.max(sets[0]?.length ?? 0, sets[1]?.length ?? 0) : 0
}

/* Did `side` (0/1) win set `i`? The set in play is never "won", and a match
   tiebreak has no set in play. */
export function setWon(sets, i, side, live, lp) {
  if (!sets) return false
  const n = setCount(sets)
  if (live && i === n - 1 && !lp?.match_tiebreak) return false
  const x = Number(parseSet(sets[0]?.[i]).g), y = Number(parseSet(sets[1]?.[i]).g)
  if (Number.isNaN(x) || Number.isNaN(y)) return false
  return side === 0 ? x > y : y > x
}

/* Who won, 0/1 or null, in the site's order of trust:
   1. the server says so (a recorded fact);
   2. the end marker — "w/o" names the side that advanced, "ret." the side
      that quit, and both describe matches a scoreline cannot;
   3. only then, counting sets — WRONG for a player who retires while ahead,
      so reached only for an ordinary completed row the server did not mark. */
export function winnerSideOf(e) {
  if (e?.winner_side === 0 || e?.winner_side === 1) return e.winner_side
  if (e?.status !== 'completed') return null
  if (endedWith(e.scores, 0) === 'w/o') return 0
  if (endedWith(e.scores, 1) === 'w/o') return 1
  if (endedWith(e.scores, 0) === 'ret.') return 1
  if (endedWith(e.scores, 1) === 'ret.') return 0
  const sets = e.scores
  if (!sets) return null
  let x = 0, y = 0
  for (let i = 0; i < setCount(sets); i++) { if (setWon(sets, i, 0, false)) x++; if (setWon(sets, i, 1, false)) y++ }
  return x === y ? null : (x > y ? 0 : 1)
}
