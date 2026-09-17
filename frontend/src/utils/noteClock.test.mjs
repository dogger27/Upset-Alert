// node frontend/src/utils/noteClock.test.mjs
//
// The clock inside a printed slot note, rewritten into the reader's zone.
import assert from 'node:assert/strict'
import { noteHasClock, rewriteNoteClock } from './noteClock.js'

let failed = 0
function check(label, fn) {
  try { fn(); console.log(`ok   ${label}`) } catch (e) { failed++; console.log(`FAIL ${label}\n     ${e.message}`) }
}

check('the stored clock is the note\'s own substring', () => {
  assert.equal(rewriteNoteClock('Not before 3:00 PM', '3:00 PM', '12:00 PM'), 'Not before 12:00 PM')
  assert.equal(rewriteNoteClock('Starts At 14:30', '14:30', '8:30 AM'), 'Starts At 8:30 AM')
})
/* SP Open, 2026-09-17: "NB 2:30 possible court change" printed no PM, and the
   ingest stores the clock it means — so the stored clock is no longer in the
   note, and the plain replace left the venue's clock on a "my time" page. */
check('a clock the sheet printed without PM is still found', () => {
  assert.equal(rewriteNoteClock('NB 2:30 possible court change', '2:30 PM', '11:30 AM'),
               'NB 11:30 AM possible court change')
})
check('a dotted meridiem in the note is replaced with the clock', () => {
  assert.equal(rewriteNoteClock('Not before 2:30 p.m.', '2:30 PM', '11:30 AM'), 'Not before 11:30 AM')
})
check('digits are matched whole', () => {
  assert.equal(rewriteNoteClock('After 12:30 match, NB 2:30', '2:30 PM', '11:30 AM'),
               'After 12:30 match, NB 11:30 AM')
})
check('a clock that is not in the note leaves it alone', () => {
  assert.equal(rewriteNoteClock('After suitable rest', '2:30 PM', '11:30 AM'), 'After suitable rest')
})
/* SP Open, 2026-09-17: "Followed by" under a blank box printed "Starting at
   12:00 PM" — the row holds the noon, the note does not. */
check('a note with no clock of its own is told apart', () => {
  assert.equal(noteHasClock('Followed by'), false)
  assert.equal(noteHasClock('After suitable rest'), false)
  assert.equal(noteHasClock(null), false)
  assert.equal(noteHasClock('NB 2:30 possible court change'), true)
  assert.equal(noteHasClock('Starts At 14.30'), true)
})

if (failed) { console.log(`${failed} FAILED`); process.exit(1) }
console.log('PASS')
