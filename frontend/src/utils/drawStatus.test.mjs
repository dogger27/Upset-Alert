/*
 * Which bucket a draw belongs in — Active, Last Week, Previous.
 *
 *   node src/utils/drawStatus.test.mjs
 *
 * WHY THIS SUITE EXISTS. The rule had no tests, and it went wrong in a way
 * nobody could have caught by reading it: 2026 Guadalajara finished on the
 * 19th and kept showing as Active for two days, because the cohort that
 * decides "still playing" was clustered by END DATE and SP Open — a
 * different event, a different country — ended a day later (owner,
 * 2026-09-21). The intent had always been the narrower one: a combined
 * event's men's final does not retire the event while the women's is on
 * court.
 *
 * The dates below are fixed relative to a stubbed "today", because a bucket
 * that depends on the real clock is a suite that fails at midnight Pacific.
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'

/* The module reads today's date through a cached Intl formatter. Freezing
   Date.now() is not enough — the cache would hold a real day from an earlier
   call — so the source is loaded with the formatter's timezone pinned and
   Date stubbed before the first import. */
const TODAY = '2026-09-21'
const src = readFileSync(new URL('./drawStatus.js', import.meta.url), 'utf8')
globalThis.Date = class extends Date {
  constructor(...args) {
    super(...(args.length ? args : [`${TODAY}T12:00:00Z`]))
  }

  static now() { return new Date(`${TODAY}T12:00:00Z`).getTime() }
}
const { computeCohortInfo, getDisplayStatus } =
  await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'))

let n = 0
let failures = 0
function check(name, fn) {
  try { fn(); n += 1; console.log(`  ok  ${name}`) }
  catch (e) {
    failures += 1
    console.log(`  FAIL ${name}\n      ${e.message}`)
    process.exitCode = 1
  }
}

const draw = (id, tournament_id, end_date, status) => ({ id, tournament_id, end_date, status })
const bucket = (list, id) => getDisplayStatus(list.find(t => t.id === id), computeCohortInfo(list))

// ── the rule the cohort exists for ─────────────────────────────────────────

check('a combined event keeps its finished half Active while the other plays', () => {
  // One tournament, two draws: the men's is done, the women's is on court.
  const list = [
    draw(1, 500, '2026-09-20', 'completed'),
    draw(2, 500, '2026-09-21', 'active'),
  ]
  assert.equal(bucket(list, 1), 'active')
  assert.equal(bucket(list, 2), 'active')
})

check('an event still running today holds its own finished draw', () => {
  // Nothing marked active, but the event's last day is today: Rule 3 keeps
  // the cohort Active until Pacific midnight.
  const list = [
    draw(1, 500, '2026-09-20', 'completed'),
    draw(2, 500, '2026-09-21', 'completed'),
  ]
  assert.equal(bucket(list, 1), 'active')
})

// ── the bug ───────────────────────────────────────────────────────────────

check('a DIFFERENT event ending a day later does not hold it Active', () => {
  // Guadalajara (finished the 19th) and SP Open (playing, ends the 21st):
  // one day apart at the time, which used to weld them into one cohort.
  const list = [
    draw(142, 900, '2026-09-19', 'completed'),
    draw(143, 901, '2026-09-20', 'active'),
  ]
  assert.notEqual(bucket(list, 142), 'active')
  assert.equal(bucket(list, 143), 'active')
})

check('nor does one ending the same day', () => {
  const list = [
    draw(142, 900, '2026-09-19', 'completed'),
    draw(143, 901, '2026-09-19', 'active'),
  ]
  assert.notEqual(bucket(list, 142), 'active')
})

check('one tournament row, two events months apart, do NOT move together', () => {
  /* Four tournament rows conflate an ATP and a WTA event that share a city's
     name but are played weeks or months apart. Hong Kong's ATP 250 was played
     in January and its WTA 250 is in November, under one row — and grouping by
     that row alone put the January event under ACTIVE in September, ten months
     after its final (owner, 2026-09-21: "WTF is going on???"). */
  const list = [
    draw(3, 41, '2026-01-11', 'completed'),     // ATP, played in January
    draw(155, 41, '2026-11-08', 'upcoming'),    // WTA, still to come
  ]
  assert.equal(bucket(list, 3), 'previous')
  assert.equal(bucket(list, 155), 'upcoming')
})

check('the same row IS one cohort when it is one week of play', () => {
  // The case the rule exists for, which the narrowing must not break.
  const list = [
    draw(1, 41, '2026-09-20', 'completed'),
    draw(2, 41, '2026-09-21', 'active'),
  ]
  assert.equal(bucket(list, 1), 'active')
})

// ── Last Week is still a WEEK, not one event ──────────────────────────────

check('a week of finished events lands in Last Week together', () => {
  // Three unrelated tournaments, ending within a day of each other, all done.
  const list = [
    draw(1, 900, '2026-09-19', 'completed'),
    draw(2, 901, '2026-09-20', 'completed'),
    draw(3, 902, '2026-09-20', 'completed'),
  ]
  for (const id of [1, 2, 3]) assert.equal(bucket(list, id), 'lastweek')
})

check('an earlier week is Previous, not Last Week', () => {
  const list = [
    draw(1, 800, '2026-09-13', 'completed'),   // the week before
    draw(2, 900, '2026-09-19', 'completed'),   // last week
    draw(3, 901, '2026-09-20', 'completed'),
  ]
  assert.equal(bucket(list, 1), 'previous')
  assert.equal(bucket(list, 2), 'lastweek')
  assert.equal(bucket(list, 3), 'lastweek')
})

check('a draw that has finished joins Last Week without waiting for its week', () => {
  /* THIS ASSERTION WAS REVERSED ON 2026-09-21, deliberately. It used to read
     `bucket(list, 1) === 'lastweek'`, on the rule that a week still being
     played is nobody's last week, so the finished draw 2 fell through to
     Previous and the older week kept the heading.

     The season rehearsal showed what that cost: draw 2 read Previous — beside
     January's events — until draw 3 finished, and then moved BACK to Last
     Week. Since 250s finish on the Saturday and 500s on the Sunday, that
     happened most weeks of the year, and a draw moving backwards is precisely
     what the owner meant by "I want to stop babysitting these constant bugs
     where draws change their status as we progress through the weeks".

     So a draw that has left Active belongs to the most recent finished week
     from that moment on. The older week (draw 1) gives up the heading a day
     or two earlier than it used to, which is a forward move for it too. */
  const list = [
    draw(1, 800, '2026-09-13', 'completed'),
    draw(2, 900, '2026-09-20', 'completed'),
    draw(3, 901, '2026-09-21', 'active'),
  ]
  assert.equal(bucket(list, 2), 'lastweek')
  assert.equal(bucket(list, 1), 'previous')
  assert.equal(bucket(list, 3), 'active')
})

check('a finished week stops being Last Week once it is plainly not', () => {
  /* "Last Week" had no sense of recency, so the most recent finished week was
     whatever had last finished — ten months ago, on a list holding one old
     event. */
  const list = [draw(1, 900, '2026-06-14', 'completed')]
  assert.equal(bucket(list, 1), 'previous')
  const fresh = [draw(1, 900, '2026-09-13', 'completed')]
  assert.equal(bucket(fresh, 1), 'lastweek')
})

// ── the shapes the data really takes ──────────────────────────────────────

check('a draw with no event of its own stands alone', () => {
  // tournament_id null: nothing can be said about what it moves with.
  const list = [
    draw(1, null, '2026-09-19', 'completed'),
    draw(2, null, '2026-09-20', 'active'),
  ]
  assert.notEqual(bucket(list, 1), 'active')
})

check('no dates, no cohorts, and nothing thrown', () => {
  assert.deepEqual(computeCohortInfo([]), {})
  assert.deepEqual(computeCohortInfo(null), {})
  assert.deepEqual(computeCohortInfo([{ id: 1, status: 'active' }]), {})
})

check('a draw’s own status still wins where it is not completed', () => {
  const list = [draw(1, 900, '2026-09-25', 'open'), draw(2, 900, '2026-09-25', 'upcoming')]
  assert.equal(bucket(list, 1), 'open')
  assert.equal(bucket(list, 2), 'upcoming')
})

console.log(`\n  ${n} passed`
  + (failures ? `, ${failures} FAILED` : ''))
if (failures) process.exitCode = 1
