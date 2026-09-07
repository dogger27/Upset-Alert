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

/* Which round to open on.
 *
 * THE FURTHEST ROUND THAT HAS ACTUALLY HAPPENED — the one holding the latest
 * result, or the matches on court right now. Rounds only ever move forward, so
 * the last round with a started match IS the live edge of the draw.
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
export function currentRound(rounds) {
  const started = m => !m.is_bye && !!(m.winner || m.live_scores || m.live_point)
  for (let i = rounds.length - 1; i >= 0; i--) {
    if (rounds[i][1].some(started)) return rounds[i][0]
  }
  return rounds.length ? rounds[0][0] : null
}
