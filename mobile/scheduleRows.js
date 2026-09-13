/*
 * Which tournaments the Schedule screen is showing, and whether a row is one.
 *
 * Its own module, free of React, so it can be tested by a plain node script
 * the way scoring.js is — the store that holds the selection needs a hook and
 * therefore needs React, and a data: URL cannot resolve a bare specifier.
 */

/* THE UNIT IS THE TOURNAMENT, not the draw (owner, 2026-09-13). One row for
 * the US Open rather than two, and the ATP/WTA split happens inside, on the
 * chips the screen already has.
 *
 * It also makes the test trivial and total: a schedule row ALWAYS carries a
 * tournament_id, where draw_id is null for qualifying and doubles because we
 * hold no bracket for either. Matching on the draw needed the events behind
 * the chosen draws as a second set, and deriving that set from the day's rows
 * is what hid Guadalajara's and SP Open's qualifying on 12 September. There is
 * nothing to derive now.
 */
export function rowInTournaments(row, tournamentIds) {
  if (!tournamentIds) return true
  return tournamentIds.has(row.tournament_id)
}

/* Same membership? A Set is compared by reference, so the store needs this to
 * avoid re-publishing an equal selection and re-filtering on every tap. */
export function sameDrawSet(a, b) {
  if (a === b) return true
  if (!a || !b || a.size !== b.size) return false
  for (const v of a) if (!b.has(v)) return false
  return true
}

/* THE LIVE DRAWS, AS TOURNAMENTS. Two draws of a combined event are one
 * entry: the name, the id the schedule rows carry, and the tours present so
 * the row can show both badges. Men first, so a pair never swaps sides.
 *
 * A draw with no tournament_id is dropped rather than listed: no schedule row
 * could ever match it, so offering it would be offering a filter that empties
 * the screen.
 */
export function tournamentsOf(draws) {
  const by = new Map()
  for (const d of draws || []) {
    if (d?.tournament_id == null) continue
    const cur = by.get(d.tournament_id)
    if (cur) {
      if (!cur.genders.includes(d.gender)) cur.genders.push(d.gender)
    } else {
      by.set(d.tournament_id, { id: d.tournament_id, name: d.name, genders: [d.gender] })
    }
  }
  for (const t of by.values()) t.genders.sort((a, b) => (a === 'M' ? 0 : 1) - (b === 'M' ? 0 : 1))
  return [...by.values()]
}
