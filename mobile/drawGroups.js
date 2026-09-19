/*
 * THE DRAWS SHEET, GROUPED BY STATUS (owner, 2026-09-19).
 *
 * The tab bar's chooser lists every draw worth opening, and that list answers
 * two different questions at once: which draws still take picks, and which are
 * being played. Flat, four rows read as one undifferentiated list and the
 * deadline — the only one of the two a reader can miss — was invisible.
 *
 * The two words and their order are the DASHBOARD's, not new ones: its home
 * screen has shown "Open" then "Active" since it was built, so grouping here
 * costs the reader no second vocabulary for the same fact.
 *
 * `sectionOf` comes from useChoosableTournaments, which works the cohort out
 * over EVERY draw before filtering. Do not recompute it from the list passed
 * in here: clustering a filtered list moves the boundaries, which is how
 * "Last Week" starts stealing from "Active" (choosableTournaments.js).
 */

export const STATUS_GROUPS = [
  { key: 'open', title: 'Open' },
  { key: 'active', title: 'Active' },
]

/* [{ key, title, draws }], in the dashboard's order, empty groups dropped.
 *
 * Anything whose section is neither lands in a trailing group rather than
 * being dropped. Today the sheet is fed a list already filtered to these two,
 * so that group is always empty — but a draw must never vanish from a chooser
 * because its status turned out to be a third thing, and a heading nobody
 * planned is a far smaller failure than a draw the reader cannot reach. */
export function groupDrawsByStatus(draws, sectionOf) {
  const rows = draws || []
  const at = typeof sectionOf === 'function' ? sectionOf : () => null
  const out = []
  for (const g of STATUS_GROUPS) {
    const mine = rows.filter(d => at(d) === g.key)
    if (mine.length) out.push({ ...g, draws: mine })
  }
  const known = new Set(STATUS_GROUPS.map(g => g.key))
  const rest = rows.filter(d => !known.has(at(d)))
  if (rest.length) out.push({ key: 'other', title: 'Other', draws: rest })
  return out
}

/* ONE GROUP IS NO GROUPING. A heading over the whole list says nothing the
   list does not already say, and in a sheet this short it costs a row of
   height to say it — so the caller draws headings only when there are two. */
export const showGroupHeadings = (groups) => (groups || []).length > 1
