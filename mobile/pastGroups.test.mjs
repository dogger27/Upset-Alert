/* node pastGroups.test.mjs */
import assert from 'node:assert/strict'
import { eventRank, eventRankFrom, groupPastDay, matchStrength, roundRank, sortByStrength, tierPoints } from './pastGroups.js'

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

// A dual-gender day: tournament, then tour (ATP before WTA), then round.
const T = (id, tour, round_label, players = []) => ({ id, tournament_name: 'US Open', tournament_id: 92, tour, discipline: 'singles', round_label, players })
const slam = [T(1, 'WTA', 'R128'), T(2, 'ATP', 'R64'), T(3, 'ATP', 'R128'), T(4, 'WTA', 'R64')]
g = groupPastDay(slam, { byTour: true })
assert.deepEqual(g.map(x => [x.tour, x.round, x.list.map(e => e.id)]), [
  ['ATP', 'R128', [3]], ['ATP', 'R64', [2]], ['WTA', 'R128', [1]], ['WTA', 'R64', [4]],
])
// Without the tour level the same day is rounds alone.
assert.deepEqual(groupPastDay(slam).map(x => [x.tour, x.round]), [[null, 'R128'], [null, 'R64']])

// Inside a group: seeds first (lowest number strongest), then rankings, then the day's order.
const P = (side, seed, draw_rank) => ({ side, seed, draw_rank })
const strong = [
  T(10, 'ATP', 'R128', [P('a', null, 80), P('b', null, 95)]),      // unseeded, best rank 80
  T(11, 'ATP', 'R128', [P('a', 12, 15), P('b', null, 60)]),        // seed 12
  T(12, 'ATP', 'R128', [P('a', null, 40), P('b', null, 41)]),      // unseeded, best rank 40
  T(13, 'ATP', 'R128', [P('a', null, 3), P('b', 1, 1)]),           // seed 1
  T(14, 'ATP', 'R128', [P('a', null, null), P('b', null, null)]),  // nothing known
]
assert.deepEqual(sortByStrength(strong).map(e => e.id), [13, 11, 12, 10, 14])
assert.deepEqual(matchStrength(strong[3]), [1, 1])
assert.deepEqual(matchStrength(strong[4]), [Infinity, Infinity])
assert.deepEqual(groupPastDay(strong)[0].list.map(e => e.id), [13, 11, 12, 10, 14])

/* ── THE BIGGER EVENT FIRST, ATP BEFORE WTA (owner, 2026-09-23) ────────── */

// A tier is its ranking points, which is what the draw-filter bar prints.
assert.equal(tierPoints('Grand Slam'), 2000)
assert.equal(tierPoints('ATP 1000'), 1000)
assert.equal(tierPoints('WTA 125'), 125)
assert.equal(tierPoints('ATP Finals'), 1500, 'the finale has no number of its own')
assert.equal(tierPoints('United Cup'), 0)
assert.equal(tierPoints(null), 0)

// A combined week is as big as its bigger half, and counts as ATP.
assert.deepEqual(eventRank([{ gender: 'F', category: 'WTA 1000' },
                            { gender: 'M', category: 'ATP 500' }]), [-1000, 0])
assert.deepEqual(eventRank([{ gender: 'F', category: 'WTA 500' }]), [-500, 1])
assert.deepEqual(eventRank([]), [0, 1], 'nothing known is not something big')

const EV = (id, name, ...stamps) => ({ id, name, stamps })
const week = [
  EV(1, 'Almaty Open', { gender: 'M', category: 'ATP 250' }),
  EV(2, 'US Open', { gender: 'M', category: 'Grand Slam' }, { gender: 'F', category: 'Grand Slam' }),
  EV(3, 'Korea Open', { gender: 'F', category: 'WTA 500' }),
  EV(4, 'Japan Open', { gender: 'M', category: 'ATP 500' }),
  EV(5, 'Guangzhou Open', { gender: 'F', category: 'WTA 250' }),
]
const rank = eventRankFrom(week)
const rows = [
  E(20, 'Almaty Open', 'singles', 'QF', 1),
  E(21, 'US Open', 'singles', 'QF', 2),
  E(22, 'Korea Open', 'singles', 'QF', 3),
  E(23, 'Japan Open', 'singles', 'QF', 4),
  E(24, 'Guangzhou Open', 'singles', 'QF', 5),
]
const names = groupPastDay(rows, { byTournament: true, eventRank: rank }).map(g => g.tournament)
assert.deepEqual(names, ['US Open', 'Japan Open', 'Korea Open', 'Almaty Open', 'Guangzhou Open'],
  'the Slam leads; the two 500s are next with ATP first; the two 250s last, ATP first')

// An event the day holds no stamp for sorts last, not first.
const withUnknown = groupPastDay(
  [...rows, E(25, 'Mystery Open', 'singles', 'QF', 99)],
  { byTournament: true, eventRank: rank }).map(g => g.tournament)
assert.equal(withUnknown[withUnknown.length - 1], 'Mystery Open')

// Without a rank, the old alphabetical order stands — one caller, one change.
assert.deepEqual(groupPastDay(rows, { byTournament: true }).map(g => g.tournament),
  ['Almaty Open', 'Guangzhou Open', 'Japan Open', 'Korea Open', 'US Open'])

console.log('ok — pastGroups')
