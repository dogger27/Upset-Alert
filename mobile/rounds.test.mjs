/*
 * Which round the draw opens on.
 *
 *     node rounds.test.mjs
 *
 * A plain node script, like scoring.test.mjs, and loaded the same way: the
 * package is not type:module, so the source goes through a data: URL rather
 * than being imported by path and reparsed with a warning.
 */
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import assert from 'node:assert/strict'

const src = readFileSync(new URL('./rounds.js', import.meta.url), 'utf8')
const { currentRound, shortRound } =
  await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'))

let n = 0
function check(name, fn) {
  try { fn(); n += 1; console.log(`  ok  ${name}`) }
  catch (e) { console.log(`  FAIL ${name}\n      ${e.message}`); process.exitCode = 1 }
}

const NOW = new Date('2026-09-15T18:00:00Z').getTime()
const at = (h, day = 15) => `2026-09-${String(day).padStart(2, '0')}T${String(h).padStart(2, '0')}:00:00Z`
const won = { winner: { id: 1 } }
const idle = {}

check('the furthest round that started', () => {
  assert.equal(currentRound([[1, [won, won]], [2, [won]], [3, [idle]]], NOW), 2)
})

check("TODAY'S SHEET COUNTS, even before a ball is struck", () => {
  /* The morning of a new round: yesterday's is over, today's is printed and
     has not begun. The round the reader is here for is today's. */
  const rounds = [[1, [won, won]], [2, [{ expected_start_at: at(20) }, idle]], [3, [idle]]]
  assert.equal(currentRound(rounds, NOW), 2)
})

check('a sheet for another day does not count', () => {
  const rounds = [[1, [won]], [2, [{ expected_start_at: at(20, 16) }]]]
  assert.equal(currentRound(rounds, NOW), 1, "tomorrow's sheet is not today's round")
})

check('a postponed match printed today cannot drag the draw backwards', () => {
  // The scan runs from the END, so a straggler rescheduled into today loses to
  // the round actually being played.
  const rounds = [[1, [{ expected_start_at: at(20) }]], [2, [won]]]
  assert.equal(currentRound(rounds, NOW), 2)
})

check('a completed draw opens on its final, not the champion column', () => {
  const rounds = [[1, [won, won]], [2, [won]], [3, [won]], [4, [{ champion: true }]]]
  assert.equal(currentRound(rounds, NOW), 3)
})

check('nothing started and nothing scheduled opens at the first round', () => {
  assert.equal(currentRound([[1, [idle, idle]], [2, [idle]]], NOW), 1)
  assert.equal(currentRound([], NOW), null)
})

check('a bye is not a match, however it is dated', () => {
  const rounds = [[1, [won]], [2, [{ is_bye: true, expected_start_at: at(20) }]]]
  assert.equal(currentRound(rounds, NOW), 1)
})

check('live counts as started', () => {
  assert.equal(currentRound([[1, [won]], [2, [{ live_scores: {} }]]], NOW), 2)
  assert.equal(currentRound([[1, [won]], [2, [{ live_point: {} }]]], NOW), 2)
})

check('shortRound still speaks the scoreboard', () => {
  assert.equal(shortRound('Round of 128'), 'R128')
  assert.equal(shortRound('Quarterfinals'), 'QF')
  assert.equal(shortRound('Final'), 'F')
  assert.equal(shortRound('Champion'), '🏆')
})

console.log(`\n  ${n} passed`)
