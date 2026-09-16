// node frontend/src/utils/dayOrder.test.mjs
//
// The order the schedule's Time view lists a day in. Every case below is a
// row shape a real day produced.
import assert from 'node:assert/strict'
import { byTimeOfDay } from './dayOrder.js'

let failed = 0
function check(label, fn) {
  try { fn(); console.log(`ok   ${label}`) } catch (e) { failed++; console.log(`FAIL ${label}\n     ${e.message}`) }
}
const ids = rows => byTimeOfDay(rows).map(r => r.id)

/* Guadalajara, 2026-09-17 (doc 274). The doubles SF was printed "Time TBA -
   After suitable rest" and had nothing ahead of it on its court, so it had no
   estimate — and was listed above the 1:00 PM opener. */
const skarch = [
  { id: 1235, court: 'ESTADIO SKARCH', court_order: 1, status: 'scheduled', expected_start_at: '2026-09-17T19:00:00Z' },
  { id: 1236, court: 'ESTADIO SKARCH', court_order: 2, status: 'scheduled', expected_start_at: '2026-09-17T20:51:00Z' },
  { id: 1237, court: 'ESTADIO SKARCH', court_order: 3, status: 'scheduled', expected_start_at: '2026-09-17T23:00:00Z' },
  { id: 1238, court: 'ESTADIO SKARCH', court_order: 4, status: 'scheduled', expected_start_at: '2026-09-18T00:51:00Z' },
]
const tba = { id: 1239, court: 'CANCHA MEXCOVERY.COM', court_order: 1, status: 'scheduled',
              start_note: 'Time TBA - After suitable rest', expected_start_at: null }

check('a slot with no time at all comes after every timed one', () => {
  assert.deepEqual(ids([tba, ...skarch]), [1235, 1236, 1237, 1238, 1239])
})
check('an empty string is no time either', () => {
  assert.deepEqual(ids([{ ...tba, expected_start_at: '' }, skarch[0]]), [1235, 1239])
})
check('two untimed rows keep their court order', () => {
  const a = { ...tba, id: 1, court_order: 2 }, b = { ...tba, id: 2, court_order: 1 }
  assert.deepEqual(ids([a, skarch[0], b]), [1235, 2, 1])
})
check('a started match sorts on when it began, not what was printed', () => {
  const late = { ...skarch[0], id: 9, started_at: '2026-09-17T21:30:00Z' }
  assert.deepEqual(ids([late, skarch[1]]), [1236, 9])
})
/* SP Open, 2026-09-16: a carried match keeps yesterday's started_at. */
check('a carried match sorts on the slot it resumes in', () => {
  const carried = { id: 7, court: 'CENTRAL', court_order: 1, status: 'to_be_completed',
                    started_at: '2026-09-15T18:00:00Z', expected_start_at: '2026-09-17T22:00:00Z' }
  assert.deepEqual(ids([carried, skarch[1]]), [1236, 7])
})
check('a carried match with no slot yet is untimed, not yesterday', () => {
  const carried = { id: 7, court: 'CENTRAL', court_order: 1, status: 'to_be_completed',
                    started_at: '2026-09-15T18:00:00Z', expected_start_at: null }
  assert.deepEqual(ids([carried, skarch[0]]), [1235, 7])
})
check('the input is not reordered in place', () => {
  const rows = [tba, skarch[0]]
  byTimeOfDay(rows)
  assert.deepEqual(rows.map(r => r.id), [1239, 1235])
})

console.log(failed ? `\n${failed} FAILED` : '\nall passed')
process.exit(failed ? 1 : 0)
