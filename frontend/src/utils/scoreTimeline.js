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

const RANK = { '0': 0, '15': 1, '30': 2, '40': 3, 'A': 4 }

/**
 * History with the feed's own corrections erased.
 *
 * Sofascore's scoreboard is typed by a human, and a point posted early gets
 * corrected back: the stored stream holds 0-40, 0-30, 0-40 (Parks-Marcinko,
 * 2026-08-25) and the scrubber replayed the mistake as if the score had
 * travelled back in time. Within a game, tennis points move one way — the
 * ONLY legal backward step is A -> 40, which is deuce, and games never
 * decrease at all. So any transition that breaks those rules convicts the
 * EARLIER snapshot (the premature value), not the later one (the
 * correction): pop it and re-test, so a run of premature states collapses
 * until the stream reads as tennis again.
 *
 * What survives untouched, by construction:
 * - deuce battles: A-40 -> 40-40 -> A-40 is legal in both directions
 * - new games and new sets: points reset when games advance, which the
 *   games-must-not-decrease rule permits
 * - ESPN rows: no point to compare (null), games rules still apply
 * - tiebreaks: numeric points, same one-way rule
 */
export function sanitizeSnapshots(snapshots) {
  if (!Array.isArray(snapshots)) return []
  const out = []
  for (const cur of snapshots) {
    while (out.length) {
      const prev = out[out.length - 1]
      if (!_illegalRegression(prev, cur)) break
      out.pop()
    }
    // Erasing a premature run can leave the state it regressed TO sitting
    // beside its own earlier copy — two identical 40-30s where the feed went
    // 40-30, (phantom game), 40-30. One state, one snapshot: keep the
    // earlier, whose timestamp is when it first became true.
    const top = out[out.length - 1]
    if (top && _sameState(top, cur)) continue
    out.push(cur)
  }
  return out
}

function _sameState(a, b) {
  return JSON.stringify(a.games) === JSON.stringify(b.games)
    && JSON.stringify(a.point ?? null) === JSON.stringify(b.point ?? null)
    && !!a.tiebreak === !!b.tiebreak
    && !!a.match_tiebreak === !!b.match_tiebreak
    && (a.serving ?? null) === (b.serving ?? null)
}

function _illegalRegression(prev, cur) {
  const pg = prev?.games
  const cg = cur?.games
  if (!pg?.[0] || !cg?.[0]) return false
  // A set column vanishing, or games shrinking inside a column, is never
  // tennis — compare per shared column.
  if (cg[0].length < pg[0].length) return true
  for (let c = 0; c < pg[0].length; c++) {
    if (num(cg[0][c]) < num(pg[0][c]) || num(cg[1]?.[c]) < num(pg[1]?.[c])) return true
  }
  // Points, only when the game itself did not advance.
  const col = pg[0].length - 1
  const sameGame = cg[0].length === pg[0].length
    && num(cg[0][col]) === num(pg[0][col])
    && num(cg[1]?.[col]) === num(pg[1]?.[col])
    && !!prev.tiebreak === !!cur.tiebreak
  if (!sameGame || !prev.point || !cur.point) return false
  if (prev.tiebreak) {
    // tiebreak points are plain numbers and only count up
    return num(cur.point[0]) < num(prev.point[0]) || num(cur.point[1]) < num(prev.point[1])
  }
  for (const side of [0, 1]) {
    const a = RANK[String(prev.point[side])]
    const b = RANK[String(cur.point[side])]
    if (a == null || b == null) continue
    if (b < a && !(a === 4 && b === 3)) return true   // only A -> 40 may fall
  }
  return false
}


/**
 * Markers for a snapshot list, as [{ i, kind: 'set' | 'break', side: 1|2 }].
 *
 * `i` is the SLIDER POSITION where the event first shows — the snapshot in
 * which the new state is visible — so clicking the tick lands on the moment
 * just after the break was sealed or the set closed. `side` is WHO did it,
 * in the snapshot's own orientation (1 = games[0] = the bracket's player1):
 * the breaker for a break, the set's winner for a set — so the popup can
 * hang the tick above or below the track next to that player's initials.
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
export function timelineMarkers(snapshots, opts = {}) {
  const out = []
  if (!Array.isArray(snapshots) || snapshots.length < 2) return out
  const { completed = false, winnerSide = null } = opts

  // High-water mark of set columns. A set tick fires only when the count
  // exceeds the most EVER seen, not the previous snapshot's: at a set change
  // Sofascore can flicker — three columns, briefly two again, then three —
  // and pair-wise comparison marked the same set twice (Sonego-Herbert,
  // 2026-08-24, two blue ticks for one set). A shrink never unmarks anything;
  // it just cannot re-earn a tick on the way back up.
  let maxCols = snapshots[0]?.games?.[0]?.length ?? 0

  for (let i = 1; i < snapshots.length; i++) {
    const prev = snapshots[i - 1]
    const cur = snapshots[i]
    const pg = prev?.games
    const cg = cur?.games
    if (!pg?.[0] || !cg?.[0]) continue

    // ── Set finished ──
    if (cg[0].length > pg[0].length && cg[0].length > maxCols) {
      maxCols = cg[0].length
      // The finished set's final score sits in cur at the column that was
      // last in prev — read the winner off it. A feed that reorders columns
      // mid-match would misattribute here, but that would already be a
      // corrupted history everywhere else too.
      const col = pg[0].length - 1
      const side = num(cg[0][col]) > num(cg[1]?.[col]) ? 1 : 2
      out.push({ i, kind: 'set', side })
      // BROKE TO WIN IT: when the set's closing game was a break, the break
      // rides BESIDE the set tick (adj) rather than being swallowed by it —
      // sealing a set on the opponent's serve is exactly the moment a reader
      // scrubs for. Same reading as the break rule below, on the finished
      // column; a tiebreak'd set never qualifies (mini-breaks aren't breaks).
      const g = _gameWon(pg, cg, col, prev)
      if (g && g.winner !== g.server) {
        out.push({ i, kind: 'break', side: g.winner, adj: true })
      }
      continue
    }

    // ── Break of serve ──
    const g = _gameWon(pg, cg, pg[0].length - 1, prev)
    if (g && g.winner !== g.server) {
      out.push({ i, kind: 'break', side: g.winner })
    }
  }

  /* ── Match finished ── a red tick at the timeline's very end, only once
     the match IS over (the popup says so — a live match's history simply
     has no end yet). Its side is the match's real winner, HANDED IN by the
     popup where it knows one (retirements decide matches from behind, so
     reading the winner off the games can lie); the last column's games are
     only the fallback. If the closing game was a break — broke to win the
     match — the break tick rides beside it, same as a set. */
  if (completed && snapshots.length >= 2) {
    const iEnd = snapshots.length
    const last = snapshots[snapshots.length - 1]
    const lg = last?.games
    let side = winnerSide
    if (side !== 1 && side !== 2) {
      const col = (lg?.[0]?.length ?? 0) - 1
      side = col >= 0 && num(lg[0][col]) > num(lg[1]?.[col]) ? 1 : 2
    }
    out.push({ i: iEnd, kind: 'match', side })
    const prev = snapshots[snapshots.length - 2]
    const pg = prev?.games
    if (pg?.[0] && lg?.[0] && pg[0].length === lg[0].length) {
      const g = _gameWon(pg, lg, pg[0].length - 1, prev)
      if (g && g.winner !== g.server && g.winner === side) {
        out.push({ i: iEnd, kind: 'break', side, adj: true })
      }
    }
  }
  return out
}


/* One game, completed between two snapshots in a given column — or null.
   The shared reading behind every break judgement: exactly one side gained
   exactly one game (anything else is a feed correction, not a game we
   watched finish), the server is PREV's — who held the ball while it was
   played — and a tiebreak in progress disqualifies the pair outright. */
function _gameWon(pg, cg, col, prev) {
  if (prev.tiebreak) return null
  const server = prev.serving
  if (server !== 1 && server !== 2) return null
  if (col < 0 || col >= cg[0].length) return null
  const dA = num(cg[0][col]) - num(pg[0][col])
  const dB = num(cg[1]?.[col]) - num(pg[1]?.[col])
  if (dA + dB !== 1 || dA < 0 || dB < 0) return null
  return { winner: dA === 1 ? 1 : 2, server }
}
