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
const { drawsByTournament, holdSelection, rowInTournaments, sameDrawSet, tournamentsOf } =
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

check('drawsByTournament keeps the draws, grouped, in the caller\'s order', () => {
  const live = [
    { id: 142, name: 'Guadalajara Open', gender: 'F', tournament_id: 35 },
    { id: 78, name: 'US Open', gender: 'F', tournament_id: 92 },
    { id: 77, name: 'US Open', gender: 'M', tournament_id: 92 },
  ]
  const out = drawsByTournament(live)
  assert.equal(out.length, 2, 'two events')
  assert.deepEqual(out[0].map(d => d.id), [142], 'a group takes the place of its first draw')
  assert.deepEqual(out[1].map(d => d.id), [77, 78], 'men first, whatever order they arrived in')
})

check('a draw with no tournament id is its OWN group, not dropped', () => {
  // The opposite of tournamentsOf: there it would offer a filter that empties
  // the screen; here dropping it would hide a card.
  const out = drawsByTournament([{ id: 1, name: 'Orphan', gender: 'M', tournament_id: null },
                                 { id: 2, name: 'Other', gender: 'F', tournament_id: null }])
  assert.deepEqual(out.map(g => g.map(d => d.id)), [[1], [2]], 'and never folded together')
  assert.deepEqual(drawsByTournament(null), [])
})

check('sameDrawSet compares membership, not identity', () => {
  assert.equal(sameDrawSet(new Set([1, 2]), new Set([2, 1])), true)
  assert.equal(sameDrawSet(new Set([1]), new Set([1, 2])), false)
  assert.equal(sameDrawSet(null, null), true)
  assert.equal(sameDrawSet(null, new Set([1])), false)
})

console.log(`\n  ${n} passed`)


/* ── A LONG HOLD: ISOLATE, AND UNDO ITSELF ───────────────────────────────
 *
 * A hold shows only the tournament held (owner, 2026-09-21). Holding the one
 * that is already alone shows everything again — "Long holding on a draw when
 * only one draw is selected should select ALL draws" — so the gesture is its
 * own undo and nobody has to tap four pills back on.
 *
 * `null` is the store's word for every tournament, both in and out.
 */
const held = (sel, id) => holdSelection(sel === null ? null : new Set(sel), id)
const ids = (r) => (r === null ? 'ALL' : [...r].sort())

// From everything, a hold isolates.
assert.equal(ids(held(null, 3)).join(), '3')
// From several, a hold isolates.
assert.equal(ids(held([1, 2, 3], 2)).join(), '2')
// From the lone one — THE NEW CASE — a hold shows everything.
assert.equal(ids(held([2], 2)), 'ALL')

/* Holding a DIFFERENT pill still isolates it, even while one draw is the only
   one showing. The other reading — any hold means "all" once one draw is
   alone — would make the second isolate unreachable by the gesture that
   performs it. */
assert.equal(ids(held([2], 5)).join(), '5')

// Two selected is not one, whichever is held.
assert.equal(ids(held([2, 5], 2)).join(), '2')
assert.equal(ids(held([2, 5], 5)).join(), '5')

// An empty selection is the store's other spelling of "everything", and a hold
// off it isolates like any other.
assert.equal(ids(held([], 4)).join(), '4')

// It never mutates what it was given: the store compares by reference and a
// selection edited in place would be re-published as an equal object.
{
  const before = new Set([2])
  const out = holdSelection(before, 5)
  assert.equal([...before].join(), '2')
  assert.equal([...out].join(), '5')
  assert.notEqual(out, before)
}
