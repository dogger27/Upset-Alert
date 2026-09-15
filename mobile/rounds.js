/*
 * Round labels, short enough for a strip across a phone.
 *
 * The server sends full names ("Round of 128", "Quarterfinals") because that is
 * what a page has room for. A pager across 393pt has room for six or seven
 * chips, so it needs the scoreboard forms — which are also what people say.
 */

const SHORT = [
  [/round of (\d+)/i, m => `R${m[1]}`],
  [/quarter/i, () => 'QF'],
  [/semi/i, () => 'SF'],
  [/^final/i, () => 'F'],
  [/third place|3rd place/i, () => '3rd'],
  [/qualifying round (\d+)/i, m => `Q${m[1]}`],
  [/qualifying/i, () => 'Q'],
  // The column past the final: the champion, as the trophy (owner, 2026-09-09).
  [/champion/i, () => '🏆'],
]

export function shortRound(name, roundNumber) {
  if (!name) return roundNumber != null ? `R${roundNumber}` : ''
  for (const [re, fn] of SHORT) {
    const m = name.match(re)
    if (m) return fn(m)
  }
  // Unknown wording: keep it, trimmed. Better a long chip than a wrong one.
  return name.length > 6 ? name.slice(0, 6) : name
}

/* The reader's own calendar day, which is the day the schedule screen prints
   its clocks in (the device's zone, not the venue's and not the account's).
   A match is "today" if the reader would see it on today's page. */
function sameDay(iso, now) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return false
  const n = new Date(now)
  return d.getFullYear() === n.getFullYear()
    && d.getMonth() === n.getMonth()
    && d.getDate() === n.getDate()
}

/* Which round to open on.
 *
 * THE FURTHEST ROUND THAT HAS HAPPENED OR IS HAPPENING TODAY — the one holding
 * the latest result, the matches on court right now, or the ones the
 * tournament has put on today's sheet. Rounds only ever move forward, so the
 * last such round IS the live edge of the draw.
 *
 * TODAY'S SHEET is the second half of that test and it earns its place in the
 * morning. A round whose matches are printed for today but have not begun is
 * the round the reader is here for; without it the screen opened on
 * yesterday's, which was over, while the day's play was one tab away (owner,
 * 2026-09-15). It can only ever move the answer FORWARD — a day's sheet is
 * never behind the last round that started — so the fix below is untouched.
 *
 * A COMPLETED DRAW therefore opens on its final: nothing is scheduled for
 * today, and the final is the furthest round that started. The champion column
 * past it holds no match to have started, so it is somewhere the reader
 * arrives by choice rather than somewhere they are put.
 *
 * It used to open on the EARLIEST round with anything undecided, which is a
 * different question and a worse one: a single straggler left behind — a
 * suspended match, a qualifying slot that never resolved, a walkover never
 * stamped — pinned the whole screen back on R128 while the quarter-finals
 * were being played.
 *
 * "Started" rather than "won", so a round whose first matches are on court but
 * none yet finished is still the answer. Opening on the previous round to show
 * settled results, while the draw's live edge sits one tab away, is the same
 * mistake in the other direction.
 *
 * Nothing started at all — a draw released, picks not yet playable — opens at
 * the first round, which is where the picking is.
 */
export function currentRound(rounds, now = Date.now()) {
  const started = m => !m.is_bye && !!(m.winner || m.live_scores || m.live_point)
  /* A schedule entry exists only where the tournament PRINTED the match, so
     both kinds count: "estimated" is a time derived from the match above it on
     the same sheet ("Followed By"), not a guess about a future round. */
  const today = m => !m.is_bye && !!m.expected_start_at && sameDay(m.expected_start_at, now)
  for (let i = rounds.length - 1; i >= 0; i--) {
    if (rounds[i][1].some(m => started(m) || today(m))) return rounds[i][0]
  }
  return rounds.length ? rounds[0][0] : null
}
