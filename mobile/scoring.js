/*
 * The two comparisons that decide what the standings and picks screens SAY.
 *
 * Pulled out of the screens so they can be tested without a renderer. Both
 * encode rules that fail silently — a wrong answer here looks like a working
 * app that quietly disagrees with the website.
 */

/* Level on total AND on every round.
 *
 * The server sorts entries by total points, then by points in the latest
 * rounds first (Final -> SF -> QF -> ...). That tiebreak is LEXICOGRAPHIC over
 * the round vector, not a weighted sum, so two people on the same total are
 * only actually tied if their whole round vector matches. Comparing totals
 * alone would call them tied and give them the same rank when the server has
 * deliberately ordered one above the other.
 */
export function sameStanding(a, b) {
  if (!a || !b || a.total !== b.total) return false
  const x = a.round_points || [], y = b.round_points || []
  return x.length === y.length && x.every((v, i) => v === y[i])
}

/* Competition ranking: 1, 1, 1, 4 — not 1, 1, 1, 2.
 * Genuinely level people share a rank, and the next person takes the position
 * they actually occupy. */
export function competitionRanks(entries) {
  const out = []
  entries.forEach((e, i) => {
    out.push(i > 0 && sameStanding(entries[i - 1], e) ? out[i - 1] : i + 1)
  })
  return out
}

/* What to print in one side of a match.
 *
 * A named entrant always wins: in a bye match one side IS a real player, and
 * labelling both sides "Bye" hides who received it. An empty slot is NOT a
 * bye — power-of-two draws have zero byes, so a null player is a match whose
 * feeder has not been played. A drawn-but-unnamed qualifier slot reads
 * "Qualifier", which is what the draw sheet says. */
export function slotLabel(entry, match) {
  if (entry?.name) return entry.name
  if (match?.is_bye) return 'Bye'
  if (!entry) return 'TBD'
  return entry.entry_type === 'Q' ? 'Qualifier' : 'TBD'
}
