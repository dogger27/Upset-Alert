import { test } from 'node:test'
import assert from 'node:assert/strict'
import { othersPicksNote } from './lock.js'

test('others’ picks: the mode decides the wait, and an active draw has none', () => {
  assert.equal(othersPicksNote({ status: 'active', pick_lock_mode: 'r1_progressive' }), null)
  assert.equal(othersPicksNote({ status: 'completed' }), null)
  assert.match(othersPicksNote({ status: 'open', pick_lock_mode: 'r1_progressive', closing_time: '2026-09-01T15:00:00' }),
               /every first-round match has started/)
  assert.match(othersPicksNote({ status: 'open', pick_lock_mode: 'classic', closing_time: '2026-09-01T15:00:00' }),
               /after pick selection closes: /)
  assert.match(othersPicksNote({ status: 'open' }), /after pick selection closes\.$/)
})
