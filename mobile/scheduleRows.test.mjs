/*
 * Which schedule rows a draw filter keeps.
 *
 *     node scheduleRows.test.mjs
 *
 * A plain node script, like scoring.test.mjs: scheduleRows.js imports nothing,
 * so it loads directly.
 */
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import assert from 'node:assert/strict'

/* Loaded through a data: URL like scoring.test.mjs, and for the same reason:
   package.json is not type:module (React Native uses babel), so importing the
   .js directly makes node reparse it and warn. scheduleRows imports nothing,
   so a data: URL resolves it completely. */
const src = readFileSync(new URL('./scheduleRows.js', import.meta.url), 'utf8')
const { rowInDraws, sameDrawSet } =
  await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'))

let n = 0
function check(name, fn) {
  try { fn(); n += 1; console.log(`  ok  ${name}`) }
  catch (e) { console.log(`  FAIL ${name}\n      ${e.message}`); process.exitCode = 1 }
}

const chosen = new Set([77])          // the men's US Open
const events = new Set([92])          // the tournament behind it

check('a row of a chosen draw stays', () => {
  assert.equal(rowInDraws({ draw_id: 77, tournament_id: 92 }, chosen, events), true)
})

check('the OTHER draw of the same event goes', () => {
  // The whole point of filtering by draw rather than by tournament.
  assert.equal(rowInDraws({ draw_id: 78, tournament_id: 92 }, chosen, events), false)
})

check('doubles of a chosen event stays, having no draw of its own', () => {
  assert.equal(rowInDraws({ draw_id: null, tournament_id: 92 }, chosen, events), true)
})

check('doubles of an event nobody chose goes', () => {
  assert.equal(rowInDraws({ draw_id: null, tournament_id: 35 }, chosen, events), false)
})

check('no filter shows everything', () => {
  assert.equal(rowInDraws({ draw_id: 1, tournament_id: 2 }, null, null), true)
  assert.equal(rowInDraws({ draw_id: null, tournament_id: 2 }, null, null), true)
})

check('a chosen draw with no tournament set still works', () => {
  // drawTournaments is built from the day's rows; a draw playing no singles
  // that day contributes nothing to it, and a doubles row must not then throw.
  assert.equal(rowInDraws({ draw_id: null, tournament_id: 92 }, chosen, null), false)
})

check('sameDrawSet compares membership, not identity', () => {
  assert.equal(sameDrawSet(new Set([1, 2]), new Set([2, 1])), true)
  assert.equal(sameDrawSet(new Set([1]), new Set([1, 2])), false)
  assert.equal(sameDrawSet(null, null), true)
  assert.equal(sameDrawSet(null, new Set([1])), false)
})

console.log(`\n  ${n} passed`)
