// The slot line follows the site's printedStart/SHORTEN/CANON rules, and the
// clock inside it follows the zone switch. Zones are pinned so the assertions
// hold on any machine: the "device" is Los Angeles, the venue New York.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { footTime, whenLabel, isLive, isSuspended } from './schedule.js'

const LA = 'America/Los_Angeles', NY = 'America/New_York'
const fixed = { status: 'scheduled', start_type: 'fixed', start_time_local: '11:00 AM',
                printed_start_at: '2026-09-02T15:00:00Z', start_note: 'Starts At 11:00 AM' }

/* The slot line is footTime's — whenLabel is the status pill alone now, and
   draws nothing for a row that has not started. `inCourt` true is the grouped
   layout, where the sheet's own wording is shown; the scaffolding words
   ("Starting at", "Not before") are stripped to their clock and kept in
   `displaced` for the accessibility label. */
const line = (e, zone, venue) => footTime(e, zone, venue, true)

test('venue mode keeps the sheet clock; my time rewrites it', () => {
  assert.deepEqual(line(fixed, NY, true), { text: '11:00 AM', estimated: false, displaced: 'Starting at 11:00 AM' })
  assert.equal(line(fixed, LA, false).text, '8:00 AM')
  assert.equal(line(fixed, LA, false).displaced, 'Starting at 8:00 AM')
})

test('wording is canonical whatever the sheet printed', () => {
  const nb = { ...fixed, start_type: 'not_before', start_note: 'Not Before 11:00 AM' }
  assert.deepEqual(line(nb, NY, true), { text: '11:00 AM', estimated: false, displaced: 'Not before 11:00 AM' })
  assert.equal(line({ ...fixed, start_note: 'Followed By' }, LA, false).text, 'Followed by')
  // A dotted clock, as en-CA devices print it, must still split off the wording.
  assert.deepEqual(line({ ...fixed, start_note: 'Starts At 11:00 a.m.', start_time_local: '11:00 a.m.' }, NY, true),
                   { text: '11:00 a.m.', estimated: false, displaced: 'Starting at 11:00 a.m.' })
})

test('long wordings shorten; rows without a note fall back on the same clock rule', () => {
  assert.equal(line({ status: 'scheduled', start_note: 'After suitable rest' }, LA, false).text, 'After rest')
  const bare = { ...fixed, start_note: null, start_type: 'not_before' }
  assert.deepEqual(line(bare, LA, false), { text: '8:00 AM', estimated: false, displaced: 'Not before 8:00 AM' })
  assert.equal(line(bare, NY, true).text, '11:00 AM')
  assert.equal(line({ status: 'scheduled' }, LA, false).text, 'TBA')
})

test('a started or finished row has no slot line at all', () => {
  assert.equal(line({ ...fixed, status: 'live' }, LA, false).text, '')
  assert.equal(line({ ...fixed, status: 'completed' }, LA, false).text, '')
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
