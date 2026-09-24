/* node dayLabels.test.mjs */
import assert from 'node:assert/strict'
import { dayLabels, dayWords, msToMidnight, relativeDayWord, todayIso } from './dayLabels.js'

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
assert.deepEqual(dayLabels(['2026-09-12'], '2026-09-13'),
                 [{ date: '2026-09-12', label: 'Q1', isToday: false }])

/* TODAY IS FLAGGED, because the strip draws a "T" for it where every other day
   is a dot (owner, 2026-09-21). One day at most, and never by accident: the
   flag is an exact date match, so a strip whose days do not include today —
   last week's schedule, next week's — draws no T at all rather than guessing
   which dot deserves one. */
{
  const week = ['2026-09-20', '2026-09-21', '2026-09-22']
  assert.deepEqual(dayLabels(week, '2026-09-20', '2026-09-21').map(d => d.isToday),
                   [false, true, false])
  // Exactly one, wherever it falls.
  assert.equal(dayLabels(week, '2026-09-20', '2026-09-21').filter(d => d.isToday).length, 1)
  assert.deepEqual(dayLabels(week, '2026-09-20', '2026-09-20').map(d => d.isToday),
                   [true, false, false])
  // A day that is not in the strip flags nothing; so does no day at all.
  assert.deepEqual(dayLabels(week, '2026-09-20', '2026-10-05').map(d => d.isToday),
                   [false, false, false])
  assert.deepEqual(dayLabels(week, '2026-09-20').map(d => d.isToday), [false, false, false])
  assert.deepEqual(dayLabels(week, '2026-09-20', null).map(d => d.isToday), [false, false, false])
  // The LABELS are untouched by any of it — they are what the accessibility
  // label still reads out now the glyphs are gone.
  assert.deepEqual(dayLabels(week, '2026-09-21', '2026-09-21').map(d => d.label),
                   ['Q1', '1', '2'])
}


// The slot's word: yesterday, today and TOMORROW — the three days a reader has
// a word for (owner, 2026-09-20; tomorrow used to show its date) — and nothing
// for any other day. Across a month end and a year end, since it is day
// arithmetic rather than string maths.
assert.equal(relativeDayWord('2026-09-17', '2026-09-17'), 'Today')
assert.equal(relativeDayWord('2026-09-16', '2026-09-17'), 'Yday')
assert.equal(relativeDayWord('2026-09-18', '2026-09-17'), 'Tmrw')
assert.equal(relativeDayWord('2026-09-15', '2026-09-17'), null)
assert.equal(relativeDayWord('2026-09-19', '2026-09-17'), null)     // two days out is a date
assert.equal(relativeDayWord('2026-08-31', '2026-09-01'), 'Yday')
assert.equal(relativeDayWord('2025-12-31', '2026-01-01'), 'Yday')
assert.equal(relativeDayWord(undefined, '2026-09-17'), null)

console.log('ok — dayLabels')

// The words hold over a month end, a year end and a leap day. The shift is
// done at NOON UTC so a daylight change cannot push the result across the
// date line.
assert.equal(relativeDayWord('2026-10-01', '2026-09-30'), 'Tmrw')
assert.equal(relativeDayWord('2027-01-01', '2026-12-31'), 'Tmrw')
assert.equal(relativeDayWord('2028-02-29', '2028-02-28'), 'Tmrw')
assert.equal(relativeDayWord('2028-03-01', '2028-02-29'), 'Tmrw')
assert.equal(relativeDayWord('2026-09-21', null), null)


/* ── THE RIGHT SLOT'S WORDS, so the rule beside it stays put ─────────────
 *
 * The slot was sized by whatever word was in it, so the line down its left
 * edge slid sideways as the reader swiped from "Today" to "Sep 24" and back
 * (owner, 2026-09-22). It is now sized to the widest word the CURRENT range
 * can show, which moves only when the range does.
 *
 * This lists the candidates; the screen measures them and adds slack, because
 * only the font knows which is widest and the advance tables carry no kerning.
 * "Sep 20" wrapped onto two lines when the slot was sized to the exact
 * measurement — 45.6pt of text in 46pt of room.
 */
const SHORT = iso => {
  // 'Sep 15' / 'Sep 5', without leaning on the test runner's locale.
  const [, m, d] = iso.split('-')
  return `${['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][+m]} ${+d}`
}

// A range around today: the three words, in the order the days run.
assert.deepEqual(dayWords(['2026-09-21', '2026-09-22', '2026-09-23'], '2026-09-22', SHORT),
                 ['Yday', 'Today', 'Tmrw'])

// A range with no word in it is all dates.
assert.deepEqual(dayWords(['2026-09-05', '2026-09-15'], '2026-10-01', SHORT), ['Sep 5', 'Sep 15'])

/* THE CHOSEN DAY COUNTS EVEN WHEN IT HAS NO SHEET — the slot shows the day
   the reader is on, and a day with no matches still says which day it is. */
assert.deepEqual(dayWords(['2026-09-05'], '2026-10-01', SHORT, '2026-09-15'), ['Sep 5', 'Sep 15'])
assert.deepEqual(dayWords([], '2026-09-22', SHORT, '2026-09-22'), ['Today'])

// The active day is already in the range: named once, not twice — a duplicate
// would not change the widest, but it would make the list lie about the range.
assert.deepEqual(dayWords(['2026-09-22'], '2026-09-22', SHORT, '2026-09-22'), ['Today'])

// Nothing to show, nothing to size by: the caller leaves the slot to grow.
assert.deepEqual(dayWords([], '2026-09-22', SHORT), [])
assert.deepEqual(dayWords(null, '2026-09-22', SHORT), [])
assert.deepEqual(dayWords([null, undefined], '2026-09-22', SHORT), [])

/* IT DOES NOT MOVE ACROSS THE RANGE. Every day of one range must see the same
   candidates, or the slot changes width on a swipe — which is the whole bug. */
{
  const range = ['2026-09-20', '2026-09-21', '2026-09-22', '2026-09-23', '2026-09-24']
  const answers = new Set(range.map(d => dayWords(range, '2026-09-22', SHORT, d).join('|')))
  assert.equal(answers.size, 1, `the slot changed width mid-range: ${[...answers]}`)
}

// Today is the DEVICE calendar date, and midnight is the next local one.
{
  const late = new Date(2026, 8, 23, 23, 59, 30)   // local 23:59:30
  assert.equal(todayIso(late), '2026-09-23')
  assert.equal(msToMidnight(late), 31000)           // 30s + 1s margin
  assert.equal(todayIso(new Date(late.getTime() + msToMidnight(late))), '2026-09-24')
}
