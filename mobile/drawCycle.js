/*
 * "On to the next draw being played" — which one that is.
 *
 * Pure, and in its own file with no imports, because the interesting part is
 * not the button: it is the ORDER. A cycle whose order comes from whatever the
 * API happened to list means "next" points somewhere different each visit, and
 * a reader can never learn it. Fixed here: by start date, then the men's draw
 * before the women's, then by name.
 */

/** The live draws in the cycle's order. */
export function cycleOrder(live) {
  return [...(live || [])].sort((a, b) =>
    String(a.start_date).localeCompare(String(b.start_date))
    || (a.gender === 'M' ? 0 : 1) - (b.gender === 'M' ? 0 : 1)
    || String(a.name).localeCompare(String(b.name)))
}

/**
 * The draw to step to from `current`, or null for no button at all.
 *
 * Null in three cases, and each is a case where a button would be a lie:
 *   - fewer than two live draws: nowhere to go;
 *   - no current draw yet: nothing to step from;
 *   - every live draw belongs to THIS tournament, where the header's tour
 *     switch already is this control, and two buttons doing one thing is
 *     worse than one.
 *
 * A current draw that is not live — an old one opened from history — is not a
 * refusal: the cycle starts at the top of the list instead.
 */
export function nextLiveDraw(live, current) {
  const ordered = cycleOrder(live)
  if (!current || ordered.length < 2) return null
  if (!ordered.some(d => d.tournament_id !== current.tournament_id)) return null
  const i = ordered.findIndex(d => d.id === current.id)
  return ordered[i < 0 ? 0 : (i + 1) % ordered.length] ?? null
}

/**
 * THE LIST THE READER CAME FROM (owner, 2026-09-23): on a league's standings
 * the next-draw button walks the events the league page's tab was LISTING
 * when the reader tapped in — not every live draw — and is hidden when that
 * list held one event.
 *
 * `listed` is one draw id per event, in the tab's order; `here` is every id
 * of the event on screen (both halves), so the ATP and WTA standings of one
 * event count as the same stop. Returns the id to step to, or null.
 */
export function nextListedDraw(listed, here) {
  const ids = (listed || []).map(String)
  if (ids.length < 2) return null
  const mine = new Set((here || []).map(String))
  const i = ids.findIndex(x => mine.has(x))
  return ids[i < 0 ? 0 : (i + 1) % ids.length]
}
