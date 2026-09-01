/*
 * Tests for the two comparisons that decide what the app SAYS.
 *
 * There is no test runner in this project yet and adding one is not worth it
 * for two pure functions, so this is a plain node script:
 *
 *     node scoring.test.mjs
 *
 * scoring.js is ESM but package.json is not type:module (React Native uses
 * babel), so it is loaded through a data: URL rather than renamed.
 */

import { readFileSync } from 'node:fs'
import assert from 'node:assert/strict'

const src = readFileSync(new URL('./scoring.js', import.meta.url), 'utf8')
const { competitionRanks, sameStanding, slotLabel } =
  await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'))

let n = 0
const check = (name, fn) => { fn(); n++; console.log('  ok  ' + name) }

check('ties share a rank and the next rank skips', () => {
  const e = [
    { total: 10, round_points: [4, 6] },
    { total: 10, round_points: [4, 6] },
    { total: 10, round_points: [4, 6] },
    { total: 5,  round_points: [5, 0] },
  ]
  assert.deepEqual(competitionRanks(e), [1, 1, 1, 4])
})

check('same total but a different round vector is NOT a tie', () => {
  // Both on 10, but the server put the later-round points first. Comparing
  // totals alone would wrongly call these level.
  const e = [
    { total: 10, round_points: [0, 10] },
    { total: 10, round_points: [10, 0] },
  ]
  assert.equal(sameStanding(e[0], e[1]), false)
  assert.deepEqual(competitionRanks(e), [1, 2])
})

check('a lone entry ranks first, and an empty list is empty', () => {
  assert.deepEqual(competitionRanks([{ total: 3, round_points: [3] }]), [1])
  assert.deepEqual(competitionRanks([]), [])
})

check('a bye still shows the player who received it', () => {
  const m = { is_bye: true }
  assert.equal(slotLabel({ name: 'Sinner', seed: 1 }, m), 'Sinner')
  assert.equal(slotLabel(null, m), 'Bye')
})

check('an empty slot in a normal match is TBD, not a bye', () => {
  assert.equal(slotLabel(null, { is_bye: false }), 'TBD')
})

check('an unnamed qualifier slot reads Qualifier', () => {
  assert.equal(slotLabel({ entry_type: 'Q', name: '' }, { is_bye: false }), 'Qualifier')
  // Once the qualifier is known, the name wins.
  assert.equal(slotLabel({ entry_type: 'Q', name: 'Nardi' }, { is_bye: false }), 'Nardi')
})

console.log(`\n  ${n} passed`)
