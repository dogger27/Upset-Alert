/* How tightly the day strip packs its chips.
 *
 * The type never shrinks. What gives is the air: the gap between chips, the
 * padding inside them and their minimum width, stepped down level by level
 * until every day fits the room — and only when the TIGHTEST level still
 * does not fit does the strip scroll (owner, 2026-09-17). The widths are
 * measured from font metrics (measure.js) before layout, so the level is
 * chosen once, arithmetically, with no trial passes on screen.
 *
 * `widths` are the chips' text widths at their own size; `active` is the
 * index of the chosen chip, which is a size up and carries its own padding
 * and minimum. `room` is the width the row may occupy. */
/* A chip is never narrower than a two-glyph label needs (owner, 2026-09-17:
   "the minimum width of the day spots is too narrow"): the tight level's
   floor was 0, so a "7" stood on a chip as wide as the digit, cramped beside
   "Q5". The floors rise a step at every level; the strip scrolls a little
   sooner, which is the trade the owner asked for. */
export const LEVELS = [
  { gap: 6, pad: 8, min: 38, padOn: 10, minOn: 44 },   // roomy — a 250's week
  { gap: 4, pad: 6, min: 34, padOn: 8,  minOn: 40 },
  { gap: 3, pad: 4, min: 30, padOn: 6,  minOn: 36 },
  { gap: 2, pad: 3, min: 26, padOn: 4,  minOn: 32 },   // tight — before scrolling
]

// Measurement is not layout: a couple of points of slack, so a strip that
// "just fits" on paper does not come out a hair too wide and scroll by 2pt.
const SLACK = 2

export function widthAt(level, textWidth, on) {
  return on
    ? Math.max(level.minOn, textWidth + 2 * level.padOn)
    : Math.max(level.min, textWidth + 2 * level.pad)
}

export function totalAt(level, widths, active) {
  let total = 0
  for (let i = 0; i < widths.length; i++) total += widthAt(level, widths[i], i === active)
  return total + Math.max(0, widths.length - 1) * level.gap
}

export function pickLevel(widths, active, room, levels = LEVELS) {
  for (let i = 0; i < levels.length; i++) {
    const total = totalAt(levels[i], widths, active)
    if (total + SLACK <= room) return { index: i, level: levels[i], total, fits: true }
  }
  const last = levels[levels.length - 1]
  return { index: levels.length - 1, level: last, total: totalAt(last, widths, active), fits: false }
}
