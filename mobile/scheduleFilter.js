/*
 * Which draws the Schedule screen is showing.
 *
 * A day's sheet can carry four tournaments and a hundred rows; a reader with
 * picks in one of them wants that one. So the Schedule tab asks first, and the
 * screen filters to the answer.
 *
 * An external store rather than context, for the same reason as currentDraw
 * and lastLeague: the WRITER is the tab layout, which sits above every screen
 * that reads it.
 *
 * SESSION-SCOPED, deliberately unlike lastLeague. A league is the same league
 * next season; a set of draw ids is a week old by Monday, and a persisted one
 * would silently empty a schedule the reader had not asked to empty. `null`
 * means every draw, which is also the state after a restart.
 *
 * NEVER EMPTY. The owner's rule — one or many, not none: a filter that hides
 * everything is indistinguishable from a broken screen, so the last selected
 * draw cannot be unselected.
 */
import { useSyncExternalStore } from 'react'
import { sameDrawSet } from './scheduleRows'

let ids = null            // Set of draw ids, or null = every draw
const subscribers = new Set()

function publish() {
  subscribers.forEach(fn => fn())
}

/** Replace the selection. An empty or null set means "every draw". */
export function setScheduleDraws(next) {
  const clean = next && next.size ? new Set(next) : null
  // Same membership, same object identity for the reader: a Set is compared by
  // reference, so re-publishing an equal one would re-filter on every tap.
  if (sameDrawSet(clean, ids)) return
  ids = clean
  publish()
}

/** Drop ids that are no longer live — a week later they name nothing. */
export function pruneScheduleDraws(liveIds) {
  if (!ids) return
  const keep = new Set([...ids].filter(id => liveIds.includes(id)))
  setScheduleDraws(keep.size ? keep : null)
}

export function useScheduleDraws() {
  return useSyncExternalStore(
    fn => { subscribers.add(fn); return () => subscribers.delete(fn) },
    () => ids,
    () => ids,
  )
}
