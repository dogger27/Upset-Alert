import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  GROUP_TONE, STATUS_GROUPS, groupDrawsByStatus, sectionOfMany, showGroupHeadings,
} from './drawGroups.js'

const SECTIONS = { 1: 'open', 2: 'active', 3: 'open', 4: 'lastweek', 5: 'upcoming' }
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

test('next week is its own group, after the two that are live', () => {
  const got = groupDrawsByStatus([{ id: 5 }, { id: 2 }, { id: 1 }], sectionOf)
  assert.deepEqual(got.map(g => g.title), ['Open', 'Active', 'Next week'])
})

test('a status nobody planned for still reaches the reader', () => {
  // Both callers pass lists already confined to those sections, so this
  // cannot happen today — but a draw must never vanish from a list.
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


// ── A card holding two draws ────────────────────────────────────────────────

test('a combined card takes the more OPEN of its two halves', () => {
  // The men's draw is under way while the women's still takes picks: the card
  // is one the reader can act on, so it belongs under Open.
  assert.equal(sectionOfMany(['active', 'open']), 'open')
  assert.equal(sectionOfMany(['open', 'active']), 'open')
  assert.equal(sectionOfMany(['active', 'upcoming']), 'active')
  // One half only, and the ordinary single-draw case.
  assert.equal(sectionOfMany(['upcoming']), 'upcoming')
})

test('a card in no group at all says so, rather than guessing', () => {
  assert.equal(sectionOfMany(['lastweek']), null)
  assert.equal(sectionOfMany([]), null)
  assert.equal(sectionOfMany(null), null)
  assert.equal(sectionOfMany([null, undefined]), null)
  // …and one live half still places a card whose other half has no section.
  assert.equal(sectionOfMany([null, 'active']), 'active')
})

test('every group has a tone, and it names a real token', () => {
  // The colour lives here as a token NAME so this module needs no theme
  // import; the screens resolve it against C. A group with no tone falls back
  // to muted, which is quiet but never invisible.
  for (const g of STATUS_GROUPS) {
    assert.ok(GROUP_TONE[g.key], `${g.key} has no tone`)
  }
})
