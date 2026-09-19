import { test } from 'node:test'
import assert from 'node:assert/strict'
import { lockLabel, othersPicksNote } from './lock.js'

test('others’ picks: the mode decides the wait, and an active draw has none', () => {
  assert.equal(othersPicksNote({ status: 'active', pick_lock_mode: 'r1_progressive' }), null)
  assert.equal(othersPicksNote({ status: 'completed' }), null)
  assert.match(othersPicksNote({ status: 'open', pick_lock_mode: 'r1_progressive', closing_time: '2026-09-01T15:00:00' }),
               /every first-round match has started/)
  assert.match(othersPicksNote({ status: 'open', pick_lock_mode: 'classic', closing_time: '2026-09-01T15:00:00' }),
               /after pick selection closes: /)
  assert.match(othersPicksNote({ status: 'open' }), /after pick selection closes\.$/)
})

/* THE TWO KINDS OF DEADLINE (owner, 2026-09-19): a clock, or a place in the
   tournament. `label` leads quietly and `value` carries the weight. */
const AT = '2026-09-21T15:00:00'
const at = (h, m = 0) => Date.parse(`${AT}Z`) - ((h * 60 + m) * 60_000)

test('a match-by-match draw locks at an EVENT, and names no hour for it', () => {
  const got = lockLabel({ pick_lock_mode: 'r1_progressive', closing_time: AT }, at(30))
  assert.equal(got.label, 'Lock at:')
  assert.equal(got.value, 'End of R1')
  assert.equal(got.text, 'Lock at: End of R1')
  assert.equal(got.urgent, false)
  // Even with a closing_time sitting right there, it must not be counted down.
  assert.ok(!/hr|min|day/.test(got.text))
})

test('every other draw counts down to its moment', () => {
  const t = { pick_lock_mode: 'draw_start', closing_time: AT }
  // Hours right out to three days — the owner's own example was "52 hrs".
  assert.equal(lockLabel(t, at(52)).text, 'Locks in: 52 hrs')
  assert.equal(lockLabel(t, at(24)).text, 'Locks in: 24 hrs')
  assert.equal(lockLabel(t, at(71, 59)).text, 'Locks in: 71 hrs')
  // Past three days the number stops meaning anything.
  assert.equal(lockLabel(t, at(72)).text, 'Locks in: 3 days')
  assert.equal(lockLabel(t, at(24 * 9)).text, 'Locks in: 9 days')
  // Inside the day, hours and minutes; inside the hour, minutes.
  assert.equal(lockLabel(t, at(5, 30)).text, 'Locks in: 5h 30m')
  assert.equal(lockLabel(t, at(0, 45)).text, 'Locks in: 45m')
})

test('urgent turns on inside six hours, and not before', () => {
  const t = { pick_lock_mode: 'draw_start', closing_time: AT }
  assert.equal(lockLabel(t, at(24)).urgent, false)
  assert.equal(lockLabel(t, at(6)).urgent, false)
  assert.equal(lockLabel(t, at(5, 59)).urgent, true)
  assert.equal(lockLabel(t, at(0, 20)).urgent, true)
})

test('closed is closed, whichever way it got there', () => {
  assert.equal(lockLabel({ is_locked: true }).text, 'Picks closed')
  // The clock ran out but nothing has stamped it yet.
  assert.equal(lockLabel({ closing_time: AT }, at(-1)).text, 'Picks closed')
  // A progressive draw that HAS locked reads closed, not "End of R1".
  assert.equal(lockLabel({ is_locked: true, pick_lock_mode: 'r1_progressive' }).text, 'Picks closed')
})

test('nothing to say, rather than something wrong', () => {
  assert.equal(lockLabel(null), null)
  assert.equal(lockLabel({ pick_lock_mode: 'draw_start' }), null)
  assert.equal(lockLabel({ closing_time: 'not a date' }), null)
})
