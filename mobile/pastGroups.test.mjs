/* node pastGroups.test.mjs */
import assert from 'node:assert/strict'
import { groupPastDay, roundRank } from './pastGroups.js'

// Qualifying first, then the draw from its first round to the final.
const order = ['Q1', 'Q2', 'Q3', 'R128', 'R64', 'R32', 'R16', 'QF', 'SF', 'F'].map(roundRank)
assert.deepEqual(order, [...order].sort((a, b) => a - b))
assert.ok(roundRank('Quarterfinals') === roundRank('QF'))
assert.ok(roundRank('who knows') > roundRank('F'))

const E = (id, tournament_name, discipline, round_label, tournament_id = 1) => ({ id, tournament_name, tournament_id, discipline, round_label })
const day = [
  E(1, 'SP Open', 'doubles', 'R16', 97),
  E(2, 'SP Open', 'singles', 'QF', 97),
  E(3, 'Guadalajara Open', 'singles', 'R16', 35),
  E(4, 'SP Open', 'singles', 'R16', 97),
  E(5, 'SP Open', 'singles', 'R16', 97),
  E(6, 'Guadalajara Open', 'doubles', 'QF', 35),
  E(7, 'Guadalajara Open', 'singles', 'QF', 35),
]

// Two tournaments: grouped by tournament (alphabetical), singles before doubles, rounds in order.
let g = groupPastDay(day, { byTournament: true })
assert.deepEqual(g.map(x => [x.tournament, x.discipline, x.round, x.list.map(e => e.id)]), [
  ['Guadalajara Open', 'Singles', 'R16', [3]],
  ['Guadalajara Open', 'Singles', 'QF', [7]],
  ['Guadalajara Open', 'Doubles', 'QF', [6]],
  ['SP Open', 'Singles', 'R16', [4, 5]],
  ['SP Open', 'Singles', 'QF', [2]],
  ['SP Open', 'Doubles', 'R16', [1]],
])
// Only the first group of a tournament carries its heading.
assert.deepEqual(g.map(x => x.first), [true, false, false, true, false, false])

// One tournament showing: no tournament level at all.
g = groupPastDay(day.filter(e => e.tournament_id === 97))
assert.deepEqual(g.map(x => [x.tournament, x.discipline, x.round]), [
  [null, 'Singles', 'R16'], [null, 'Singles', 'QF'], [null, 'Doubles', 'R16'],
])
assert.deepEqual(g.map(x => x.first), [false, false, false])

// Rows inside a group keep the order they arrived in.
assert.deepEqual(g[0].list.map(e => e.id), [4, 5])
assert.deepEqual(groupPastDay([]), [])
console.log('ok — pastGroups')
