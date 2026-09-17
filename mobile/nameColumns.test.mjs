/* node nameColumns.test.mjs */
import assert from 'node:assert/strict'
import { MIN_SCALE, bestLeftColumn, cardCost } from './nameColumns.js'

const scales = (L, rows) => rows.map(({ a, b, room }) => [Math.min(1, L / a), Math.min(1, Math.max(0, room - L) / b)])

// Plenty of room: the column is the widest left name and nothing shrinks.
let rows = [{ a: 90, b: 60, room: 220 }, { a: 50, b: 80, room: 220 }, { a: 70, b: 40, room: 220 }]
assert.equal(bestLeftColumn(rows), 90)
assert.ok(scales(90, rows).flat().every(f => f === 1))

// The owner's card: a long left name on one row, a five-set score on another.
// The widest-left rule (L = 90) puts the five-setter's right name under the
// floor; the optimum gives up a little on Rinderknech instead.
rows = [
  { a: 90, b: 85, room: 165 },   // Rinderknech def. Shimabukuro, four sets
  { a: 60, b: 40, room: 165 },   // Lehečka def. Busta, four sets
  { a: 75, b: 75, room: 215 },   // Rakhimova def. Krejčíková, two sets
  { a: 55, b: 70, room: 140 },   // Prižmić def. Kukushkin, FIVE sets
]
const L = bestLeftColumn(rows)
assert.ok(L < 90, `L=${L}`)
for (const [fl, fr] of scales(L, rows)) { assert.ok(fl >= MIN_SCALE - 1e-9, fl); assert.ok(fr >= MIN_SCALE - 1e-9, fr) }
assert.ok(cardCost(L, rows) < cardCost(90, rows))
// And no more names shrink than must: at the optimum only Rinderknech gives.
const shrunk = scales(L, rows).flat().filter(f => f < 1 - 1e-9).length
assert.ok(shrunk <= 2, `shrunk=${shrunk}`)

// A row nobody can save (two long names, a five-set score) does not wreck
// the others: the column still keeps every other name whole.
rows = [{ a: 100, b: 100, room: 150 }, { a: 60, b: 60, room: 220 }, { a: 70, b: 50, room: 220 }]
const L2 = bestLeftColumn(rows)
const s2 = scales(L2, rows)
assert.ok(s2[1].every(f => f === 1) && s2[2].every(f => f === 1), JSON.stringify(s2))

// Degenerate input.
assert.equal(bestLeftColumn([]), 0)
assert.equal(bestLeftColumn([{ a: 0, b: 0, room: 100 }]), 0)
console.log('ok — nameColumns')
