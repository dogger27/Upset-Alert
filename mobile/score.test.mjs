import { test } from 'node:test'
import assert from 'node:assert/strict'
import { parseSet, endedWith, winnerSideOf, setWon, scoreSets } from './score.js'

test('a cell splits into games and tiebreak, and sheds a retirement mark', () => {
  assert.deepEqual(parseSet('7(7)'), { g: '7', tb: '7' })
  assert.deepEqual(parseSet('0r'), { g: '0', tb: null })
  assert.deepEqual(parseSet('6'), { g: '6', tb: null })
  assert.deepEqual(parseSet('w/o'), { g: '', tb: null })
  assert.deepEqual(parseSet(null), { g: '', tb: null })
})

test('the end marker names the winner, and a retirement from ahead still loses', () => {
  const ret = { status: 'completed', scores: [['6', '3'], ['4', '0r']] }   // side 1 quit while behind
  assert.equal(endedWith(ret.scores, 1), 'ret.')
  assert.equal(winnerSideOf(ret), 0)
  const ahead = { status: 'completed', scores: [['4', '0r'], ['6', '3']] } // side 0 quit
  assert.equal(winnerSideOf(ahead), 1)
  const wo = { status: 'completed', scores: [['w/o'], []] }
  assert.equal(endedWith(wo.scores, 0), 'w/o')
  assert.equal(winnerSideOf(wo), 0)
  assert.equal(winnerSideOf({ status: 'completed', winner_side: 1, scores: [['6', '6'], ['0', '0']] }), 1)
  assert.equal(winnerSideOf({ status: 'live', scores: [['6'], ['0']] }), null)
})

test('a set in play is never won; a decided one is', () => {
  const sets = [['6', '4'], ['3', '1']]          // per SIDE: side 0 leads 6-3, 4-1
  assert.equal(setWon(sets, 0, 0, true, null), true)
  assert.equal(setWon(sets, 1, 0, true, null), false)   // in play
  assert.equal(setWon(sets, 1, 0, false), true)         // over: decided
  assert.equal(setWon(sets, 0, 1, false), false)
})

test('one source per render', () => {
  const lp = { games: [['6', '2'], ['4', '1']], point: ['40', '30'] }
  assert.deepEqual(scoreSets({ status: 'live', live_point: lp, scores: [['6'], ['4']] }), lp.games)
  assert.deepEqual(scoreSets({ status: 'completed', live_point: lp, scores: [['6', '6'], ['4', '4']] }), [['6', '6'], ['4', '4']])
  assert.deepEqual(scoreSets({ status: 'postponed', live_point: lp, scores: null }), lp.games)
})

test('the one-line score names the tiebreak for its loser only', async () => {
  const { scoreLine } = await import('./score.js')
  assert.equal(scoreLine([['7(7)', '6', '3'], ['6(4)', '4', '0r']]), '7-6⁴  6-4  3-0 (ret.)')
  assert.equal(scoreLine([['6(3)', '6'], ['7', '4']]), '6³-7  6-4')
  assert.equal(scoreLine([['w/o'], []]), 'walkover')
  assert.equal(scoreLine(null), null)
})
