/* node stripLayout.test.mjs */
import assert from 'node:assert/strict'
import { LEVELS, pickLevel, totalAt, widthAt } from './stripLayout.js'

const digits = n => Array.from({ length: n }, () => 9)     // a one-digit chip's text, ~9pt at 13pt

// A chip is at least its minimum wide, else its text plus padding.
assert.equal(widthAt(LEVELS[0], 9, false), 38)
assert.equal(widthAt(LEVELS[0], 40, false), 56)
assert.equal(widthAt(LEVELS[0], 9, true), 44)
assert.equal(widthAt(LEVELS[3], 9, false), 26)             // a floor even at the tightest (owner, 2026-09-17)

// Six days fit at the roomiest level in a 250's strip.
let r = pickLevel(digits(6), 2, 300)
assert.equal(r.index, 0); assert.equal(r.fits, true)
assert.equal(r.total, 5 * 38 + 44 + 5 * 6)

// Nine days: the roomy level is 396 wide, so the strip steps down one.
r = pickLevel(digits(9), 4, 348)
assert.equal(totalAt(LEVELS[0], digits(9), 4), 8 * 38 + 44 + 8 * 6)
assert.equal(r.index, 1); assert.equal(r.fits, true)

// Twelve days fit only at the tightest — and DO fit, so no scrolling.
r = pickLevel(digits(12), 5, 348)
assert.equal(r.index, 3); assert.equal(r.fits, true)

// Twenty days: with a floor under every chip the tightest is 564 wide; the strip scrolls.
r = pickLevel(digits(20), 10, 348)
assert.equal(r.index, 3); assert.equal(r.fits, false)

// Twenty days in a narrow room: even the tightest overflows; the strip scrolls.
r = pickLevel(digits(20), 10, 300)
assert.equal(r.index, 3); assert.equal(r.fits, false)
assert.ok(r.total > 300)

// The slack: a strip exactly the room's width on paper is treated as too wide.
const exact = totalAt(LEVELS[0], digits(3), 1)
assert.equal(pickLevel(digits(3), 1, exact).index, 1)
assert.equal(pickLevel(digits(3), 1, exact + 2).index, 0)

// Levels only ever get tighter, so stepping down never makes it wider.
for (let i = 1; i < LEVELS.length; i++) {
  assert.ok(totalAt(LEVELS[i], digits(12), 5) < totalAt(LEVELS[i - 1], digits(12), 5))
}
console.log('ok — stripLayout')
