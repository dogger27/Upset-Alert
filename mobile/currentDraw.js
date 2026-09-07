/*
 * Which draw the Draw tab points at.
 *
 * A tab needs a static href, and "the draw" is not static — there are two at
 * every slam and a dozen across a season. So the draw screen reports the one
 * it is showing, and the tab follows: tap Draw while reading the women's US
 * Open and you stay in the women's US Open.
 *
 * An external store rather than context, because the READER is the tab layout,
 * which sits ABOVE every screen that could set this — a provider low enough to
 * be written by the draw screen would be too low to be read by the layout.
 *
 * Session-scoped on purpose. On a cold start there is no answer yet and the
 * layout falls back to the first draw worth opening; persisting a stale id
 * would only reopen a tournament that finished months ago.
 */
import { useSyncExternalStore } from 'react'

let current = null
const subscribers = new Set()

/** Called by the draw screen for the draw it is showing. */
export function setCurrentDraw(id) {
  const next = id == null ? null : Number(id)
  if (next === current) return          // no needless re-render of every tab
  current = next
  subscribers.forEach(fn => fn())
}

export function useCurrentDraw() {
  return useSyncExternalStore(
    fn => { subscribers.add(fn); return () => subscribers.delete(fn) },
    () => current,
    () => current,
  )
}
