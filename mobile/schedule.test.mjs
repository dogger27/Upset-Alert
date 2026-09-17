// The slot line follows the site's printedStart/SHORTEN/CANON rules, and the
// clock inside it follows the zone switch. Zones are pinned so the assertions
// hold on any machine: the "device" is Los Angeles, the venue New York.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { byTimeOfDay, footTime, whenLabel, isLive, isSuspended } from './schedule.js'

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
  assert.equal(line({ status: 'scheduled', start_type: 'followed_by', start_note: 'Followed By' }, LA, false).text, 'Followed by')
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

/* Guadalajara, 2026-09-17: the doubles SF was printed "Time TBA - After
   suitable rest" with nothing ahead of it on its court — no estimate — and
   was listed above the 1:00 PM opener. */
test('a slot with no time at all comes after every timed one', () => {
  const at = (id, court, order, iso) => ({ id, court, court_order: order, status: 'scheduled', expected_start_at: iso })
  const rows = [
    at(1239, 'CANCHA MEXCOVERY.COM', 1, null),
    at(1236, 'ESTADIO SKARCH', 2, '2026-09-17T20:51:00Z'),
    at(1235, 'ESTADIO SKARCH', 1, '2026-09-17T19:00:00Z'),
    at(1240, 'CANCHA MEXCOVERY.COM', 2, ''),
  ]
  assert.deepEqual(byTimeOfDay(rows).map(r => r.id), [1235, 1236, 1239, 1240])
  const carried = { id: 7, court: 'CENTRAL', court_order: 1, status: 'to_be_completed',
                    started_at: '2026-09-15T18:00:00Z', expected_start_at: '2026-09-17T22:00:00Z' }
  assert.deepEqual(byTimeOfDay([carried, rows[1]]).map(r => r.id), [1236, 7])
})

/* SP Open, 2026-09-17: "NB 2:30 possible court change" printed no PM, and the
   ingest now stores the clock it means — "2:30 PM" — so the stored clock is no
   longer a substring of the note it came from. The clock inside the note must
   still follow the zone switch. */
test('a clock the sheet printed without PM still follows the zone switch', () => {
  const nb = { status: 'scheduled', start_type: 'not_before', start_time_local: '2:30 PM',
               printed_start_at: '2026-09-17T18:30:00Z', start_note: 'NB 2:30 possible court change' }
  assert.equal(line(nb, NY, true).text, 'NB 2:30 possible court change')
  assert.equal(line(nb, LA, false).text, 'NB 11:30 AM possible court change')
  // The digits are matched whole: a 2:30 clock never rewrites a 12:30 inside a note.
  const noon = { ...nb, start_time_local: '2:30 PM', start_note: 'After 12:30 match, NB 2:30' }
  assert.equal(line(noon, LA, false).text, 'After 12:30 match, NB 11:30 AM')
})

/* SP Open, 2026-09-17 (doc 277): QUADRA 2's first box was blank under
   "Starting at 12:00 PM" and the court's first match printed "Followed by".
   The ingest keeps the noon on the row and the note as printed, so a line
   built from the note alone printed "Followed by" — followed by nothing — and
   no time. The row's clock is the line, in either zone. */
test('a clock handed down from a blank box is the line', () => {
  const opener = { status: 'scheduled', start_type: 'followed_by', start_time_local: '12:00 PM',
                   printed_start_at: '2026-09-17T15:00:00Z', start_note: 'Followed by',
                   expected_start_at: '2026-09-17T15:00:00Z', expected_source: 'printed' }
  assert.deepEqual(line(opener, NY, true), { text: '12:00 PM', estimated: false, displaced: null })
  assert.equal(line(opener, LA, false).text, '8:00 AM')
  assert.equal(footTime(opener, LA, false, false).text, '8:00 AM')
  // No clock on the row: the wording is all there is.
  assert.equal(line({ ...opener, start_time_local: null, printed_start_at: null }, LA, false).text,
               'Followed by')
})
