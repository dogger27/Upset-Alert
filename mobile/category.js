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


/* THE TIER AN EVENT PLAYS AT, as one short string: "500", "1000", "GS".
 *
 * A combined week whose halves differ keeps both, joined — Beijing is a WTA
 * 1000 beside an ATP 500, and "1000" alone would be a claim about the men's
 * draw that is not true. Halves at the same tier say it once, which is the
 * common case (Chengdu and Hangzhou are both ATP 250).
 *
 * Empty string, never a placeholder, when nothing is known: a pill draws the
 * line only if there is something to put on it, and a stray dash above a
 * tournament name reads as a missing number rather than an absent one.
 */
/* A SLAM IS "2000" HERE (owner, 2026-09-22), not "GS". This pill sits in a row
 * of 250s, 500s and 1000s, and those are ranking points — so the odd one out
 * was the one printing a category where its neighbours printed a number. Only
 * this word changes: categoryShort still answers "GS" everywhere a tier is a
 * LABEL rather than one of a series (the tier badges, the headings).
 */
const SLAM_POINTS = '2000'

export function tierWord(categories) {
  const seen = []
  for (const c of categories || []) {
    const short = categoryShort(c)
    const word = short === 'GS' ? SLAM_POINTS : short
    if (word && !seen.includes(word)) seen.push(word)
  }
  return seen.join('/')
}
