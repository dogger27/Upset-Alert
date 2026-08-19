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
 * Sets are emitted as individual nowrap spans separated by an ordinary space,
 * so a long score can wrap BETWEEN sets while each set stays whole — "6-7(3)"
 * must never break across lines.
 *
 * The comma is added in CSS, not here, because whether one belongs depends on
 * where the line happens to break — and that is only knowable after layout.
 * The draw page has the width to keep commas; the schedule's narrow
 * right-aligned column drops them rather than stranding one at the end of a
 * line. See .score-set in Schedule.css.
 */
function joinSets(sets) {
  return sets.map((s, i) => (
    <Fragment key={i}>
      {i > 0 && ' '}
      <span className="score-set">{s}</span>
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


/* ── Expected start ──
 *
 * "Today at ~4:35 PM" / "Tomorrow at 12:40 PM EDT". The tilde marks an
 * estimate, exactly as it does on the schedule page, so a chained guess never
 * reads as an announced time.
 *
 * zone: an IANA name to render in, or undefined for the reader's own.
 */
const FIVE_MIN = 5 * 60 * 1000

export function expectedStartLabel(iso, source, zone) {
  if (!iso) return null
  let when = new Date(iso)
  if (Number.isNaN(when.getTime())) return null

  // Round estimates to five minutes, as the schedule does. A guess chained from
  // constant match lengths has no business claiming "8:12" — the precision is
  // invented, and showing it invites more trust than it has earned. A printed
  // time keeps whatever the tournament stated.
  if (source !== 'printed') {
    when = new Date(Math.round(when.getTime() / FIVE_MIN) * FIVE_MIN)
  }

  const opts = { hour: 'numeric', minute: '2-digit', ...(zone ? { timeZone: zone } : {}) }
  const time = when.toLocaleTimeString([], opts)

  // Compare calendar days in the SAME zone the time is being shown in —
  // otherwise a late match reads "Today" to one reader and "Tomorrow" to
  // another looking at the identical row.
  const dayOf = (d) => d.toLocaleDateString('en-CA', zone ? { timeZone: zone } : {})
  const today = dayOf(new Date())
  const thatDay = dayOf(when)

  let prefix
  if (thatDay === today) {
    prefix = 'Today'
  } else {
    const tomorrow = new Date()
    tomorrow.setDate(tomorrow.getDate() + 1)
    prefix = thatDay === dayOf(tomorrow)
      ? 'Tomorrow'
      : when.toLocaleDateString([], { weekday: 'short', ...(zone ? { timeZone: zone } : {}) })
  }

  // Always name the zone, including the reader's own. A bare time forces the
  // question "whose clock is that?" on anyone who has ever switched the
  // setting, and the answer is only obvious to someone who has not.
  //
  // Resolved by Intl rather than stored, so it tracks daylight saving on its
  // own: the same venue is EDT in August and EST in November, and a fixed
  // abbreviation would be wrong for half the season.
  let suffix = ''
  {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZoneName: 'short', ...(zone ? { timeZone: zone } : {}),
    }).formatToParts(when)
    const tzName = parts.find(p => p.type === 'timeZoneName')?.value
    if (tzName) suffix = ` ${tzName}`
  }

  const hedge = source === 'printed' ? '' : '~'
  return `${prefix} at ${hedge}${time}${suffix}`
}
