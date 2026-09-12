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
/* AND THE TOURNAMENTS BEHIND THEM, which is not the same question.
   Qualifying and doubles rows carry no draw_id, so they can only be matched by
   their event — and the mapping from draw to event has to come from the DRAW,
   which knows its tournament_id, not from whatever happens to be on court that
   day. Deriving it from the day's rows is what hid Guadalajara's and SP Open's
   qualifying on 12 September: neither draw had a single main-draw row that
   day, so neither event ever entered the set, and both events' matches
   appeared only when the US Open's women's draw was also ticked — because
   THAT row supplied the only tournament id there was (owner, 2026-09-12). */
let eventIds = null
const subscribers = new Set()

function publish() {
  subscribers.forEach(fn => fn())
}

/** Replace the selection: the draws, and the events they belong to. An empty
    or null set means "every draw". */
export function setScheduleDraws(next, events) {
  const clean = next && next.size ? new Set(next) : null
  const cleanEvents = clean && events && events.size ? new Set(events) : null
  // Same membership, same object identity for the reader: a Set is compared by
  // reference, so re-publishing an equal one would re-filter on every tap.
  if (sameDrawSet(clean, ids) && sameDrawSet(cleanEvents, eventIds)) return
  ids = clean
  eventIds = cleanEvents
  snapshot = { draws: ids, tournaments: eventIds }
  publish()
}

/** Drop ids that are no longer live — a week later they name nothing.
    `live` is the draw list, so the events are re-derived from it. */
export function pruneScheduleDraws(live) {
  if (!ids) return
  const alive = live.filter(d => ids.has(d.id))
  setScheduleDraws(alive.length ? new Set(alive.map(d => d.id)) : null,
                   new Set(alive.map(d => d.tournament_id).filter(v => v != null)))
}

/** `{ draws, tournaments }`, both null when every draw is shown. One object
    per change, so the identity is stable between publishes. */
let snapshot = { draws: null, tournaments: null }

export function useScheduleDraws() {
  return useSyncExternalStore(
    fn => { subscribers.add(fn); return () => subscribers.delete(fn) },
    () => snapshot,
    () => snapshot,
  )
}
