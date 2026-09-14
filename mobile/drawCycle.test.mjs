import { test } from 'node:test'
import assert from 'node:assert/strict'
import { cycleOrder, nextLiveDraw } from './drawCycle.js'

const d = (id, tid, gender, start, name) =>
  ({ id, tournament_id: tid, gender, start_date: start, name })

// Two tournaments, one of them combined: the shape the button exists for.
const GUADALAJARA = d(142, 35, 'F', '2026-09-13', 'Guadalajara Open')
const SP = d(143, 80, 'F', '2026-09-14', 'SP Open')
const USO_M = d(77, 92, 'M', '2026-08-24', 'US Open')
const USO_F = d(78, 92, 'F', '2026-08-24', 'US Open')

test('the order is fixed: date, then men before women, then name', () => {
  const got = cycleOrder([SP, USO_F, GUADALAJARA, USO_M]).map(x => x.id)
  assert.deepEqual(got, [77, 78, 142, 143])
  // Same answer whatever the API happened to list first.
  assert.deepEqual(cycleOrder([GUADALAJARA, USO_M, SP, USO_F]).map(x => x.id), got)
})

test('steps to the next live draw and wraps', () => {
  const live = [USO_M, USO_F, GUADALAJARA, SP]
  assert.equal(nextLiveDraw(live, USO_M).id, 78)
  assert.equal(nextLiveDraw(live, USO_F).id, 142)
  assert.equal(nextLiveDraw(live, SP).id, 77, 'wraps to the top')
})

test('no button when there is nowhere to go', () => {
  assert.equal(nextLiveDraw([GUADALAJARA], GUADALAJARA), null)
  assert.equal(nextLiveDraw([], GUADALAJARA), null)
  assert.equal(nextLiveDraw([USO_M, USO_F], null), null)
})

test('no button when every live draw is this same tournament', () => {
  // The header's tour switch already crosses between these two, and two
  // controls doing one thing is worse than one.
  assert.equal(nextLiveDraw([USO_M, USO_F], USO_M), null)
  assert.equal(nextLiveDraw([USO_M, USO_F], USO_F), null)
})

test('an old draw opened from history starts the cycle at the top', () => {
  const old = d(9, 12, 'M', '2026-02-01', 'Rotterdam')
  assert.equal(nextLiveDraw([GUADALAJARA, SP], old).id, 142)
})
