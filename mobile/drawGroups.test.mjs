import { test } from 'node:test'
import assert from 'node:assert/strict'
import { groupDrawsByStatus, showGroupHeadings } from './drawGroups.js'

const SECTIONS = { 1: 'open', 2: 'active', 3: 'open', 4: 'lastweek' }
const sectionOf = d => SECTIONS[d.id] ?? null
const ids = g => g.draws.map(d => d.id)
const draws = [{ id: 2 }, { id: 1 }, { id: 3 }]

test('open comes first, then active — the dashboard’s order, not the list’s', () => {
  const got = groupDrawsByStatus(draws, sectionOf)
  assert.deepEqual(got.map(g => g.title), ['Open', 'Active'])
  assert.deepEqual(ids(got[0]), [1, 3], 'the rows keep the order they arrived in')
  assert.deepEqual(ids(got[1]), [2])
})

test('an empty group is dropped, not drawn as a heading over nothing', () => {
  const got = groupDrawsByStatus([{ id: 2 }], sectionOf)
  assert.deepEqual(got.map(g => g.title), ['Active'])
})

test('a status nobody planned for still reaches the reader', () => {
  // The sheet is fed a list already filtered to open/active, so this cannot
  // happen today — but a draw must never vanish from a chooser.
  const got = groupDrawsByStatus([{ id: 1 }, { id: 4 }], sectionOf)
  assert.deepEqual(got.map(g => g.title), ['Open', 'Other'])
  assert.deepEqual(ids(got[1]), [4])
})

test('nothing in, nothing out', () => {
  assert.deepEqual(groupDrawsByStatus([], sectionOf), [])
  assert.deepEqual(groupDrawsByStatus(null, sectionOf), [])
  // A caller that has no section function must not crash the sheet: every row
  // falls through to the trailing group.
  assert.deepEqual(groupDrawsByStatus([{ id: 1 }]).map(g => g.title), ['Other'])
})

test('headings appear only once there are two groups to tell apart', () => {
  assert.equal(showGroupHeadings(groupDrawsByStatus(draws, sectionOf)), true)
  assert.equal(showGroupHeadings(groupDrawsByStatus([{ id: 1 }], sectionOf)), false)
  assert.equal(showGroupHeadings([]), false)
  assert.equal(showGroupHeadings(undefined), false)
})
