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
