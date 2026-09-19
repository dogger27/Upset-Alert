import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  blockedByLive, computeNextPicks, namesChampion, picksFromRows, picksMap, projectPicks,
} from './picks.js'

/* A four-entrant draw: two first-round matches feeding one final.
   Rankings put 1 ahead of 3 ahead of 4 ahead of 2, so "better-ranked" is
   never the same as "listed first" and a wrong tiebreak shows up. */
const ENTRIES = [
  { id: 1, ranking: 1 }, { id: 2, ranking: 50 }, { id: 3, ranking: 10 }, { id: 4, ranking: 20 },
]
const M = {
  a: { id: 101, round_number: 1, match_number: 1, player1: { id: 1 }, player2: { id: 2 } },
  b: { id: 102, round_number: 1, match_number: 2, player1: { id: 3 }, player2: { id: 4 } },
  f: { id: 201, round_number: 2, match_number: 1 },
}
const MATCHES = [M.a, M.b, M.f]

test('projection: nothing is left blank — every match takes the better-ranked player', () => {
  const out = projectPicks({}, MATCHES, ENTRIES)
  assert.equal(out[101], 1)          // 1 over 2
  assert.equal(out[102], 3)          // 3 over 4
  assert.equal(out[201], 1)          // 1 over 3
})

test('projection: a choice carries forward, and the pair it meets follows from it', () => {
  const out = projectPicks({ 101: 2 }, MATCHES, ENTRIES)
  assert.equal(out[101], 2)
  // The final is now 2 v 3, and 3 is the better ranked of those two.
  assert.equal(out[201], 3)
})

test('projection: a pick nobody can reach is passed over, not honoured', () => {
  // 4 was picked to win the final but is projected out in round one.
  const out = projectPicks({ 201: 4 }, MATCHES, ENTRIES)
  assert.equal(out[201], 1)
})

test('projection: a bye advances its occupant and is never given a pick', () => {
  const bye = { id: 103, round_number: 1, match_number: 1, is_bye: true, player1: { id: 2 } }
  const next = { id: 104, round_number: 1, match_number: 2, player1: { id: 3 }, player2: { id: 4 } }
  const fin = { id: 205, round_number: 2, match_number: 1 }
  const out = projectPicks({}, [bye, next, fin], ENTRIES)
  assert.ok(!(103 in out), 'the bye match has no pick')
  assert.equal(out[205], 3, 'the bye’s occupant met 3 and lost on ranking')
})

test('projection: a draw with no matches is returned untouched', () => {
  const base = { 101: 2 }
  assert.deepEqual(projectPicks(base, [], ENTRIES), base)
})

test('cascade: changing a winner clears the path the old player was carrying', () => {
  const base = { 101: 2, 201: 2 }
  const next = computeNextPicks(base, 101, 1, MATCHES)
  assert.equal(next[101], 1)
  assert.equal(next[201], null, 'the final’s pick of 2 is cleared, not left dangling')
})

test('cascade: a downstream pick on somebody else is left alone', () => {
  const base = { 101: 2, 201: 3 }
  const next = computeNextPicks(base, 101, 1, MATCHES)
  assert.equal(next[201], 3)
})

test('cascade: re-picking the same player changes nothing downstream', () => {
  const base = { 101: 2, 201: 2 }
  const next = computeNextPicks(base, 101, 2, MATCHES)
  assert.equal(next[201], 2)
})

test('cascade: it walks the WHOLE path, not just the next round', () => {
  // Eight entrants: three rounds, so a first-round change has two rounds above it.
  const mk = (id, r, n, p1, p2) => ({
    id, round_number: r, match_number: n,
    player1: p1 ? { id: p1 } : null, player2: p2 ? { id: p2 } : null,
  })
  const ms = [
    mk(1, 1, 1, 11, 12), mk(2, 1, 2, 13, 14), mk(3, 1, 3, 15, 16), mk(4, 1, 4, 17, 18),
    mk(5, 2, 1), mk(6, 2, 2), mk(7, 3, 1),
  ]
  const base = { 1: 11, 5: 11, 7: 11 }
  const next = computeNextPicks(base, 1, 12, ms)
  assert.equal(next[5], null)
  assert.equal(next[7], null, 'two rounds up is still downstream')
})

test('in play: a change to a frozen match is refused, an unchanged one is not', () => {
  const locked = new Set([201])
  assert.equal(blockedByLive({ 201: 1 }, { 201: 2 }, locked), true)
  assert.equal(blockedByLive({ 201: 1 }, { 201: 1, 101: 2 }, locked), false)
  assert.equal(blockedByLive({ 101: 1 }, { 101: 2 }, locked), false)
  assert.equal(blockedByLive({ 201: 1 }, { 201: 2 }, new Set()), false)
})

test('in play: clearing a frozen match counts as a change', () => {
  assert.equal(blockedByLive({ 201: 1 }, { 201: null }, new Set([201])), true)
})

test('rows in, rows out: a null winner is the same as no row', () => {
  const picks = picksFromRows([
    { match_id: 101, predicted_winner_id: 2 },
    { match_id: 201, predicted_winner_id: null },
  ])
  assert.deepEqual(picks, { 101: 2 })
  const map = picksMap(picks)
  assert.equal(map.get(101), 2, 'keyed on a NUMBER, which is what the bracket looks up with')
})

test('a champion is a pick in the last round that holds one', () => {
  assert.equal(namesChampion({ 101: 1 }, MATCHES), false)
  assert.equal(namesChampion({ 201: 1 }, MATCHES), true)
  assert.equal(namesChampion({}, MATCHES), false)
  assert.equal(namesChampion({ 201: 1 }, []), false)
})
