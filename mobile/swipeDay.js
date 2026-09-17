/* The schedule's swipe-to-change-day, decided on release.
 *
 * A swipe is a distance OR a flick: a slow drag past SWIPE_PX, or a quick one
 * that did not get that far but was clearly going somewhere (SWIPE_VX). The
 * sign is the finger's: moving LEFT brings the NEXT day (+1), as pages turn.
 * A drag that comes back under both thresholds is nothing at all. */
export const SWIPE_PX = 60
export const SWIPE_VX = 500

export function swipeStep(translationX, velocityX, px = SWIPE_PX, vx = SWIPE_VX) {
  'worklet'
  if (translationX <= -px || velocityX <= -vx) return 1
  if (translationX >= px || velocityX >= vx) return -1
  return 0
}
