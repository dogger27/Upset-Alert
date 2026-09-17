// node --test courtGroups.test.mjs
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { courtGroups } from './courtGroups.js'

const row = (id, tournament_id, tournament_name, court, court_order, seeds = [], discipline = 'singles') =>
  ({ id, tournament_id, tournament_name, court, court_order, discipline, players: seeds.map(seed => ({ seed })) })

test('one tournament: courts by best seed, then load, then name; no headings', () => {
  const g = courtGroups([
    row(1, 80, 'SP Open', 'Quadra 1', 1, [null, 12]),
    row(2, 80, 'SP Open', 'Quadra Central', 2, [3, null]),
    row(3, 80, 'SP Open', 'Quadra Central', 1, [null, null]),
    row(4, 80, 'SP Open', 'Quadra 2', 1, [null, null]),
    row(5, 80, 'SP Open', 'Quadra 2', 2, [null, null]),
  ])
  assert.deepEqual(g.map(x => [x.court, x.title, x.list.map(e => e.id)]), [
    ['Quadra Central', null, [3, 2]],
    ['Quadra 1', null, [1]],
    ['Quadra 2', null, [4, 5]],
  ])
  assert.deepEqual(g.map(x => x.key), ['Quadra Central', 'Quadra 1', 'Quadra 2'])
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
