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
let _spec = ''
const _widths = new Map()

/** Width in px of `text` at `px`/`weight`, in the body's font. */
export function textWidth(text, px, weight = 400) {
  if (!text || !px) return 0
  if (typeof document === 'undefined') return text.length * 0.55 * px
  if (_ctx === undefined) {
    try { _ctx = document.createElement('canvas').getContext('2d') }
    catch { _ctx = null }
  }
  if (!_ctx) return text.length * 0.55 * px
  const family = getComputedStyle(document.body).fontFamily || 'sans-serif'
  const spec = `${weight} ${px}px ${family}`
  // The cache is keyed by the font too, so a font change cannot serve stale
  // widths; clearing on change keeps it from growing without bound.
  if (spec !== _spec) { _spec = spec; _widths.clear() }
  let w = _widths.get(text)
  if (w === undefined) {
    _ctx.font = spec
    w = _ctx.measureText(text).width
    _widths.set(text, w)
  }
  return w
}

/** Root font size in px, for turning a rem-based CSS size into something
 *  measurable. Read rather than assumed: the user's browser setting moves it. */
export function rootFontPx() {
  if (typeof document === 'undefined') return 16
  return parseFloat(getComputedStyle(document.documentElement).fontSize) || 16
}
