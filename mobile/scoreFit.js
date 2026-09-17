/* THE SCORE SHRINKS ONLY AS MUCH AS IT MUST (owner, 2026-09-17).
 *
 * The block used to give way by column count alone — 0.76 at five columns,
 * 0.88 at four — whatever the room: a finished five-setter in the mid view
 * came out at 0.61 of full size with a third of the row to spare. Now the
 * card measures its width and the cells shrink only when the row cannot
 * hold them beside a name at its floor. Before the first layout (width 0)
 * the column rule stands in, so the first paint is safe.
 *
 * Every width here is a POINT ESTIMATE of the card's own styles at scale 1
 * (scorecard.jsx): the seed box and its gap, the flag slot, the win/loss
 * mark, the serve slot, a set box (16, or 26 with a two-digit game count),
 * a tiebreak superscript, the running point. NAME_FLOOR is a shortened
 * name with the pick mark — "C. Alcaraz 🤞" — at body size; below it the
 * ladder's last rung ("Zver…") is what the reader gets. */
const GAP = 8            // s.line's gap between items
const SEED = 34          // the seed box
const FLAG = 22          // one flag slot (leading(17))
const FLAG_MORE = 4      // each further slot's gap (leading(3))
const MARK = 18          // the ✓ / ✕ column (leading(14))
const SERVE = 16         // the serve-mark slot
const SET_GAP = 6        // s.sets' gap
const BOX = 16
const BOX_WIDE = 26
const SUP = 6            // a tiebreak superscript
const POINT = 26
const NAME_FLOOR = 98
const FLOOR = 0.6        // never below this fraction of the asked scale

export function columnScale(cols) {
  return cols >= 5 ? 0.76 : cols === 4 ? 0.88 : 1
}

/* The width the set cells want at `scale`, superscripts and gaps included. */
export function setsWidth({ cols, point, twoDigit, tiebreaks, scale = 1 }) {
  const sets = cols - (point ? 1 : 0)
  const boxes = sets * (twoDigit ? BOX_WIDE : BOX) + tiebreaks * SUP + (point ? POINT : 0)
  return (boxes + Math.max(0, cols - 1) * SET_GAP) * scale
}

/* The fraction of full size the cells are drawn at: `scale` itself when the
   row holds them, less only by what the room lacks. */
export function setsScale({ width, scale = 1, cols, point, twoDigit, tiebreaks, flagSlots = 1, badges = true, live = false }) {
  if (!width) return columnScale(cols) * scale
  const need = setsWidth({ cols, point, twoDigit, tiebreaks, scale })
  if (!need) return scale
  const fixed = (badges ? SEED + GAP : 0)
    + FLAG + Math.max(0, flagSlots - 1) * (FLAG + FLAG_MORE) + GAP
    + MARK + GAP
    + (live ? SERVE + GAP : 0)
  const room = width - fixed - NAME_FLOOR * scale
  if (room >= need) return scale
  return Math.max(FLOOR * scale, (room / need) * scale)
}
