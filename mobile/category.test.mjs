/*
 * Tour and tier words, and which tour an event belongs to.
 *
 *   node category.test.mjs
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { categoryShort, eventTour, tourLabel } from './category.js'

/* ── eventTour ────────────────────────────────────────────────────────────
 * The Schedule screen's tournament pills are tinted by tour — blue ATP, pink
 * WTA (owner, 2026-09-21) — so this decides a colour, and getting it wrong
 * paints a women's event blue.
 */
test('a single-tour event answers its own tour', () => {
  assert.equal(eventTour(['M']), 'ATP')
  assert.equal(eventTour(['F']), 'WTA')
  // tournamentsOf sorts men first, but a caller must not depend on that.
  assert.equal(eventTour(['F', 'F']), 'WTA')
})

test('a combined week belongs to neither tour', () => {
  // The case the caller needs a neutral for. NOT a blend — see TOUR.X.
  assert.equal(eventTour(['M', 'F']), null)
  assert.equal(eventTour(['F', 'M']), null)
})

test('nothing to go on is not a tour', () => {
  // An event mid-load, or a draw whose gender never arrived: null, so the
  // pill stays neutral rather than defaulting to ATP and mislabelling half
  // the calendar by coin flip.
  assert.equal(eventTour([]), null)
  assert.equal(eventTour(null), null)
  assert.equal(eventTour(undefined), null)
  assert.equal(eventTour([null, undefined]), null)
})

/* ── the words, which the pills' labels and headings share ─────────────── */
test('the tier word is the short one', () => {
  assert.equal(categoryShort('Grand Slam'), 'GS')
  assert.equal(categoryShort('WTA 1000'), '1000')
  assert.equal(categoryShort('ATP 500'), '500')
  assert.equal(categoryShort('ATP 250'), '250')
})

test('the tour label names the tour, never the gender', () => {
  assert.equal(tourLabel({ gender: 'M', category: 'ATP 1000' }), 'ATP 1000')
  assert.equal(tourLabel({ gender: 'F', category: 'WTA 250' }), 'WTA 250')
})
