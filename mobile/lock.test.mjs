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

/* ONE DEADLINE, BOTH MODES (owner, 2026-09-19, correcting himself the same
   day): locking STARTS at the first ball whatever the mode, so every draw
   counts down to it. `label` leads quietly and `value` carries the weight. */
const AT = '2026-09-21T15:00:00'
const at = (h, m = 0) => Date.parse(`${AT}Z`) - ((h * 60 + m) * 60_000)

test('a match-by-match draw counts down like any other', () => {
  const prog = { pick_lock_mode: 'r1_progressive', closing_time: AT }
  const plain = { pick_lock_mode: 'draw_start', closing_time: AT }
  // The mode changes which picks survive the first ball, not when the first
  // ball is — so the line reads the same on both.
  assert.equal(lockLabel(prog, at(35)).text, 'Locks in: 35 hrs')
  assert.equal(lockLabel(prog, at(35)).text, lockLabel(plain, at(35)).text)
  assert.equal(lockLabel(prog, at(4, 30)).text, 'Locks in: 4h 30m')
})

test('once the first ball has gone, the two modes part company', () => {
  const prog = { pick_lock_mode: 'r1_progressive', closing_time: AT }
  const plain = { pick_lock_mode: 'draw_start', closing_time: AT }
  /* THE ONE WINDOW THAT DIFFERS. A progressive draw is not `is_locked` until
     round one COMPLETES, so between the first ball and that moment a card
     would otherwise claim picks were closed for the two days a first round
     takes — while the draw screen still accepts changes to untouched later
     rounds. */
  assert.equal(lockLabel(prog, at(-1)).text, 'Lock at: End of R1')
  assert.equal(lockLabel(plain, at(-1)).text, 'Picks closed')
  // And once it HAS locked, it is closed like anything else.
  assert.equal(lockLabel({ ...prog, is_locked: true }, at(-30)).text, 'Picks closed')
})

test('every draw counts down to its moment', () => {
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
  // A progressive draw that HAS locked reads closed, not "End of R1" —
  // is_locked is checked before the clock for exactly this reason.
  assert.equal(lockLabel({ is_locked: true, pick_lock_mode: 'r1_progressive' }).text, 'Picks closed')
})

test('nothing to say, rather than something wrong', () => {
  assert.equal(lockLabel(null), null)
  assert.equal(lockLabel({ pick_lock_mode: 'draw_start' }), null)
  assert.equal(lockLabel({ closing_time: 'not a date' }), null)
})
