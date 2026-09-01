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
 * The one being PLAYED — the earliest with anything undecided. Opening on
 * R128 of a completed slam means scrolling past six rounds of history to reach
 * what is happening; opening on the final of a draw that has not started means
 * a screen of TBD. When everything is done, the last round is the answer,
 * because that is where the result is.
 */
export function currentRound(rounds) {
  for (const [num, matches] of rounds) {
    if (matches.some(m => !m.is_bye && !m.winner)) return num
  }
  return rounds.length ? rounds[rounds.length - 1][0] : null
}
