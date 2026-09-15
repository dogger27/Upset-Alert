// node frontend/src/utils/playState.test.mjs
//
// The rule that decides whether a schedule row keeps its time line. Every case
// below is a row shape a real day produced and this reading once got wrong.
import assert from 'node:assert/strict'
import { isSuspended, isUnderWay } from './playState.js'

let failed = 0
function check(label, fn) {
  try { fn(); console.log(`ok   ${label}`) } catch (e) { failed++; console.log(`FAIL ${label}\n     ${e.message}`) }
}

// The frozen payload a match keeps after rain stops it: games, no serving
// side, and the word in the fifth slot. It does not change when the day does.
const frozen = { live_scores: [['6', '5', '2'], ['1', '7', '2'], null, [true, false, null], 'suspended'] }

check('a live match stopped by rain is suspended', () => {
  assert.equal(isSuspended({ ...frozen, status: 'live' }), true)
  assert.equal(isUnderWay({ ...frozen, status: 'live' }), true)
})
check('the point payload spells it too', () => {
  const e = { status: 'live', live_point: { suspended: true } }
  assert.equal(isSuspended(e), true)
})
/* SP Open, 2026-09-16. Three R32 matches carried out of Tuesday's rain, each
   printed "Not before 2:00 PM" on Wednesday's sheet, each showing no time at
   all on the page — the stale flag read as "on court right now". */
check('a match carried to a new day keeps its time line', () => {
  const e = { ...frozen, status: 'to_be_completed', start_note: 'Not before 2:00 PM' }
  assert.equal(isSuspended(e), false)
  assert.equal(isUnderWay(e), false)
})
check('a postponed match keeps its time line', () => {
  const e = { ...frozen, status: 'postponed' }
  assert.equal(isSuspended(e), false)
  assert.equal(isUnderWay(e), false)
})
check('a carried match whose only evidence is the point flag', () => {
  const e = { status: 'to_be_completed', live_point: { suspended: true } }
  assert.equal(isUnderWay(e), false)
})
check('on court and finished still lose the line', () => {
  assert.equal(isUnderWay({ status: 'live' }), true)
  assert.equal(isUnderWay({ status: 'completed' }), true)
})
check('an ordinary scheduled row keeps its line', () => {
  assert.equal(isUnderWay({ status: 'scheduled' }), false)
})
check('nothing at all does not throw', () => {
  assert.equal(isUnderWay(undefined), false)
  assert.equal(isSuspended(null), false)
})

console.log(failed ? `\n${failed} FAILED` : '\nall passed')
process.exit(failed ? 1 : 0)
