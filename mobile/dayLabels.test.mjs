/* node dayLabels.test.mjs */
import assert from 'node:assert/strict'
import { dayLabels, relativeDayWord } from './dayLabels.js'

const labels = (dates, main) => dayLabels(dates, main).map(d => d.label)

// Nothing published, nothing labelled.
assert.deepEqual(labels([], null), [])

// No qualifying: day 1 is the first sheet.
assert.deepEqual(labels(['2026-09-15', '2026-09-16', '2026-09-17'], '2026-09-15'), ['1', '2', '3'])

// Two qualifying days, a blank day between them and day 1 — not in the list,
// so not counted — then the main draw.
assert.deepEqual(
  labels(['2026-09-12', '2026-09-13', '2026-09-15', '2026-09-16'], '2026-09-15'),
  ['Q1', 'Q2', '1', '2'])

// Qualifying finishing ON day 1 (Guadalajara): the shared day is day 1.
assert.deepEqual(labels(['2026-09-12', '2026-09-13', '2026-09-14'], '2026-09-13'), ['Q1', '1', '2'])

// A Slam: five qualifying days (three rounds), then fifteen.
const iso = (y, m, d) => new Date(Date.UTC(y, m - 1, d)).toISOString().slice(0, 10)
const uso = [...Array.from({ length: 5 }, (_, i) => iso(2026, 8, 24 + i)),   // Aug 24–28
             ...Array.from({ length: 15 }, (_, i) => iso(2026, 8, 30 + i))]  // Aug 30 – Sep 13
const usoLabels = labels(uso, '2026-08-30')
assert.deepEqual(usoLabels.slice(0, 6), ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', '1'])
assert.equal(usoLabels.length, 20)
assert.equal(usoLabels[19], '15')

// Only qualifying sheets so far: every day is a Q day.
assert.deepEqual(labels(['2026-09-12', '2026-09-13'], '2026-09-15'), ['Q1', 'Q2'])

// Day 1 not known yet: numbered from 1, no Q days.
assert.deepEqual(labels(['2026-09-12', '2026-09-13'], null), ['1', '2'])
assert.deepEqual(labels(['2026-09-12', '2026-09-13'], undefined), ['1', '2'])

// The date rides along with its label.
assert.deepEqual(dayLabels(['2026-09-12'], '2026-09-13'), [{ date: '2026-09-12', label: 'Q1' }])


// The slot's word: today, yesterday, and nothing for any other day — across a
// month end and a year end, since it is day arithmetic, not string maths.
assert.equal(relativeDayWord('2026-09-17', '2026-09-17'), 'Today')
assert.equal(relativeDayWord('2026-09-16', '2026-09-17'), 'Yester.')
assert.equal(relativeDayWord('2026-09-15', '2026-09-17'), null)
assert.equal(relativeDayWord('2026-09-18', '2026-09-17'), null)     // tomorrow has no word
assert.equal(relativeDayWord('2026-08-31', '2026-09-01'), 'Yester.')
assert.equal(relativeDayWord('2025-12-31', '2026-01-01'), 'Yester.')
assert.equal(relativeDayWord(undefined, '2026-09-17'), null)

console.log('ok — dayLabels')
