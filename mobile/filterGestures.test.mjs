/*
 * Hold a tournament to show only that one.
 *
 *     node filterGestures.test.mjs
 *
 * Owner, 2026-09-21: "Make it so a LONG hold on any draw will display ONLY
 * that draw and deselect all the others." Getting down to one tournament used
 * to mean tapping every OTHER pill off — five taps on a five-event day, one of
 * them easy to miss.
 *
 * A source check, because the thing that can break is which props are on a
 * Pressable and which Set is handed to the store. There is no return value to
 * inspect, and a renderer would be testing React rather than the wiring. The
 * two lists are checked TOGETHER on purpose: they are the same tournaments,
 * and a gesture that works on one and not the other is a gesture nobody
 * trusts.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = p => readFileSync(new URL(p, import.meta.url), 'utf8')
const PILLS = read('./app/(tabs)/schedule.jsx')
const SHEET = read('./app/(tabs)/_layout.jsx')
const STORE = read('./scheduleFilter.js')

/* The delay the schedule rows' own hold already uses. One speed, or the app
   asks for a long press at two and the slower one reads as a dead control. */
const DELAY = 320

test('both lists decide a hold with the SAME rule', () => {
  /* The rule is scheduleRows.holdSelection — isolate, or show everything when
     the held one is already alone — and it is tested on its own in
     scheduleRows.test.mjs. What matters here is that neither list reimplements
     it: two copies of "what a hold means" is how the pills and the sheet come
     to disagree, which is the thing that makes a gesture untrustworthy. */
  assert.match(PILLS, /onLongPress=\{\(\) => setScheduleTournaments\(holdSelection\(/)
  assert.match(SHEET, /onLongPress=\{\(\) => setDraft\(holdSelection\(/)
  for (const [what, src] of [['pills', PILLS], ['sheet', SHEET]])
    assert.doesNotMatch(src, /onLongPress=\{\(\) => \w+\(new Set\(\[t\.id\]\)\)\}/,
      `${what} builds its own one-id set instead of asking holdSelection`)
  // A hold that toggles is the tap it was meant to replace.
  assert.doesNotMatch(PILLS, /onLongPress=\{\(\) => toggleEvent/)
})

test('the sheet TICKS every row for “all”, rather than clearing them', () => {
  /* holdSelection answers null for everything, which is the store's word and
     wrong for a sheet that shows its answer as checkboxes — clearing them all
     to mean "everything" is the one thing its own Clear button already warns
     is confusing. */
  assert.match(SHEET, /\?\?\s*new Set\(choosable\.map\(/)
})

test('both hold at the same speed as the rest of the app', () => {
  for (const [what, src] of [['pills', PILLS], ['sheet', SHEET]]) {
    const delays = [...src.matchAll(/delayLongPress=\{(\d+)\}/g)].map(m => Number(m[1]))
    assert.ok(delays.length > 0, `${what} sets no delayLongPress`)
    assert.ok(delays.every(d => d === DELAY),
      `${what} holds at ${delays.join('/')}ms, not ${DELAY}ms`)
  }
})

test('“only this” can never collapse into “everything”', () => {
  /* The store's own word for "every tournament" is null, and it maps an EMPTY
     set onto it. A one-element set must therefore survive untouched — if that
     rule ever inverted, holding a pill would show the whole day, which is the
     exact opposite of what was asked. */
  assert.match(STORE, /next && next\.size \? new Set\(next\) : null/,
    'the store no longer keeps a non-empty set as given')
})

test('the hint says what the hold will actually do', () => {
  /* A hold with no hint is invisible to anyone using a screen reader, and
     near-invisible to everyone else. Now that the gesture has two outcomes the
     hint has to follow it, or it tells half the users the wrong one. */
  for (const [what, src, verb] of [['pills', PILLS, 'show'], ['sheet', SHEET, 'choose']]) {
    assert.match(src, new RegExp(`Hold to ${verb} only this tournament`), what)
    assert.match(src, new RegExp(`Hold to ${verb} every tournament`), what)
    assert.match(src, /size === 1/, `${what} hint does not branch on the lone selection`)
  }
})
