// node --test scoreFit.test.mjs
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { columnScale, setsScale, setsWidth } from './scoreFit.js'

test('before layout the column rule stands in', () => {
  assert.equal(setsScale({ width: 0, scale: 1, cols: 5, tiebreaks: 3 }), 0.76)
  assert.equal(setsScale({ width: 0, scale: 0.8, cols: 4, tiebreaks: 0 }), 0.88 * 0.8)
  assert.equal(setsScale({ width: 0, scale: 1, cols: 2, tiebreaks: 0 }), 1)
  assert.deepEqual([5, 4, 3].map(columnScale), [0.76, 0.88, 1])
})

test('a finished five-setter with room to spare keeps the asked scale (the mid view, owner 2026-09-17)', () => {
  // Shelton d. Alcaraz 6-7(5) 6-1 6-3 1-6 7-6(7): five sets, three tiebreaks, a 360pt card at 0.8.
  const k = setsScale({ width: 360, scale: 0.8, cols: 5, point: false, twoDigit: false, tiebreaks: 3, live: false })
  assert.equal(k, 0.8)
})

test('the same score in a narrow card shrinks, and only by what the room lacks', () => {
  const args = { scale: 1, cols: 5, point: false, twoDigit: false, tiebreaks: 3, live: false }
  const need = setsWidth(args)
  const wide = setsScale({ ...args, width: 400 })
  const tight = setsScale({ ...args, width: 300 })
  const tighter = setsScale({ ...args, width: 260 })
  assert.equal(wide, 1)
  assert.ok(tight < 1 && tight > 0.6, `tight ${tight}`)
  assert.ok(tighter < tight, 'less room, smaller')
  assert.equal(setsScale({ ...args, width: 100 }), 0.6, 'never below the floor')
  assert.ok(need > 100 && need < 140, `five columns want ~${need}`)
})

test('a live match counts its point column and the serve slot', () => {
  const done = setsScale({ width: 320, scale: 1, cols: 3, point: false, twoDigit: false, tiebreaks: 0, live: false })
  const live = setsScale({ width: 320, scale: 1, cols: 4, point: true, twoDigit: false, tiebreaks: 0, live: true })
  assert.equal(done, 1)
  assert.ok(live <= done)
})

test('a two-digit match tiebreak widens every box', () => {
  assert.ok(setsWidth({ cols: 3, point: false, twoDigit: true, tiebreaks: 0 }) > setsWidth({ cols: 3, point: false, twoDigit: false, tiebreaks: 0 }))
})
