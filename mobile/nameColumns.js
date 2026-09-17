/* WHERE THE VERB GOES on a card of "A def. B" rows (owner, 2026-09-17).
 *
 * One left-column width L serves the whole card: every left name is
 * right-aligned into L, the verb sits after it on one x, and each right
 * name has what its own row leaves after its own score. Two rules that
 * pull against each other:
 *
 *   1. no name below a readable floor (MIN_SCALE of its size) if any L can
 *      manage it — a name that cannot be read is not a name;
 *   2. as few shrunken names as possible, shrunk as little as possible.
 *
 * The cost of an L is piecewise-linear in L with breakpoints at each row's
 * left need and at each row's room-less-right-need, so evaluating the
 * candidates at those breakpoints (and the midpoints between them) finds
 * the optimum exactly. A row that no L can satisfy — two long names beside
 * a five-set score — still pays for how far under the floor it is, so L
 * settles where the damage is least.
 *
 * rows: [{ a, b, room }] — a, b the two names' widths at full size; room
 * the width the row has for a + b together (after flags, verb, score, gaps). */
export const MIN_SCALE = 10 / 13          // 10pt of 13: the floor a name may shrink to
const FLOOR_PENALTY = 1000                // per unit of scale below the floor — dominates
const SHRINK_PENALTY = 100                // per unit of scale shrunk, above the floor
const COUNT_PENALTY = 12                  // per name shrunk at all — "the number of"

export function cardCost(L, rows, minScale = MIN_SCALE) {
  let cost = 0
  for (const { a, b, room } of rows) {
    const fl = a > 0 ? Math.min(1, L / a) : 1
    const fr = b > 0 ? Math.min(1, Math.max(0, room - L) / b) : 1
    for (const f of [fl, fr]) {
      if (f < minScale) cost += FLOOR_PENALTY * (minScale - f) + SHRINK_PENALTY * (1 - f) + COUNT_PENALTY
      else if (f < 1) cost += SHRINK_PENALTY * (1 - f) + COUNT_PENALTY
    }
  }
  return cost
}

export function bestLeftColumn(rows, minScale = MIN_SCALE) {
  const live = (rows || []).filter(r => r && r.a >= 0 && r.b >= 0 && r.room > 0)
  if (!live.length) return 0
  const maxA = Math.max(...live.map(r => r.a))
  const points = new Set([0, maxA])
  for (const r of live) {
    points.add(Math.min(maxA, Math.max(0, r.a)))
    points.add(Math.min(maxA, Math.max(0, r.room - r.b)))
    points.add(Math.min(maxA, Math.max(0, r.a * minScale)))
    points.add(Math.min(maxA, Math.max(0, r.room - r.b * minScale)))
  }
  const sorted = [...points].sort((x, y) => x - y)
  const candidates = [...sorted]
  for (let i = 1; i < sorted.length; i++) candidates.push((sorted[i - 1] + sorted[i]) / 2)
  let best = maxA, bestCost = Infinity
  for (const L of candidates) {
    const c = cardCost(L, live, minScale)
    // Ties go to the wider column: left names whole, and the verb further
    // from the flags on the left.
    if (c < bestCost - 1e-9 || (Math.abs(c - bestCost) <= 1e-9 && L > best)) { best = L; bestCost = c }
  }
  return Math.ceil(best)
}
