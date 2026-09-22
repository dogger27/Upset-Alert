// node --test courtGroups.test.mjs
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { courtGroups } from './courtGroups.js'

const row = (id, tournament_id, tournament_name, court, court_order, seeds = [], discipline = 'singles') =>
  ({ id, tournament_id, tournament_name, court, court_order, discipline, players: seeds.map(seed => ({ seed })) })

test('one tournament: courts by best seed, then load, then name — and it is still named', () => {
  const g = courtGroups([
    row(1, 80, 'SP Open', 'Quadra 1', 1, [null, 12]),
    row(2, 80, 'SP Open', 'Quadra Central', 2, [3, null]),
    row(3, 80, 'SP Open', 'Quadra Central', 1, [null, null]),
    row(4, 80, 'SP Open', 'Quadra 2', 1, [null, null]),
    row(5, 80, 'SP Open', 'Quadra 2', 2, [null, null]),
  ])
  /* THE HEADING IS THERE WITH ONE TOURNAMENT TOO (owner, 2026-09-20). It used
     to be dropped as saying nothing; it says WHICH, and "Quadra Central"
     belongs to any tournament you like. */
  assert.deepEqual(g.map(x => [x.court, x.title, x.list.map(e => e.id)]), [
    ['Quadra Central', 'SP Open', [3, 2]],
    ['Quadra 1', null, [1]],
    ['Quadra 2', null, [4, 5]],
  ])
  // The tournament is in every key: two events on a day can both have a
  // "Court 1", and a shared key would collide them into one group.
  assert.deepEqual(g.map(x => x.key), ['80 Quadra Central', '80 Quadra 1', '80 Quadra 2'])
})

test('two tournaments: grouped by tournament in name order, the first court of each carries the heading', () => {
  const g = courtGroups([
    row(1, 80, 'SP Open', 'Quadra 1', 1, [null, 12]),
    row(2, 35, 'Guadalajara', 'Estadio', 1, [1, null]),
    row(3, 80, 'SP Open', 'Quadra Central', 1, [3, null]),
    row(4, 35, 'Guadalajara', 'Cancha 2', 1, [null, null]),
  ])
  assert.deepEqual(g.map(x => [x.title, x.court]), [
    ['Guadalajara', 'Estadio'], [null, 'Cancha 2'],
    ['SP Open', 'Quadra Central'], [null, 'Quadra 1'],
  ])
  assert.equal(new Set(g.map(x => x.key)).size, 4)
})

test('a doubles seed does not rank a court; a row with no court is Court TBA', () => {
  const g = courtGroups([
    row(1, 80, 'SP Open', 'Quadra 2', 1, [1, null], 'doubles'),
    row(2, 80, 'SP Open', 'Quadra 1', 1, [8, null]),
    row(3, 80, 'SP Open', null, 1, [null, null]),
  ])
  assert.deepEqual(g.map(x => x.court), ['Quadra 1', 'Court TBA', 'Quadra 2'])
})

test('two events sharing a court name stay two groups', () => {
  const g = courtGroups([
    row(1, 80, 'SP Open', 'Court 1', 1, [5, null]),
    row(2, 35, 'Guadalajara', 'Court 1', 1, [2, null]),
  ])
  assert.equal(g.length, 2, 'one group each, not one group of both')
  assert.deepEqual(g.map(x => [x.title, x.court]), [
    ['Guadalajara', 'Court 1'], ['SP Open', 'Court 1'],
  ])
  assert.equal(new Set(g.map(x => x.key)).size, 2)
})

test('a qualifying seed ranks below every main-draw seed (Chengdu 2026-09-23)', () => {
  const q = (id, court, court_order, seeds) =>
    ({ ...row(id, 17, 'Chengdu Open', court, court_order, seeds), stage: 'qualifying' })
  const g = courtGroups([
    q(1, 'COURT 1', 1, [2, 7]),
    q(2, 'COURT 1', 2, [1, 8]),
    q(3, 'COURT 2', 1, [3, 6]),
    row(4, 17, 'Chengdu Open', 'CENTER COURT', 1, [8, null]),
    row(5, 17, 'Chengdu Open', 'CENTER COURT', 2, [null, null]),
    row(6, 17, 'Chengdu Open', 'COURT 3', 1, [null, null]),
  ])
  /* The sheet's order: the show court with the main-draw [8] first, then the
     qualifying courts by THEIR seeds, then an unseeded main-draw court. */
  assert.deepEqual(g.map(x => x.court), ['CENTER COURT', 'COURT 1', 'COURT 2', 'COURT 3'])
})
