/*
 * Measure text WITHOUT drawing it.
 *
 * React Native cannot say whether a string fits until it has laid it out, and
 * the two platform features that look like they solve this do not:
 *   - adjustsFontSizeToFit on iOS shrinks to its minimum whenever the box has
 *     any slack at all — the seed badge became a 5pt speck in a 30pt box;
 *   - onTextLayout's lines[].text does not reliably reveal truncation, so the
 *     name ladder never stepped and "Nishesh B…" shipped.
 *
 * So the app measures from the font's own advance widths, generated from the
 * TTFs by tools/gen-font-metrics.mjs. Deterministic, identical on iOS and in
 * the web harness — which means what is rendered on Jupiter is finally what
 * renders on the phone. Kerning is ignored and covered by the caller's margin.
 */
import METRICS from './fontMetrics.js'
import { FONT_SCALE } from './fontScale.js'

const FALLBACK = 'Archivo_500Medium'
const maps = {}

function table(family) {
  const m = METRICS[family] ?? METRICS[FALLBACK]
  if (!maps[family]) {
    const map = new Map()
    let i = 0
    for (const ch of m.chars) { map.set(ch, m.adv[i++]) }
    maps[family] = { map, upm: m.upm, avg: m.avg }
  }
  return maps[family]
}

/** Width in points of `text` set in `family` at `fontSize`, AS THE READER
    SEES IT — the device text-size setting is applied, because that is the
    size the platform will actually draw. */
export function textWidth(text, family, fontSize) {
  const t = table(family)
  let units = 0
  for (const ch of String(text ?? '')) {
    const w = t.map.get(ch)
    units += w == null || w < 0 ? t.avg : w
  }
  return (units / t.upm) * fontSize * FONT_SCALE
}


/* THE ONE TEXT SIZE AT WHICH A WHOLE ROW OF PILLS FITS THE WIDTH IT HAS.
 *
 * The Schedule's tournament filter used to wrap onto a second line, which cost
 * a row of the screen and moved the list down as the week changed. The owner
 * asked for one line instead (2026-09-21), so the pills share a size chosen to
 * make that true — ONE size for all of them, not each shrunk to its own box: a
 * row where "Korea" is set larger than "Hangzhou" reads as a mistake, and the
 * pills are a set of equals.
 *
 * Each pill is as wide as the WIDER OF ITS TWO LINES — the tier number above
 * and the name below — so a short name under a long number ("SP" under
 * "1000") is measured by the number.
 *
 * Solved rather than searched. Text width is linear in font size but the
 * padding and borders are not, so the answer is
 *
 *     size = (available - fixed chrome) / (total text width at size 1)
 *
 * which is exact in one step. Never ABOVE the caller's size — a row with room
 * to spare keeps its intended size rather than inflating to fill the space,
 * which is the mistake adjustsFontSizeToFit makes in the other direction.
 *
 * `chrome` is one pill's horizontal padding AND border, both sides, in points.
 *
 * SLACK, AND WHY IT IS NOT OPTIONAL. The first version solved for the row to
 * come out EXACTLY the available width, and every name truncated (owner,
 * 2026-09-21: "What a FAIL!"). Two points of arithmetic were missing. The
 * tables at the top of this file carry advance widths and no KERNING, which
 * the header admits and leaves "covered by the caller's margin" — there was no
 * margin to cover it. And a Text that runs out of room reserves space for the
 * ellipsis it is about to draw, so being a hair too wide costs a hair PLUS an
 * ellipsis. An exact fit is therefore always a slight overflow, flex shrinks
 * every box to absorb it, and the reader sees "Cheng…". FitText leaves a point
 * for the same reason; a row of pills needs one per pill.
 */
export function fitPillSize(pills, { avail, family, size, tierRatio = 0.8,
                                     chrome = 0, gap = 0, min = 7,
                                     slack = 1 } = {}) {
  const n = pills?.length || 0
  if (!n || !avail || !(size > 0)) return size
  const fixed = n * (chrome + slack) + gap * (n - 1)
  const unit = pills.reduce((sum, p) => sum + Math.max(
    textWidth(p?.name, family, 1),
    textWidth(p?.tier, family, tierRatio),
  ), 0)
  if (unit <= 0) return size
  return Math.max(min, Math.min(size, (avail - fixed) / unit))
}

/* THE WIDTH OF TEXT AS DRAWN at `drawnSize` — a font size that ALREADY
   includes the reader's text scale (allowFontScaling off, fontSize set to
   base × FONT_SCALE). textWidth above applies FONT_SCALE itself, so handing
   it a drawn size scaled twice and overstated every width by that factor
   (2026-09-24: names shrunk more than needed, tab margins too wide). */
export function drawnWidth(text, family, drawnSize) {
  return textWidth(text, family, drawnSize / FONT_SCALE)
}
