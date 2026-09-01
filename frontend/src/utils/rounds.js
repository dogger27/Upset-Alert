/*
 * Round labels, in the scoreboard forms: R128 / R64 / R32 / R16 / QF / SF / F.
 *
 * The API sends the long names ("Round of 128", "Quarterfinals") and MUST KEEP
 * DOING SO — `Draw.round_name()` output is not only displayed, it is a key.
 * `push_content.py` builds a notification tag from it ("round-{name}-{where}")
 * and the digest scheduler reverse-looks-up a stored label back to a round
 * number. Rewriting the server's wording would change dedup keys, which is how
 * a round-complete notification gets sent a second time for a round that was
 * already announced. So the shortening happens HERE, at the point of display,
 * and nothing about the server's bookkeeping moves.
 *
 * Kept identical to mobile/rounds.js on purpose — two clients naming the same
 * round two different ways is exactly the inconsistency this replaces.
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
  // Unknown wording is kept rather than truncated: a label this does not
  // recognise is more useful whole than clipped into something that reads like
  // a different round.
  return name
}
