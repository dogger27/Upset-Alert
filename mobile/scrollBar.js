/* THE BAR THAT SAYS THERE IS MORE (owner, 2026-09-22).
 *
 * "It's not clear how to go to the next page or that more data is below" —
 * the tiebreak sheet's Back/Next row sits under the reference block, and on a
 * long question it falls past the fold with nothing on screen to admit it.
 *
 * iOS has no always-on scroll indicator to switch on: the native one is a
 * flash on touch and fades, and `persistentScrollbar` is Android's alone. So
 * the pane draws its own, and this module is the arithmetic behind it — pure,
 * so the geometry is provable without a phone.
 */

/* Small enough not to look like a page of content, big enough to grab and to
   see against a track. A thumb that shrinks with the content would vanish on
   a long page, which is the case that needed the bar in the first place. */
export const MIN_THUMB = 28

/* The thumb's height, or 0 when there is nothing to scroll — and 0 is the
   signal to draw no bar at all. The +1 slack is for the layout rounding that
   makes a pane report a content height a fraction taller than itself. */
export function thumbSize({ viewH, contentH, minThumb = MIN_THUMB }) {
  if (!(viewH > 0) || !(contentH > viewH + 1)) return 0
  const proportional = (viewH * viewH) / contentH
  return Math.round(Math.min(viewH, Math.max(minThumb, proportional)))
}

/* The two ends of the mapping: `max` is how far the CONTENT can scroll, and
   `travel` how far the THUMB may slide. Held apart from the thumb's height
   because a floored thumb no longer divides the track proportionally — the
   travel has to be measured from the size actually drawn.

   `max` never returns 0: it is a divisor on the other side, and a pane that
   cannot scroll draws no thumb to place anyway. */
export function barRange({ viewH, contentH, thumb }) {
  return {
    max: Math.max(1, contentH - viewH),
    travel: Math.max(0, viewH - thumb),
  }
}
