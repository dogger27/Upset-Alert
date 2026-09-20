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
/* THE SAME DRAWS, GROUPED, for a screen that has to RENDER both of them
 * rather than name the event once.
 *
 * tournamentsOf() answers "which events are there" and throws the draws away,
 * which is right for a filter and useless to the dashboard: a combined event's
 * card carries a tier stamp, a deadline and a standing PER TOUR, so the card
 * needs the draws themselves, together, in one group.
 *
 * Two deliberate differences from tournamentsOf:
 *
 *   - A draw with NO tournament_id is its own group, not dropped. There it
 *     would be offering a filter that empties the screen; here it would be
 *     hiding a card, and a draw the dashboard cannot show is worse than one it
 *     shows alone.
 *   - Group order follows the input, so the caller's sort survives. The
 *     dashboard's sections are ordered, and a group takes the position of its
 *     first draw.
 *
 * Men first inside each group, matching tournamentsOf, so a pair never swaps
 * sides between screens.
 */
export function drawsByTournament(draws) {
  const groups = []
  const by = new Map()
  for (const d of draws || []) {
    if (!d) continue
    const key = d.tournament_id
    if (key == null) { groups.push([d]); continue }
    const cur = by.get(key)
    if (cur) cur.push(d)
    else { const g = [d]; by.set(key, g); groups.push(g) }
  }
  for (const g of groups) g.sort((a, b) => (a.gender === 'M' ? 0 : 1) - (b.gender === 'M' ? 0 : 1))
  return groups
}

export function tournamentsOf(draws) {
  const by = new Map()
  for (const d of draws || []) {
    if (d?.tournament_id == null) continue
    const cur = by.get(d.tournament_id)
    if (cur) {
      if (!cur.genders.includes(d.gender)) cur.genders.push(d.gender)
    } else {
      by.set(d.tournament_id, {
        id: d.tournament_id,
        name: d.name,
        // The EVENT's short name, for a control that has to name it in a
        // pill — the server always sends one (TournamentOut). `name` is
        // still here for the places with room, and for a spoken label.
        short: d.tournament_short_name || d.name,
        genders: [d.gender],
      })
    }
  }
  for (const t of by.values()) t.genders.sort((a, b) => (a === 'M' ? 0 : 1) - (b === 'M' ? 0 : 1))
  return [...by.values()]
}
