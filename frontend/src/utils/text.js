/* Measuring text without laying it out.
 *
 * Fitting a name to a column by counting characters is only ever an estimate —
 * "WWW" and "iii" are the same length and nothing like the same width — and the
 * alternative, rendering it and reading offsetWidth, forces a layout and then
 * has to re-render once the answer comes back. A canvas answers the same
 * question with no DOM involved and no reflow.
 *
 * Deliberately NOT shared with CombinedView's own copy: that one measures the
 * uppercased string because .cv-name uppercases what it draws, which is a fact
 * about that component rather than about measuring text.
 */

let _ctx
const _widths = new Map()

/* THE DOCUMENT IS READ ONCE, NOT PER MEASUREMENT.
 *
 * getComputedStyle resolves style against the live document, so calling it
 * inside the measuring function billed every single measurement — cache hits
 * included — for a value that only moves when the page's font or the reader's
 * font size does. The name ladder measures several candidate strings per
 * player, and a draw holds up to 128 of them.
 *
 * Invalidated by the two things that actually move it: a web font finishing
 * loading, which changes the family's metrics, and a resize, which is when a
 * browser zoom or text-size change lands.
 */
let _family = null
let _rootPx = null

function invalidateFontCache() {
  _family = null
  _rootPx = null
  _widths.clear()
}

if (typeof window !== 'undefined') {
  window.addEventListener('resize', invalidateFontCache)
  // Optional-chained: not every browser exposes document.fonts, and its
  // absence only means first-paint measurements stand, exactly as before.
  document.fonts?.ready?.then?.(invalidateFontCache)
}

function bodyFamily() {
  if (_family === null) {
    _family = getComputedStyle(document.body).fontFamily || 'sans-serif'
  }
  return _family
}

/** Width in px of `text` at `px`/`weight`, in the body's font. */
export function textWidth(text, px, weight = 400) {
  if (!text || !px) return 0
  if (typeof document === 'undefined') return text.length * 0.55 * px
  if (_ctx === undefined) {
    try { _ctx = document.createElement('canvas').getContext('2d') }
    catch { _ctx = null }
  }
  if (!_ctx) return text.length * 0.55 * px
  const spec = `${weight} ${px}px ${bodyFamily()}`
  /* KEYED BY THE FULL SPEC, AND NOT CLEARED WHEN THE SPEC CHANGES.
   *
   * The old cache keyed on the text alone and wiped itself whenever the spec
   * differed from the last call — thrifty-sounding until you look at the loop
   * it serves. MatchScoreCard measures a seed at (px * 0.85, 700) and the name
   * at (px, 600) for the SAME row, so the spec alternated twice per row and
   * the map was emptied twice per row: it could never serve a hit inside the
   * row it existed for, and cost a Map allocation on top of the measurement it
   * was meant to save. A compound key lets both specs live at once.
   */
  const key = `${spec} ${text}`
  let w = _widths.get(key)
  if (w === undefined) {
    _ctx.font = spec
    w = _ctx.measureText(text).width
    _widths.set(key, w)
  }
  return w
}

/** Root font size in px, for turning a rem-based CSS size into something
 *  measurable. Read rather than assumed: the user's browser setting moves it.
 *  Cached alongside the family — MatchScoreCard asks four times per row. */
export function rootFontPx() {
  if (typeof document === 'undefined') return 16
  if (_rootPx === null) {
    _rootPx = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16
  }
  return _rootPx
}
