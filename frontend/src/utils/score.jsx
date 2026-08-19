/*
 * Tennis score formatting, shared by the draw and the schedule.
 *
 * Lifted out of CombinedView when the schedule page needed it. Scores are not
 * something to render twice: the tiebreak rule alone (show the points only for
 * the set's LOSER, as a superscript) is the kind of detail that silently drifts
 * between two copies, and the schedule's first attempt printed "5 | 4" because
 * it invented its own.
 */
import { Fragment } from 'react'

/*
 * Sets are emitted as individual nowrap spans with the comma TRAILING, and an
 * ordinary space between them. That is what lets a long score wrap between
 * sets while keeping each set whole — "6-7(3)" must never break across lines,
 * and a leading comma would strand ", 3-6" at the start of the next one.
 */
function joinSets(sets) {
  return sets.map((s, i) => (
    <Fragment key={i}>
      {i > 0 && ' '}
      <span className="score-set">{s}{i < sets.length - 1 ? ',' : ''}</span>
    </Fragment>
  ))
}

// One set cell → { g: games, tb: tiebreak points | null }
export function parseSet(cell) {
  const m = cell != null ? String(cell).replace(/r$/i, '').match(/^(\d+)(?:\((\d+)\))?/) : null
  return m ? { g: m[1], tb: m[2] ?? null } : { g: '', tb: null }
}

// Render the score oriented TOP-player-first (i.e. player1 / the box shown
// on top of the pairing) as "7-6³, 3-6, 7-5, 6-0", regardless of who won:
// sets joined by ", "; tiebreak shown only for the set's LOSER, as a
// superscript. If either side's score cells carry a trailing "r"
// (retirement), append " (ret.)".
export function scoreNodes(scores) {
  if (!scores || scores.length < 2) return null
  const a = scores[0]
  const b = scores[1]
  // A walkover has no games to format: the withdrawing side's only cell is the
  // literal "w/o". parseSet below matches on ^(\d+), so both cells reduced to
  // empty, every set was skipped and this returned null — a completed match
  // showing no score at all, with nothing to say why.
  if ([a, b].some(arr => arr?.some(v => /^w\/?o$/i.test(String(v ?? '').trim())))) {
    return <span className="cv-ret">walkover</span>
  }
  const n = Math.max(a?.length ?? 0, b?.length ?? 0)
  const sets = []
  let retired = false
  for (let i = 0; i < n; i++) {
    if (/r$/i.test(a?.[i] ?? '') || /r$/i.test(b?.[i] ?? '')) retired = true
    const A = parseSet(a?.[i]), B = parseSet(b?.[i])
    if (A.g === '' && B.g === '') continue
    const gA = Number(A.g), gB = Number(B.g)
    // The tiebreak loser is the side with fewer games; show only their points.
    const loserIsA = A.tb != null && (B.tb == null || gA < gB)
    if (A.tb != null && loserIsA) {
      sets.push(<>{A.g}<sup>{A.tb}</sup>-{B.g}</>)
    } else if (B.tb != null && !loserIsA) {
      sets.push(<>{A.g}-{B.g}<sup>{B.tb}</sup></>)
    } else {
      sets.push(<>{A.g}-{B.g}</>)
    }
  }
  if (sets.length === 0) return null
  return (
    <>
      {joinSets(sets)}
      {retired && <span className="cv-ret"> (ret.)</span>}
    </>
  )
}

// Same set formatting as scoreNodes, but sourced from live_scores_json
// ([p1SetGames, p2SetGames, serving, p1SetWins]) instead of the persisted
// match.scores — the live feed's LAST entry is the current, still-in-play
// set (its p1SetWins value is null, since ESPN has no winner for it yet),
// which match.scores never carries at all (it only ever holds completed
// sets). That in-progress set is rendered as a plain game score (no
// tiebreak superscript — point-level score isn't tracked here, only game
// counts). No "(In Progress)"/"(Suspended)" tag: this score now renders
// between the two opponents of the live match itself, inside a group that
// already carries the In Progress / Suspended badge on its top border.
export function liveScoreNodes(live) {
  if (!live) return null
  const [aArr, bArr, , setWinsA] = live
  const n = Math.max(aArr?.length ?? 0, bArr?.length ?? 0)
  const sets = []
  for (let i = 0; i < n; i++) {
    const A = parseSet(aArr?.[i]), B = parseSet(bArr?.[i])
    if (A.g === '' && B.g === '') continue
    if (setWinsA?.[i] == null) { sets.push(<>{A.g}-{B.g}</>); continue }
    const gA = Number(A.g), gB = Number(B.g)
    const loserIsA = A.tb != null && (B.tb == null || gA < gB)
    if (A.tb != null && loserIsA) sets.push(<>{A.g}<sup>{A.tb}</sup>-{B.g}</>)
    else if (B.tb != null && !loserIsA) sets.push(<>{A.g}-{B.g}<sup>{B.tb}</sup></>)
    else sets.push(<>{A.g}-{B.g}</>)
  }
  if (sets.length === 0) return null
  return joinSets(sets)
}
