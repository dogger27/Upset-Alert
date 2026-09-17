/* A SWIPE IS NOT A TAP. The schedule's swipe-to-change-day is an RNGH pan
 * over a column of Pressables, and on the phone the finger's release at the
 * end of a swipe still reached the Pressable under it as a press — the day
 * changed AND the match history opened (owner, 2026-09-17). The pan marks
 * the window: from the moment it starts until a beat after it settles, every
 * tap handler on the page declines. Plain JS, reached from the pan's
 * worklets by scheduleOnRN, read synchronously by the handlers. */
let until = 0
const SETTLE_MS = 250

export function beginSwipe() { until = Infinity }
export function endSwipe() { until = Date.now() + SETTLE_MS }
export function swiping(now = Date.now()) { return now < until }
/* Wrap a tap handler so it is a no-op during the window. */
export const unlessSwiping = fn => (...args) => { if (swiping()) return undefined; return fn?.(...args) }
