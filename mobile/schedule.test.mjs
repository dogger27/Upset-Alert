// The slot line follows the site's printedStart/SHORTEN/CANON rules, and the
// clock inside it follows the zone switch. Zones are pinned so the assertions
// hold on any machine: the "device" is Los Angeles, the venue New York.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { whenLabel, isLive, isSuspended } from './schedule.js'

const LA = 'America/Los_Angeles', NY = 'America/New_York'
const fixed = { status: 'scheduled', start_type: 'fixed', start_time_local: '11:00 AM',
                printed_start_at: '2026-09-02T15:00:00Z', start_note: 'Starts At 11:00 AM' }

test('venue mode keeps the sheet clock; my time rewrites it', () => {
  assert.equal(whenLabel(fixed, NY, true), 'Starting at 11:00 AM')
  assert.equal(whenLabel(fixed, LA, false), 'Starting at 8:00 AM')
})

test('wording is canonical whatever the sheet printed', () => {
  const nb = { ...fixed, start_type: 'not_before', start_note: 'Not Before 11:00 AM' }
  assert.equal(whenLabel(nb, NY, true), 'Not before 11:00 AM')
  assert.equal(whenLabel({ ...fixed, start_note: 'Followed By' }, LA, false), 'Followed by')
  // A dotted clock, as en-CA devices print it, must still split off the wording.
  assert.equal(whenLabel({ ...fixed, start_note: 'Starts At 11:00 a.m.', start_time_local: '11:00 a.m.' }, NY, true), 'Starting at 11:00 a.m.')
})

test('long wordings shorten; rows without a note fall back on the same clock rule', () => {
  assert.equal(whenLabel({ status: 'scheduled', start_note: 'After suitable rest' }, LA, false), 'After rest')
  const bare = { ...fixed, start_note: null, start_type: 'not_before' }
  assert.equal(whenLabel(bare, LA, false), 'Not before 8:00 AM')
  assert.equal(whenLabel(bare, NY, true), 'Not before 11:00 AM')
  assert.equal(whenLabel({ status: 'scheduled' }, LA, false), 'TBA')
})

test('state outranks the printed line', () => {
  assert.equal(whenLabel({ ...fixed, status: 'completed' }, LA, false), 'Completed')
  assert.equal(whenLabel({ ...fixed, status: 'live' }, LA, false), 'In progress')
})

test('a washed-out day has two halves, and neither is live', () => {
  const frozen = { ...fixed, live_point: { suspended: true }, live_scores: [[6, 3], [4, 6], 2, 0, 'suspended'] }
  assert.equal(whenLabel({ ...frozen, status: 'postponed' }, LA, false), 'Postponed')
  assert.equal(whenLabel({ ...frozen, status: 'to_be_completed' }, LA, false), 'To be completed')
  assert.equal(whenLabel({ ...frozen, status: 'live' }, LA, false), 'Suspended')
  assert.equal(isLive({ ...frozen, status: 'postponed' }), false)
  assert.equal(isSuspended({ ...frozen, status: 'postponed' }), false)
  assert.equal(isLive({ ...frozen, status: 'live' }), true)
  assert.equal(isSuspended({ ...frozen, status: 'live' }), true)
})
