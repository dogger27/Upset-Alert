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

/* The dashboard's own three sections, its words, its order, its colours — a
   reader who has seen the home screen recognises a heading before reading it.
   `upcoming` earns its place for the league page, whose Open / Active tab also
   carries next week's releases; the tab bar's chooser is fed open and active
   only, so that group is simply always empty there and dropped. */
export const STATUS_GROUPS = [
  { key: 'open', title: 'Open' },
  { key: 'active', title: 'Active' },
  { key: 'upcoming', title: 'Next week' },
]

/* AN EVENT'S OWN SECTION, where a card holds more than one draw. A combined
   tournament is one card with two halves in it and they can differ — the men's
   already under way while the women's still takes picks. The card belongs to
   the FIRST of the sections above that either half is in, because a card the
   reader can still pick in is an open card. Null when none of them is a
   section this groups by. */
export function sectionOfMany(sections) {
  const order = STATUS_GROUPS.map(g => g.key)
  let best = null
  for (const s of sections || []) {
    const i = order.indexOf(s)
    if (i >= 0 && (best === null || i < best)) best = i
  }
  return best === null ? null : order[best]
}

/* [{ key, title, draws }], in the dashboard's order, empty groups dropped.
 *
 * Anything whose section is none of them lands in a trailing group rather than
 * being dropped. Both callers pass lists already confined to these sections,
 * so that group is normally empty — but a draw must never vanish from a list
 * because its status turned out to be a fourth thing, and a heading nobody
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

/* The tone each heading wears, beside its words — the dashboard's own pair,
   plus muted for a week that has not started. Imported rather than repeated:
   two screens with two copies of this drift. */
export const GROUP_TONE = { open: 'clay', active: 'greenLit', upcoming: 'muted' }

/* ONE GROUP IS NO GROUPING. A heading over the whole list says nothing the
   list does not already say, and in a sheet this short it costs a row of
   height to say it — so the caller draws headings only when there are two. */
export const showGroupHeadings = (groups) => (groups || []).length > 1
