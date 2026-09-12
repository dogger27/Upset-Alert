/*
 * Does a schedule row belong to the draws the reader chose?
 *
 * Its own module, free of React, so it can be tested by a plain node script
 * the way scoring.js is — the store that holds the selection needs a hook and
 * therefore needs React, and a data: URL cannot resolve a bare specifier.
 */

/* DOUBLES AND QUALIFYING CARRY NO draw_id — we hold no bracket for them — so
 * matching on that alone would hide every doubles row the moment a filter was
 * set. They do carry the tournament, and choosing a draw means choosing its
 * event, so a row of the same tournament stays. `tournamentIds` is the set of
 * tournament ids behind the chosen draws.
 */
export function rowInDraws(row, drawIds, tournamentIds) {
  if (!drawIds) return true
  if (row.draw_id != null) return drawIds.has(row.draw_id)
  return !!tournamentIds && tournamentIds.has(row.tournament_id)
}

/* Same membership? A Set is compared by reference, so the store needs this to
 * avoid re-publishing an equal selection and re-filtering on every tap. */
export function sameDrawSet(a, b) {
  if (a === b) return true
  if (!a || !b || a.size !== b.size) return false
  for (const v of a) if (!b.has(v)) return false
  return true
}
