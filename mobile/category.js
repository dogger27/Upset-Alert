/* "GS" / "1000" / "500" / "250" — the site's categoryShort, verbatim, so the
   app names a tier the same way the site's draw nav and history page do. */
export function categoryShort(cat) {
  if (!cat) return ''
  if (cat.includes('Slam') || cat.includes('slam')) return 'GS'
  if (cat.includes('1000')) return '1000'
  if (cat.includes('500')) return '500'
  return '250'
}
export const tourLabel = (t) => `${t?.gender === 'M' ? 'ATP' : 'WTA'}${categoryShort(t?.category) ? ' ' + categoryShort(t?.category) : ''}`

/* WHICH TOUR AN EVENT BELONGS TO — 'ATP', 'WTA', or null when it is both.
 *
 * Takes the `genders` array tournamentsOf() puts on an event, so a combined
 * week (['M','F']) answers null. That is not a failure to classify: a combined
 * week genuinely belongs to neither tour, and the app already has a rule for
 * the case. theme.js's TOUR.X, for mixed doubles, states it — "a blend of blue
 * and pink is a gradient decision on a 10pt pill, and there is no such token
 * on the site to borrow" — so a caller colouring by tour must hold a NEUTRAL
 * for null rather than invent a blend.
 */
export function eventTour(genders) {
  const seen = [...new Set((genders || []).filter(Boolean))]
  if (seen.length !== 1) return null
  return seen[0] === 'F' ? 'WTA' : 'ATP'
}
