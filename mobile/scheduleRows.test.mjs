/*
 * Which schedule rows a tournament filter keeps, and how the live draws fold
 * into the tournaments the chooser offers.
 *
 *     node scheduleRows.test.mjs
 *
 * A plain node script, like scoring.test.mjs.
 */
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import assert from 'node:assert/strict'

/* Loaded through a data: URL like scoring.test.mjs, and for the same reason:
   package.json is not type:module (React Native uses babel), so importing the
   .js directly makes node reparse it and warn. scheduleRows imports nothing,
   so a data: URL resolves it completely. */
const src = readFileSync(new URL('./scheduleRows.js', import.meta.url), 'utf8')
const { rowInTournaments, sameDrawSet, tournamentsOf } =
  await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'))

let n = 0
function check(name, fn) {
  try { fn(); n += 1; console.log(`  ok  ${name}`) }
  catch (e) { console.log(`  FAIL ${name}\n      ${e.message}`); process.exitCode = 1 }
}

const chosen = new Set([35])          // Guadalajara's tournament

check('a row of a chosen tournament stays', () => {
  assert.equal(rowInTournaments({ tournament_id: 35, draw_id: 142 }, chosen), true)
})

check('QUALIFYING AND DOUBLES STAY, having no draw of their own', () => {
  /* 12 September: Guadalajara and SP Open were playing qualifying only — rows
     with no draw_id and no tour. Matching on the DRAW hid them; matching on
     the tournament cannot. */
  assert.equal(rowInTournaments({ tournament_id: 35, draw_id: null }, chosen), true)
})

check('a row of another tournament goes', () => {
  assert.equal(rowInTournaments({ tournament_id: 92, draw_id: 78 }, chosen), false)
  assert.equal(rowInTournaments({ tournament_id: 92, draw_id: null }, chosen), false)
})

check('no filter shows everything', () => {
  assert.equal(rowInTournaments({ tournament_id: 1, draw_id: null }, null), true)
})

check('the two draws of one event fold into ONE row', () => {
  const live = [
    { id: 77, name: 'US Open', gender: 'M', tournament_id: 92 },
    { id: 78, name: 'US Open', gender: 'F', tournament_id: 92 },
    { id: 142, name: 'Guadalajara Open', gender: 'F', tournament_id: 35 },
  ]
  const out = tournamentsOf(live)
  assert.equal(out.length, 2)
  const us = out.find(t => t.id === 92)
  assert.deepEqual(us.genders, ['M', 'F'], 'men first, so a pair never swaps sides')
  assert.deepEqual(out.find(t => t.id === 35).genders, ['F'])
})

check('a draw with no tournament id is dropped, not offered', () => {
  // No schedule row could ever match it, so offering it would be offering a
  // filter that empties the screen.
  assert.deepEqual(tournamentsOf([{ id: 1, name: 'Orphan', gender: 'M', tournament_id: null }]), [])
  assert.deepEqual(tournamentsOf(null), [])
})

check('sameDrawSet compares membership, not identity', () => {
  assert.equal(sameDrawSet(new Set([1, 2]), new Set([2, 1])), true)
  assert.equal(sameDrawSet(new Set([1]), new Set([1, 2])), false)
  assert.equal(sameDrawSet(null, null), true)
  assert.equal(sameDrawSet(null, new Set([1])), false)
})

console.log(`\n  ${n} passed`)
