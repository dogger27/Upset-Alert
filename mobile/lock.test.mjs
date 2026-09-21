import { test } from 'node:test'
import assert from 'node:assert/strict'
import { HIDDEN_PICKS_NOTE, lockLabel, othersPicksNote, predictorsMessage } from './lock.js'

test('others’ picks: the mode decides the wait, and an active draw has none', () => {
  assert.equal(othersPicksNote({ status: 'active', pick_lock_mode: 'r1_progressive' }), null)
  assert.equal(othersPicksNote({ status: 'completed' }), null)
  assert.match(othersPicksNote({ status: 'open', pick_lock_mode: 'r1_progressive', closing_time: '2026-09-01T15:00:00' }),
               /every first-round match has started/)
  assert.match(othersPicksNote({ status: 'open', pick_lock_mode: 'classic', closing_time: '2026-09-01T15:00:00' }),
               /after pick selection closes: /)
  assert.match(othersPicksNote({ status: 'open' }), /after pick selection closes\.$/)
})

/* ONE DEADLINE, BOTH MODES (owner, 2026-09-19, correcting himself the same
   day): locking STARTS at the first ball whatever the mode, so every draw
   counts down to it. `label` leads quietly and `value` carries the weight. */
const AT = '2026-09-21T15:00:00'
const at = (h, m = 0) => Date.parse(`${AT}Z`) - ((h * 60 + m) * 60_000)

test('a match-by-match draw counts down like any other', () => {
  const prog = { pick_lock_mode: 'r1_progressive', closing_time: AT }
  const plain = { pick_lock_mode: 'draw_start', closing_time: AT }
  // The mode changes which picks survive the first ball, not when the first
  // ball is — so the line reads the same on both.
  assert.equal(lockLabel(prog, at(35)).text, 'Locks in: 35 hrs')
  assert.equal(lockLabel(prog, at(35)).text, lockLabel(plain, at(35)).text)
  assert.equal(lockLabel(prog, at(4, 30)).text, 'Locks in: 4h 30m')
})

test('once the first ball has gone, the two modes part company', () => {
  const prog = { pick_lock_mode: 'r1_progressive', closing_time: AT }
  const plain = { pick_lock_mode: 'draw_start', closing_time: AT }
  /* THE ONE WINDOW THAT DIFFERS. A progressive draw is not `is_locked` until
     round one COMPLETES, so between the first ball and that moment a card
     would otherwise claim picks were closed for the two days a first round
     takes — while the draw screen still accepts changes to untouched later
     rounds. */
  assert.equal(lockLabel(prog, at(-1)).text, 'Lock at: End of R1')
  assert.equal(lockLabel(plain, at(-1)).text, 'Picks closed')
  // And once it HAS locked, it is closed like anything else.
  assert.equal(lockLabel({ ...prog, is_locked: true }, at(-30)).text, 'Picks closed')
})

test('every draw counts down to its moment', () => {
  const t = { pick_lock_mode: 'draw_start', closing_time: AT }
  // Hours right out to three days — the owner's own example was "52 hrs".
  assert.equal(lockLabel(t, at(52)).text, 'Locks in: 52 hrs')
  assert.equal(lockLabel(t, at(24)).text, 'Locks in: 24 hrs')
  assert.equal(lockLabel(t, at(71, 59)).text, 'Locks in: 71 hrs')
  // Past three days the number stops meaning anything.
  assert.equal(lockLabel(t, at(72)).text, 'Locks in: 3 days')
  assert.equal(lockLabel(t, at(24 * 9)).text, 'Locks in: 9 days')
  // Inside the day, hours and minutes; inside the hour, minutes.
  assert.equal(lockLabel(t, at(5, 30)).text, 'Locks in: 5h 30m')
  assert.equal(lockLabel(t, at(0, 45)).text, 'Locks in: 45m')
})

test('urgent turns on inside six hours, and not before', () => {
  const t = { pick_lock_mode: 'draw_start', closing_time: AT }
  assert.equal(lockLabel(t, at(24)).urgent, false)
  assert.equal(lockLabel(t, at(6)).urgent, false)
  assert.equal(lockLabel(t, at(5, 59)).urgent, true)
  assert.equal(lockLabel(t, at(0, 20)).urgent, true)
})

test('closed is closed, whichever way it got there', () => {
  assert.equal(lockLabel({ is_locked: true }).text, 'Picks closed')
  // The clock ran out but nothing has stamped it yet.
  assert.equal(lockLabel({ closing_time: AT }, at(-1)).text, 'Picks closed')
  // A progressive draw that HAS locked reads closed, not "End of R1" —
  // is_locked is checked before the clock for exactly this reason.
  assert.equal(lockLabel({ is_locked: true, pick_lock_mode: 'r1_progressive' }).text, 'Picks closed')
})

test('nothing to say, rather than something wrong', () => {
  assert.equal(lockLabel(null), null)
  assert.equal(lockLabel({ pick_lock_mode: 'draw_start' }), null)
  assert.equal(lockLabel({ closing_time: 'not a date' }), null)
})

/* ── EMPTY COLUMNS ARE NOT "NOBODY" ──────────────────────────────────────
 *
 * The "Who got it right?" sheet read Right (0) "No one." / Wrong (0) "No one."
 * on a COMPLETED first-round match at Singapore (owner, 2026-09-21, with a
 * screenshot). Six people had picked it — one right, five wrong.
 *
 * The server was correct and said so: under match-by-match locking it
 * withholds everyone's picks until every first-round match has STARTED, and
 * it answers `{correct: [], incorrect: [], hidden: true}`. Verified in
 * production against that very match. The sheet had no branch for `hidden`,
 * so it fell through to the empty-list wording and asserted the opposite of
 * the truth.
 *
 * `hidden` implies match-by-match locking and an unfinished draw, always:
 * predictions_visible() returns true immediately for a completed draw and for
 * every other lock mode, so nothing else can reach this state. That is what
 * lets one sentence explain it.
 */
test('a withheld answer is told apart from an empty one', () => {
  assert.equal(predictorsMessage({ correct: [], incorrect: [], hidden: true }),
               HIDDEN_PICKS_NOTE)
  // Genuinely nobody: the columns speak for themselves, no note.
  assert.equal(predictorsMessage({ correct: [], incorrect: [] }), null)
  assert.equal(predictorsMessage({ correct: [], incorrect: [], hidden: false }), null)
  // Somebody, and still withheld — the case that made this a lie rather than
  // a blank: the note wins, and the caller must not render the columns.
  assert.equal(predictorsMessage({ correct: [{ id: 1 }], incorrect: [], hidden: true }),
               HIDDEN_PICKS_NOTE)
  // Nothing loaded yet is not an answer at all.
  assert.equal(predictorsMessage(null), null)
  assert.equal(predictorsMessage(undefined), null)
})

test('the note says when the picks arrive, not merely that they are gone', () => {
  // A reader who is told "hidden" and not "until when" has been told nothing
  // they can act on. It is the same rule othersPicksNote states on the
  // standings, so the two must not drift into two different explanations.
  assert.match(HIDDEN_PICKS_NOTE, /every first-round match has started/)
  assert.match(othersPicksNote({ status: 'open', pick_lock_mode: 'r1_progressive' }),
               /every first-round match has started/)
})
