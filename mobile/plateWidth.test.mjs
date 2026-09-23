/* node plateWidth.test.mjs — the answer's box holds its size.

   "The box around the time needs to stay the same dimensions no matter what
   the value inside says! Make [it] big enough to hold the largest dimensions
   of data and keep it that size as the value changes" (owner, 2026-09-23).

   Two halves, and the first is the one that is easy to miss: the display face
   is NOT tabular by default, so "2h 26m" is wider than "5h 41m" — a box sized
   to its ceiling would still have been too small for a value below it. The
   plate sets fontVariant tabular-nums and reserves the width of the widest
   string the question can show.
*/
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { textWidth } from './measure.js'

const SRC = readFileSync(new URL('./finalGuess.jsx', import.meta.url), 'utf8')
const DISPLAY = 'SairaCondensed_700Bold'
const SIZE = 30

/* ── why tabular figures are not optional ─────────────────────────────── */

const proportional = ['2h 26m', '5h 41m', '1h 46m', '3h 47m']
  .map(t => textWidth(t, DISPLAY, SIZE))
assert.ok(Math.max(...proportional) - Math.min(...proportional) > 3,
  'this face is proportional, so the test below has something to guard')

for (const style of ['plateValue', 'plateSub']) {
  const at = SRC.indexOf(`  ${style}: {`)
  assert.ok(at > 0, `${style} is gone`)
  const decl = SRC.slice(at, SRC.indexOf('},', at))
  assert.match(decl, /fontVariant: \['tabular-nums'\]/,
    `${style} must be tabular, or the box changes width with the digits`)
}

/* ── the reserve is the widest string THIS question can show ──────────── */

// Every duration a best-of-three can hold, under the longest ceiling we have
// measured (5h 41m at the Australian Open, a best-of-five).
const fmt = (m) => {
  const h = Math.floor(m / 60), mm = m % 60
  return h ? `${h}h ${String(mm).padStart(2, '0')}m` : `${mm}m`
}
const tab = (t) => t.replace(/\d/g, '0')     // tabular: every digit one advance
for (const ceiling of [146, 172, 227, 255, 341]) {
  const reserved = textWidth(tab(fmt(ceiling)), DISPLAY, SIZE)
  for (let v = 0; v <= ceiling; v += 7) {
    assert.ok(textWidth(tab(fmt(v)), DISPLAY, SIZE) <= reserved + 0.01,
      `a duration of ${v} is wider than the reserve for ${ceiling}`)
  }
}

// And for the aces plate, whose value is bare digits.
for (const ceiling of [9, 28, 44, 120]) {
  const reserved = textWidth(tab(String(ceiling)), DISPLAY, SIZE)
  for (let v = 0; v <= ceiling; v++) {
    assert.ok(textWidth(tab(String(v)), DISPLAY, SIZE) <= reserved + 0.01,
      `${v} aces is wider than the reserve for ${ceiling}`)
  }
}

/* ── and the plate asks for one ───────────────────────────────────────── */

assert.match(SRC, /function Plate\(\{ value, sub, reserve \}\)/,
  'Plate no longer takes a reserve')
assert.match(SRC, /reserve=\{\[fmtMinutes\(durMax\), `\$\{durMax\} min`\]\}/,
  'the duration plate must reserve its own ceiling, not a global worst case')
assert.match(SRC, /reserve=\{String\(acesMax\)\}/,
  'the aces plate must reserve its own ceiling')

console.log('ok — plateWidth')
