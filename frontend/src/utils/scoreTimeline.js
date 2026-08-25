/* The moments that mattered, derived from a match's score history.
 *
 * The history popup's slider is a list of score CHANGES; most are ordinary
 * points. Two kinds of change are worth marking on the track itself — a break
 * of serve and the end of a set — so the timeline reads as a map rather than
 * a blind scrubber. Everything here is derived from consecutive snapshot
 * pairs; nothing is stored, and the backend knows nothing about it.
 *
 * A plain .js module with no JSX or DOM so the detection rules can be run
 * under node against synthetic and real histories — which is how they were
 * verified before shipping.
 */

const num = (v) => {
  const n = parseInt(v, 10)
  return Number.isFinite(n) ? n : 0
}

/**
 * Markers for a snapshot list, as [{ i, kind: 'set' | 'break' }].
 *
 * `i` is the SLIDER POSITION where the event first shows — the snapshot in
 * which the new state is visible — so clicking the tick lands on the moment
 * just after the break was sealed or the set closed.
 *
 * Rules, and why:
 * - A SET ends when the games array gains a column: the feeds append the new
 *   set the moment it starts, so the first snapshot with an extra column is
 *   the first sight of the previous set being over. The final set gets no
 *   tick — the slider's rightmost stop is already "final".
 * - A BREAK is a completed game whose winner was not its server. The server
 *   of the completed game is `prev.serving` — who held the ball while it was
 *   played — never `cur.serving`, which has already rotated.
 * - No break detection through a tiebreak (`prev.tiebreak`): mini-breaks are
 *   not breaks, and the tiebreak's end is a SET event.
 * - Where a break closes a set, only the set is marked: the set is the
 *   bigger fact, and two overlapping 2px ticks read as a smudge.
 * - A snapshot pair with no serving information (null — a feed gap, or ESPN
 *   before its serving inference warms up) contributes no break tick: saying
 *   nothing beats guessing, exactly the draw page's own rule for scores.
 */
export function timelineMarkers(snapshots) {
  const out = []
  if (!Array.isArray(snapshots) || snapshots.length < 2) return out

  for (let i = 1; i < snapshots.length; i++) {
    const prev = snapshots[i - 1]
    const cur = snapshots[i]
    const pg = prev?.games
    const cg = cur?.games
    if (!pg?.[0] || !cg?.[0]) continue

    // ── Set finished ──
    if (cg[0].length > pg[0].length) {
      out.push({ i, kind: 'set' })
      continue // a break sealing the set is subsumed by the set tick
    }

    // ── Break of serve ──
    if (prev.tiebreak) continue
    const server = prev.serving
    if (server !== 1 && server !== 2) continue
    const col = pg[0].length - 1
    if (col < 0 || col >= cg[0].length) continue
    const dA = num(cg[0][col]) - num(pg[0][col])
    const dB = num(cg[1]?.[col]) - num(pg[1]?.[col])
    // Exactly one side gained exactly one game — anything else is a feed
    // correction (a rewound or double-counted score), not a game we watched
    // finish, and inventing a break from it would mark a moment that never
    // happened.
    if (dA + dB !== 1 || dA < 0 || dB < 0) continue
    const winner = dA === 1 ? 1 : 2
    if (winner !== server) out.push({ i, kind: 'break' })
  }
  return out
}
