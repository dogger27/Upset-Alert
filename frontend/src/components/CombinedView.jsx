/**
 * CombinedView — traditional single-player-per-box bracket that combines the
 * user's PICKS with the LIVE result.
 *
 * Columns (0..N for an N-round draw):
 *   col 0  = every entrant of round 1, one box each (the draw). No result/colour.
 *   col c  = the winner of each round-c match, as the user PREDICTED:
 *              • box shows the user's picked winner (falls back to the real
 *                winner if the user made no pick)
 *              • actual score shown beneath the box
 *              • green if the pick was right, red if wrong
 *              • when wrong, the REAL winner's name is shown above the box
 *   col N  = the champion.
 *
 * Windowed like BracketView: only `windowSize` columns render, starting at
 * `windowStart` (the parent's dot pager controls both).
 */
import { Fragment, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import H2HPanel from './H2HPanel'
import PredictorsPopup from './PredictorsPopup'
import { buildH2HSequence, buildMatchIndex, h2hNeighbours, resolveRealFirst } from '../utils/h2hSequence'
import './CombinedView.css'
import { parseSet, scoreNodes, liveScoreNodes } from '../utils/score'

// Upset bell with the same hover tooltip as BracketView's (portal-rendered,
// "Upset Alert!" pill) — pulled into its own component so each bell instance
// tracks its own hover state and bounding-rect-derived tooltip position.
function UpsetBell({ style }) {
  const ref = useRef(null)
  const [tipPos, setTipPos] = useState(null)
  return (
    <>
      <span
        ref={ref}
        className="cv-bell"
        style={style}
        onMouseEnter={() => {
          const r = ref.current?.getBoundingClientRect()
          if (r) setTipPos({ x: r.left + r.width / 2, y: r.top })
        }}
        onMouseLeave={() => setTipPos(null)}
      >
        🔔
      </span>
      {tipPos && createPortal(
        <span className="upset-tooltip" style={{ position: 'fixed', left: tipPos.x, top: tipPos.y - 8, transform: 'translate(-50%, -100%)' }}>
          <span className="upset-tooltip-dot" />
          <span className="upset-tooltip-text">
            <span className="upset-tooltip-upset">Upset </span>
            <span className="upset-tooltip-alert">Alert</span>
            <span className="upset-tooltip-exclaim">!</span>
          </span>
        </span>,
        document.body
      )}
    </>
  )
}

// Two-person glyph for the predictors chip. Counter-rotated in CSS, since the
// chip it sits in is rotated -90deg to match the H2H pill's footprint.
function GroupIcon() {
  return (
    <svg className="cv-group-icon" viewBox="0 0 20 20" aria-hidden="true">
      <circle cx="7.6" cy="6.4" r="3.1" />
      <path d="M1.6 16.4c0-3.1 2.7-5.2 6-5.2s6 2.1 6 5.2z" />
      <circle cx="15" cy="7.4" r="2.4" opacity="0.75" />
      <path d="M13.1 12.1c.6-.2 1.2-.3 1.9-.3 2.6 0 4.6 1.6 4.6 4h-4.9c0-1.5-.6-2.8-1.6-3.7z" opacity="0.75" />
    </svg>
  )
}

// IOC 3-letter → ISO 2-letter for flag classes (mirror of BracketView)
const IOC_TO_ISO2 = {
  AUS:'AU', USA:'US', GBR:'GB', FRA:'FR', GER:'DE', ESP:'ES', ITA:'IT',
  RUS:'RU', CAN:'CA', JPN:'JP', CHN:'CN', KOR:'KR', ARG:'AR', BRA:'BR',
  SUI:'CH', AUT:'AT', BEL:'BE', NED:'NL', DEN:'DK', NOR:'NO', SWE:'SE',
  FIN:'FI', POL:'PL', CZE:'CZ', SVK:'SK', HUN:'HU', ROU:'RO', BUL:'BG',
  SRB:'RS', CRO:'HR', SLO:'SI', BIH:'BA', MKD:'MK', GRE:'GR', TUR:'TR',
  POR:'PT', GEO:'GE', KAZ:'KZ', UKR:'UA', BLR:'BY', LAT:'LV', LTU:'LT',
  EST:'EE', ISR:'IL', RSA:'ZA', EGY:'EG', MAR:'MA', TUN:'TN', NGR:'NG',
  CHI:'CL', COL:'CO', PER:'PE', URU:'UY', VEN:'VE', ECU:'EC', BOL:'BO',
  PAR:'PY', MEX:'MX', IND:'IN', PAK:'PK', THA:'TH', VIE:'VN', INA:'ID',
  MAS:'MY', PHI:'PH', TPE:'TW', HKG:'HK', NZL:'NZ', BAH:'BS', DOM:'DO',
  HAI:'HT', PUR:'PR', TTO:'TT', JAM:'JM', BAR:'BB', GUA:'GT', CRC:'CR',
  MON:'MC', LUX:'LU', ISL:'IS', IRL:'IE', CYP:'CY', MLT:'MT',
}
function nationalityIso2(nat) {
  if (!nat) return null
  return IOC_TO_ISO2[nat.toUpperCase()] ?? (nat.length === 2 ? nat.toUpperCase() : null)
}

// Inferred seed/rank: seeds keep their seed number; unseeded ranked after the
// highest seed by world ranking (same rule as BracketView.computeDrawRanks).
function computeDrawRanks(players) {
  const ranks = {}
  const seeded = players.filter(p => p.seed != null)
  for (const p of seeded) ranks[p.id] = p.seed
  const unseeded = players
    .filter(p => p.seed == null)
    .sort((a, b) => {
      if (a.ranking != null && b.ranking != null) return a.ranking - b.ranking
      if (a.ranking != null) return -1
      if (b.ranking != null) return 1
      return (a.bracket_position ?? 0) - (b.bracket_position ?? 0)
    })
  const offset = seeded.reduce((max, p) => Math.max(max, p.seed), 0)
  unseeded.forEach((p, i) => { ranks[p.id] = offset + i + 1 })
  return ranks
}

// Resolve each match's two feeder player ids the same way winnerBox displays
// them: R1 comes straight from the draw; R2+ cascades the PICKED winner of
// each feeder (falling back to the real winner once known). Raw match.player1/
// player2 for R2+ only get populated once the actual bracket result is in, so
// reading them directly (as BracketView's live mode does) hides H2H/upset-bell
// for Open draws where only picks are available.
function resolveCombinedPlayers(matches, picks) {
  const byKey = {}
  for (const m of matches) byKey[`${m.round_number}:${m.match_number}`] = m
  const resolved = {}

  function getAdvancer(m) {
    if (!m) return null
    if (m.is_bye) return m.player1?.id ?? null
    // A pick only counts if the picked player is one of this match's resolved
    // feeders. Orphaned picks (e.g. a downstream pick of a player displaced by
    // a later upstream re-pick, or legacy phantom picks) must not cascade a
    // player into rounds their own bracket path never reaches.
    const r = resolved[m.id]
    const pick = picks?.[m.id]
    const pickValid = pick != null && r != null && (pick === r.p1 || pick === r.p2)
    return (pickValid ? pick : null) ?? m.winner?.id ?? null
  }

  function resolve(m) {
    if (resolved[m.id]) return resolved[m.id]
    let p1id = m.round_number === 1 ? (m.player1?.id ?? null) : null
    let p2id = m.round_number === 1 ? (m.player2?.id ?? null) : null
    if (m.round_number > 1) {
      const f1 = byKey[`${m.round_number - 1}:${m.match_number * 2 - 1}`]
      const f2 = byKey[`${m.round_number - 1}:${m.match_number * 2}`]
      if (f1) resolve(f1)
      if (f2) resolve(f2)
      p1id = f1 ? getAdvancer(f1) : null
      p2id = f2 ? getAdvancer(f2) : null
    }
    resolved[m.id] = { p1: p1id, p2: p2id }
    return resolved[m.id]
  }

  for (const m of matches) resolve(m)
  return resolved
}

function abbrevName(full) {
  if (!full) return ''
  const parts = full.trim().split(/\s+/)
  if (parts.length === 1) return parts[0]
  return `${parts[0][0]}. ${parts.slice(1).join(' ')}`
}

// A match is live while ESPN is feeding scores for it and no winner has been
// recorded yet — the same test the In Progress badge uses.
const isLiveMatch = (m) => m?.live_scores != null && m.winner == null

const BOX_H = 32
const SLOT = 58          // fallback slot (missing feeders only)
const PAIR_SLOT = 130    // vertical slot per MATCH (pair) in the base column
const PAIR_OFF = 24      // half the centre-to-centre gap of a match's two opponents
// Extra half-gap opened between the two opponents of an IN-PROGRESS match, so
// the running score fits between them. 4 (not more): the pair's grouping
// outline grows by 2*LIVE_SPREAD, and PAIR_SLOT only has ~10px of slack over
// the outline's normal height — at 4 two adjacent live pairs still clear each
// other, at 6 their outlines overlap.
const LIVE_SPREAD = 4
// Reverted the previous 214 (a 25% cut off the ~184px name allotment) back to
// 260 — the narrower width was truncating too many player names.
export const COL_W = 260
// Compact (phone) mode drops the flag AND shrinks further still — the name
// allotment there should be smaller yet, not just re-inherit the 75% cut.
// Narrower than COL_W (was 168, briefly 140) now that compact mode shows
// last-name-only (see lastNameOf below) instead of "F. Last" — widened by
// ~2 characters (140 -> 158) after it came out a bit too tight.
export const COMPACT_COL_W = 158
// Length of the horizontal feeder runs between columns: half goes to the stubs
// out of the two feeding boxes, half to the stub into the box they feed.
// Down from 64, where a two-column compact view came to 2*158 + 64 + 17 = 397px
// and overflowed a 390px phone by just enough to leave the whole draw draggable
// sideways. 44 measures 377 — still inside the screen, with more of the
// connector visible than the 32 this was briefly set to.
export const COL_GAP = 44
export const H2H_X = 8          // H2H chip's x within the gap — centred on the match box's right border
const BELL_OFFSET = 34   // distance (px) the bell sits left of the H2H chip's centre
// Left padding when there's no nav gutter: H2H_X (the chip's centre, 8px past
// the column edge) + half its rotated visual width (9px), rounded up.
const GROUP_CHIP_GUTTER = 20

function Flag({ nat }) {
  const iso2 = nationalityIso2(nat)
  if (!iso2) return <span className="cv-flag cv-flag--empty" />
  return <span className={`fi fi-${iso2.toLowerCase()} cv-flag`} title={nat} />
}

// Mirrors BracketView's TennisBall icon for visual consistency between views.
function TennisBall() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" style={{ display: 'block', flexShrink: 0 }}>
      <circle cx="12" cy="12" r="11" fill="#7ba81f" />
      <g fill="none" stroke="#fff" strokeWidth="2">
        <path d="M12 1A12.04 12.04 0 0 1 1 12" />
        <path d="M12 23A12.04 12.04 0 0 1 23 12" />
      </g>
      <circle cx="12" cy="12" r="11" fill="none" stroke="#1b4332" strokeWidth="2" />
    </svg>
  )
}

function SeedBadge({ player, drawRanks }) {
  if (!player) return null
  const rank = player.seed != null ? player.seed : drawRanks?.[player.id]
  if (rank == null) return null
  return (
    <span className={`pos-badge ${player.seed != null ? 'seeded' : 'unseeded'}`}
      title={player.ranking != null ? `Rank: ${player.ranking}` : undefined}>{rank}</span>
  )
}

function EntryBadge({ player }) {
  if (!player?.entry_type) return null
  return <span className={`pos-badge entry entry-${player.entry_type.toLowerCase()} cv-entry`}>{player.entry_type}</span>
}

// Straight-elbow connectors between two columns of box centres.
function Connectors({ leftCenters, rightCenters, totalH }) {
  const lines = []
  const x1 = 0, xMid = COL_GAP / 2, x2 = COL_GAP
  for (let ri = 0; ri < rightCenters.length; ri++) {
    const r = rightCenters[ri]
    const f1 = leftCenters[ri * 2], f2 = leftCenters[ri * 2 + 1]
    const pts = [f1, f2, r].filter(v => v != null)
    const yMin = Math.min(...pts), yMax = Math.max(...pts)
    if (f1 != null) lines.push(<line key={`a${ri}`} x1={x1} y1={f1} x2={xMid} y2={f1} />)
    if (f2 != null) lines.push(<line key={`b${ri}`} x1={x1} y1={f2} x2={xMid} y2={f2} />)
    if (yMax > yMin) lines.push(<line key={`v${ri}`} x1={xMid} y1={yMin} x2={xMid} y2={yMax} />)
    lines.push(<line key={`r${ri}`} x1={xMid} y1={r} x2={x2} y2={r} />)
  }
  return (
    <svg className="cv-conn" width={COL_GAP} height={totalH} style={{ flexShrink: 0 }}>
      <g stroke="var(--connector-line)" strokeWidth="1.5" fill="none">{lines}</g>
    </svg>
  )
}

// compact: phone-width mode — country flags are dropped to buy name space.
// zoom:    scales the whole rendered draw (layout included, via CSS zoom) so
//          the parent can shrink it until the target number of rounds fits.
export default function CombinedView({ tournament, matches, players, picks, onPick, locked = true, windowStart = 0, windowSize = 4, labelsHidden = false, insetLeft = 0, compact = false, zoom = 1, leagueId = null, lockedMatchIds = new Set(), predictionsHidden = false }) {
  const [h2h, setH2H] = useState(null)
  // Completed match whose predictors popup is open (the group chip's target).
  const [predictorsMatch, setPredictorsMatch] = useState(null)
  // Hovering any box of a player highlights ALL that player's boxes across
  // the bracket (ported from BracketView's hoveredPlayerId behaviour).
  const [hoveredPlayerId, setHoveredPlayerId] = useState(null)
  const colW = compact ? COMPACT_COL_W : COL_W

  const playerById = Object.fromEntries(players.map(p => [p.id, p]))
  const drawRanks = computeDrawRanks(players)

  // Number unplaced Q slots by bracket position: Qualifier 1, Qualifier 2, …
  // (mirror of BracketView so the Combined view labels them identically)
  const qualifierNums = {}
  players
    .filter(p => p.entry_type === 'Q' && !p.name)
    .sort((a, b) => a.bracket_position - b.bracket_position)
    .forEach((p, i) => { qualifierNums[p.id] = i + 1 })

  // Compact (phone) mode: last name only, EXCEPT for players who share a last
  // name with someone else in this draw — those keep the "F. Last" format so
  // they stay distinguishable. lastNameOf mirrors abbrevName's "everything
  // after the first token" so two-word surnames (e.g. "Carreño Busta") stay
  // together, matching how the app already defines "last name" elsewhere.
  const lastNameOf = (full) => {
    const parts = full.trim().split(/\s+/)
    return parts.length > 1 ? parts.slice(1).join(' ') : parts[0]
  }
  const lastNameCounts = {}
  if (compact) {
    for (const pl of players) {
      if (!pl.name) continue
      const last = lastNameOf(pl.name)
      lastNameCounts[last] = (lastNameCounts[last] || 0) + 1
    }
  }

  const isUnnamedQ = (p) => p?.entry_type === 'Q' && !p.name
  const slotName = (p, abbrev) => {
    if (!p) return 'TBD'
    if (isUnnamedQ(p)) {
      const n = qualifierNums[p.id]
      return `Qualifier${n != null ? ` ${n}` : ''}`
    }
    if (compact) {
      const last = lastNameOf(p.name)
      return lastNameCounts[last] > 1 ? abbrevName(p.name) : last
    }
    return abbrev ? abbrevName(p.name) : p.name
  }

  // Rounds (arrays of matches, sorted by match_number)
  const byRound = {}
  for (const m of matches) (byRound[m.round_number] ||= []).push(m)
  const roundNums = Object.keys(byRound).map(Number).sort((a, b) => a - b)
  const R = roundNums.map(rn => [...byRound[rn]].sort((a, b) => a.match_number - b.match_number))
  const N = R.length
  if (N === 0) return null

  const resolved = resolveCombinedPlayers(matches, picks)

  // The H2H panel reads real entrants first, so it never compares two players
  // who did not actually meet — see resolveRealFirst. The bracket itself keeps
  // using `resolved`, which is what the user picked.
  const h2hResolved = resolveRealFirst(matches, resolved)
  const h2hSeq = buildH2HSequence(matches, h2hResolved, playerById)
  const h2hNav = h2hNeighbours(h2hSeq, h2h?.match?.id)
  const matchIndex = buildMatchIndex(matches)

  // Round each player was actually eliminated in (real results only) — a pick
  // of that player as the winner of that round or any later one is a dead
  // pick, shown wrong immediately rather than waiting for the picked match
  // itself to be played (mirrors BracketView's lossRound handling).
  const lossRound = {}
  for (const m of matches) {
    const wid = m.winner?.id
    if (wid == null || m.is_bye) continue
    const loserId = m.player1?.id === wid ? m.player2?.id : m.player1?.id
    if (loserId != null) lossRound[loserId] = m.round_number
  }

  const totalCols = N + 1
  const size = Math.min(windowSize, totalCols)
  const maxStart = Math.max(0, totalCols - size)
  const start = Math.min(Math.max(0, windowStart), maxStart)
  const visible = Array.from({ length: size }, (_, i) => start + i)

  const colCount = (c) => (c === 0 ? 2 * R[0].length : R[c - 1].length)

  // Feeder-centred vertical layout for the visible columns. The left-most (base)
  // column pairs each match's two opponents tightly (small within-pair gap,
  // larger gap between matches); columns to its right centre on their feeders.
  const centers = {}
  visible.forEach((c, p) => {
    const count = colCount(c)
    if (p === 0) {
      centers[c] = []
      const nPairs = Math.ceil(count / 2)
      for (let pi = 0; pi < nPairs; pi++) {
        const mc = pi * PAIR_SLOT + PAIR_SLOT / 2
        const hasSecond = 2 * pi + 1 < count
        centers[c].push(hasSecond ? mc - PAIR_OFF : mc)
        if (hasSecond) centers[c].push(mc + PAIR_OFF)
      }
    } else {
      const prev = centers[visible[p - 1]]
      centers[c] = Array.from({ length: count }, (_, i) => {
        const a = prev[2 * i], b = prev[2 * i + 1]
        if (a != null && b != null) return (a + b) / 2
        return a ?? (i * SLOT + SLOT / 2)
      })
    }
  })
  const totalH = Math.ceil(colCount(visible[0]) / 2) * PAIR_SLOT
  // Natural (unscaled) footprint of the labels+body block, for the
  // scale-to-fit wrapper below. LABELS_H is an estimate of .cv-labels'
  // rendered height (padding + line height) — a few px of slop here just
  // means a few px of extra/short scroll space, not a visual bug.
  // TRAILING_W accounts for the H2H chip in the last visible column's
  // trailing stub (feeding the next, not-yet-shown round) — real, clickable
  // content, so it counts toward the footprint. The REST of that stub's
  // connector line (reaching to where the next column's box would start) is
  // decorative only, so it deliberately does NOT get a full COL_GAP credit
  // here — in compact mode that lets the zoom-fit target (TournamentDraw.jsx)
  // sit tighter, with the unneeded tail of the line simply overflowing off
  // the viewport edge instead of reserving dead space for it.
  const TRAILING_W = H2H_X + 9 // chip's right edge: its centre (H2H_X into the gap) + half its rotated visual width (height:18 -> 9)
  const naturalW = visible.length * colW + (visible.length - 1) * COL_GAP + TRAILING_W
  const LABELS_H = 34
  const naturalH = totalH + LABELS_H

  // Centres for the column just PAST the visible window (if one exists) — used
  // only to draw the trailing feed bars (connectors + H2H + bell) off the
  // right-most visible column. Its box column itself is never rendered.
  const afterC = visible[visible.length - 1] + 1
  let afterCenters = null
  if (afterC <= N) {
    const count = colCount(afterC)
    const prev = centers[visible[visible.length - 1]]
    afterCenters = Array.from({ length: count }, (_, i) => {
      const a = prev[2 * i], b = prev[2 * i + 1]
      if (a != null && b != null) return (a + b) / 2
      return a ?? (i * SLOT + SLOT / 2)
    })
  }

  // A live match prints its running score in the gap between its two
  // opponents, so open that pair up a little to make room. Applied LAST, after
  // every column (and afterCenters) has been derived, and symmetrically about
  // the pair's midpoint — which is exactly what the next column's box centre,
  // its H2H chip and the connector fan all key off, so none of them shift.
  // Only the live pair itself moves, and only by LIVE_SPREAD each way.
  visible.forEach((c) => {
    const cc = centers[c]
    R[c]?.forEach((m, ri) => {
      const a = 2 * ri, b = 2 * ri + 1
      if (!isLiveMatch(m) || cc[a] == null || cc[b] == null) return
      cc[a] -= LIVE_SPREAD
      cc[b] += LIVE_SPREAD
    })
  })

  // ---- box builders -------------------------------------------------------
  // Clicking a box picks ITS player as the predicted winner of the match they
  // feed into next (one column to the right) — e.g. clicking a player shown
  // in the "Round of 16" column (having won R32, about to play R16) predicts
  // them to win THAT match and advance into the Quarterfinals column. Column
  // c's box i always feeds match R[c][floor(i/2)]. The Champion column (c===N)
  // has no further match, so it's never clickable.
  function nextMatchOnClick(c, i, playerId) {
    if (locked || !onPick || playerId == null || c >= N) return null
    const nextMatch = R[c][Math.floor(i / 2)]
    if (!nextMatch) return null
    // Clicking a player picks them in the NEXT match, so it is that match's
    // lock that decides — not the one they are standing in.
    if (lockedMatchIds.has(nextMatch.id)) return null
    return () => onPick(nextMatch.id, playerId)
  }

  // Is the player in column c, row i currently serving? Their live match is
  // the one they feed into next — R[c][floor(i/2)] — and their slot in it is
  // p1 (even i, top) or p2 (odd i, bottom), same convention used everywhere
  // else (entrantBox, centers pairing). live_scores[2] is 1 or 2 for p1/p2.
  function isServing(c, i) {
    if (c >= N) return false
    const nextMatch = R[c][Math.floor(i / 2)]
    if (!nextMatch?.live_scores) return false
    const wantSlot = i % 2 === 0 ? 1 : 2
    return nextMatch.live_scores[2] === wantSlot
  }

  function entrantBox(c, i) {
    const match = R[0][Math.floor(i / 2)]
    // Which line of a bye match the player occupies is not in the source data
    // — Wikipedia lists a bye'd seed only in round 2 — so it is decided here.
    // ATP rulebook 7.16 fixes the seed lines (1, 8, 9, 16 … 121, 128 for a 96
    // draw) and 7.18 gives every seed a bye, which puts the seed on the OUTER
    // line of its first-round match: line 1 in match 1, line 8 in match 4,
    // line 128 in match 64. Seed lines are always ≡ 0 or 1 (mod 4), and an odd
    // line is ≡1 only in odd-numbered matches while an even line is ≡0 only in
    // even-numbered ones — so match parity alone decides it. Half the byes sit
    // below their bye, including the #2 seed's line at the very bottom.
    // Display order only: bracket_position is untouched, so no pick moves.
    const playerSlot = match.is_bye && match.match_number % 2 === 0 ? 1 : 0
    const pid = match.is_bye
      ? (i % 2 === playerSlot ? match.player1?.id ?? null : null)
      : (i % 2 === 0 ? match.player1?.id : match.player2?.id)
    const player = pid != null ? playerById[pid] : null
    const isBye = match.is_bye && i % 2 !== playerSlot
    // A bye match has no real outcome to predict — neither the bye
    // placeholder slot (isBye, handled above) NOR the opponent's own slot
    // should be clickable, so a click can never save a redundant "pick"
    // for a match that was always going to auto-advance regardless.
    const onClick = match.is_bye ? null : nextMatchOnClick(0, i, pid)
    return { key: `e${i}`, player, isBye, serving: !isBye && isServing(0, i), abbrev: true, kind: 'entrant', clickable: !!onClick, onClick }
  }

  function winnerBox(c, i) {
    const match = R[c - 1][i]
    const realId = match.winner?.id ?? null
    const pickId = picks?.[match.id] ?? null
    const displayId = pickId ?? realId
    const player = displayId != null ? playerById[displayId] : null
    const correct = pickId != null && realId != null && pickId === realId
    // Wrong when the real winner disagrees — or when the picked player has
    // already been eliminated in this round or earlier (dead pick), even
    // though this match itself hasn't been played yet.
    const deadPick = pickId != null && lossRound[pickId] != null
      && lossRound[pickId] <= match.round_number
    const wrong = pickId != null && ((realId != null && pickId !== realId) || deadPick)
    const realPlayer = realId != null ? playerById[realId] : null
    // A live match's score belongs to the match's OWN box group (drawn between
    // its two opponents), not under the box holding its eventual winner — so
    // nothing is shown here until the match is decided and match.scores lands.
    const score = match.is_bye || isLiveMatch(match) ? null : scoreNodes(match.scores)

    const onClick = nextMatchOnClick(c, i, displayId)

    return {
      key: `w${match.id}`, player, correct, wrong, score, serving: isServing(c, i),
      realName: wrong && realPlayer ? abbrevName(realPlayer.name) : null,
      realFullName: wrong && realPlayer ? realPlayer.name : null,
      match, abbrev: true, kind: 'winner', clickable: !!onClick, onClick,
    }
  }

  const colX = (idx) => idx * (colW + COL_GAP)

  return (
    <>
      {h2h && (
        <H2HPanel
          slug1={h2h.p1.te_slug} slug2={h2h.p2.te_slug}
          player1={h2h.p1} player2={h2h.p2}
          tournSurface={tournament?.surface} tournGender={tournament?.gender}
          beforeDrawId={tournament?.id} beforeRound={h2h.match?.round_number}
          match={h2h.match}
          matchOrder={matchIndex.order}
          matchTotal={matchIndex.total}
          picks={picks}
          onPick={onPick}
          canPick={!locked}
          onPrev={h2hNav.prev ? () => setH2H(h2hNav.prev) : null}
          onNext={h2hNav.next ? () => setH2H(h2hNav.next) : null}
          onClose={() => setH2H(null)}
        />
      )}
      {predictorsMatch && (
        <PredictorsPopup
          drawId={tournament?.id}
          match={predictorsMatch}
          leagueId={leagueId}
          onClose={() => setPredictorsMatch(null)}
        />
      )}
      {/* insetLeft's caller (NAV_INSET) is already tuned tight to the nav
          button's own footprint — stacking the full 0.75rem base padding on
          top of it left a visibly wide gap; a few px is enough breathing
          room between the button and the first box. */}
      {/* Left padding has to clear the group chip, which is centred on the
          leftmost column's outline border and so overhangs it by 8px + half
          the chip's rotated width (9px). Overflow to the LEFT of a scroll
          container's content origin can't be scrolled to, it's simply clipped,
          so without this the first column's chips lose their left edge. When
          the nav gutter is present its own inset is already wider than that. */}
      <div className={`cv-scroll${compact ? ' cv-scroll--compact' : ''}`} style={{ paddingLeft: insetLeft ? `${insetLeft + 4}px` : `${GROUP_CHIP_GUTTER}px` }}>
        {/* Scale-to-fit: outer claims the SMALLER (zoomed) footprint so
            .cv-scroll's scrollWidth shrinks with it (needed for 2 rounds to
            fit a narrow phone without horizontal scrolling); inner renders at
            natural size and transform:scale()s down to exactly fill it.
            transform, not the CSS `zoom` property — WebKit doesn't reliably
            cascade `zoom` into descendants that establish their own
            positioning/formatting context (position:absolute, overflow,
            flex, ...), which are exactly the properties nearly every element
            in this bracket uses; transform:scale has been identically
            supported everywhere for well over a decade. */}
        {/* No overflow clipping here (tried overflow-x:hidden — reverted: it
            also clipped the FIRST column's .cv-match-outline, which extends
            -8px past its own column on the left, an intentional overhang not
            a bug; and clipping the trailing connector line mid-stroke made
            it visibly fade to white rather than cleanly disappear, which
            reads as broken, not "cropped"). naturalW still excludes the
            decorative tail past the H2H chip so drawZoom sizes tighter, but
            the actual pixels are simply allowed to overflow past the
            declared box uncropped — same tradeoff as the LABELS_H estimate
            below: a few px of harmless overflow beats a clipping artifact. */}
        <div style={zoom !== 1 ? { width: naturalW * zoom, height: naturalH * zoom } : undefined}>
        <div style={zoom !== 1 ? { width: naturalW, height: naturalH, transform: `scale(${zoom})`, transformOrigin: 'top left' } : undefined}>
        <div className={`cv-labels${labelsHidden ? ' cv-labels--collapsed' : ''}`}>
          {visible.map((c, i) => {
            const label = c === 0
              ? (R[0][0]?.round_name || 'Round 1')
              : c < N ? (R[c][0]?.round_name || `Round ${c + 1}`) : 'Champion'
            return (
              <div key={c} style={{ display: 'flex', flexShrink: 0 }}>
                <div className="cv-label" style={{ width: colW }}>{label}</div>
                {i < visible.length - 1 && <div style={{ width: COL_GAP }} />}
              </div>
            )
          })}
        </div>

        <div className="cv-body" style={{ height: totalH }}>
          {visible.map((c, colIdx) => {
            const count = colCount(c)
            const cc = centers[c]

            // Interior gap: feeds the next VISIBLE column. Trailing stub: the
            // right-most visible column still gets its feed bars (connectors,
            // H2H, bell) pointing at the next column's slot, even though that
            // column's boxes aren't rendered (out of the window). Computed here
            // (rather than inside the gap IIFE below) so the missing-pick outline,
            // which is drawn inside cv-col, can also key off the match it feeds.
            const isLastVisible = colIdx === visible.length - 1
            const nextC = isLastVisible ? afterC : visible[colIdx + 1]
            const nextCenters = isLastVisible ? afterCenters : centers[nextC]

            return (
              <div key={c} style={{ display: 'flex', flexShrink: 0 }}>
                <div className="cv-col" style={{ width: colW, height: totalH }}>
                  {/* Light grey box grouping every match's two feeder boxes together;
                      switches to red once both opponents are known but the user
                      hasn't picked a winner yet (mirrors BracketView's "missing-pick"
                      outline in Picks mode). Rendered first so it sits behind the
                      player boxes. */}
                  {nextC >= 1 && nextC - 1 < R.length && R[nextC - 1].map((m, ri) => {
                    const yTop = cc[2 * ri], yBot = cc[2 * ri + 1]
                    if (yTop == null || yBot == null) return null
                    const { p1: aId, p2: bId } = resolved[m.id] || {}
                    const isMissingPick = !locked && aId != null && bId != null && picks?.[m.id] == null
                    // Top pad clears the "real winner" note (now centred on the
                    // TOP box's own top border, so it barely pokes above it);
                    // bottom pad clears the score line below the BOTTOM box.
                    // Scores only render when colIdx > 0 (see the box.score
                    // line below) — i.e. whichever column is currently the
                    // LEFTMOST visible pane never shows one, regardless of its
                    // absolute round — so the outline must key off colIdx, not c.
                    const topPad = 12
                    const bottomPad = colIdx === 0 ? 12 : 28
                    const top = Math.min(yTop, yBot) - BOX_H / 2 - topPad
                    const height = Math.abs(yBot - yTop) + BOX_H + topPad + bottomPad
                    const isSuspended = m.live_scores?.[4] === 'suspended'
                    const isLive = isLiveMatch(m)
                    return (
                      <Fragment key={`mo${m.id}`}>
                        <div
                          className={`cv-match-outline${isMissingPick ? ' cv-match-outline--missing' : ''}`}
                          style={{ top, height }}
                        />
                        {isLive && (
                          <span className={`in-progress-badge${isSuspended ? ' in-progress-badge--suspended' : ''}`} style={{ position: 'absolute', top, left: '50%', transform: 'translate(-50%, -50%)' }}>
                            {isSuspended ? 'Suspended' : 'In Progress'}
                          </span>
                        )}
                        {/* Running score, centred in the gap the LIVE_SPREAD
                            nudge opened between this match's two opponents.
                            Sized to fill that gap; the --sN modifier steps the
                            type down once a score is long enough to threaten
                            the column's width (see CombinedView.css — 2 and 3
                            sets share a size, since 3 sets fits at full size
                            everywhere but compact). */}
                        {isLive && (() => {
                          const nodes = liveScoreNodes(m.live_scores)
                          if (!nodes) return null
                          return (
                            <span
                              className={`cv-live-score cv-live-score--s${Math.min(nodes.length, 4)}${isSuspended ? ' cv-live-score--suspended' : ''}`}
                              style={{ top: (yTop + yBot) / 2 }}
                            >
                              {nodes}
                            </span>
                          )
                        })()}
                      </Fragment>
                    )
                  })}

                  {Array.from({ length: count }, (_, i) => {
                    const box = c === 0 ? entrantBox(c, i) : winnerBox(c, i)
                    const p = box.player
                    return (
                      <div key={box.key} className="cv-slot" style={{ top: cc[i] }}>
                        <div
                          className={`cv-box${box.isBye ? ' cv-box--bye' : ''}${!box.isBye && !p ? ' cv-box--tbd' : ''}${box.correct ? ' cv-box--correct' : ''}${box.wrong ? ' cv-box--wrong' : ''}${box.clickable ? ' cv-box--clickable' : ''}${p != null && p.id === hoveredPlayerId ? ' cv-box--highlight' : ''}`}
                          onClick={box.onClick}
                          onMouseEnter={p != null ? () => setHoveredPlayerId(p.id) : undefined}
                          onMouseLeave={p != null ? () => setHoveredPlayerId(null) : undefined}
                        >
                          {box.isBye ? (
                            <span className="cv-name cv-name--muted">BYE</span>
                          ) : (
                            <>
                              <span className="cv-badges"><SeedBadge player={p} drawRanks={drawRanks} /></span>
                              {!compact && <Flag nat={p?.nationality} />}
                              <span className={`cv-name${isUnnamedQ(p) ? ' cv-name--muted' : ''}`} title={p?.nationality ? `${p.name} (${p.nationality})` : (p?.name || undefined)}>
                                {slotName(p, box.abbrev)}
                              </span>
                              {box.serving && <span className="cv-serving" title="Serving"><TennisBall /></span>}
                              <EntryBadge player={p} />
                            </>
                          )}
                        </div>
                        {/* Rendered AFTER cv-box so it paints on top; the box's own
                            top border is removed for wrong picks (see .cv-box--wrong)
                            so it never shows through underneath this label. */}
                        {box.realName && <div className="cv-real-winner" title={box.realFullName || undefined}>{box.realName}</div>}
                        {colIdx > 0 && box.score && <div className="cv-score">{box.score}</div>}
                      </div>
                    )
                  })}
                </div>

                {(() => {
                  if (!nextCenters) return null
                  return (
                    <div className="cv-gap" style={{ width: COL_GAP, height: totalH, position: 'relative' }}>
                      <Connectors leftCenters={cc} rightCenters={nextCenters} totalH={totalH} />
                    </div>
                  )
                })()}
              </div>
            )
          })}

          {/* H2H chips + upset bells, rendered as ONE overlay that's the last
              child of cv-body — painted after (on top of) every column, so
              they're never subject to a column's own stacking level (which is
              what keeps each connector line tucked behind its box edges). */}
          <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
            {visible.map((c, colIdx) => {
              const isLastVisible = colIdx === visible.length - 1
              const nextC = isLastVisible ? afterC : visible[colIdx + 1]
              const nextCenters = isLastVisible ? afterCenters : centers[nextC]
              if (!nextCenters || nextC < 1) return null
              const gapX = colIdx * (colW + COL_GAP) + colW
              return nextCenters.map((y, ri) => {
                const m = R[nextC - 1][ri]
                const { p1: aId, p2: bId } = resolved[m.id] || {}
                const a = aId != null ? playerById[aId] : null
                const b = bId != null ? playerById[bId] : null
                // H2H compares who really played; the bell below stays on the
                // cascade, since it is about the user's pick, not the result.
                const { p1: hAId, p2: hBId } = h2hResolved[m.id] || {}
                const ha = hAId != null ? playerById[hAId] : null
                const hb = hBId != null ? playerById[hBId] : null
                const pickId = picks?.[m.id] ?? null
                const rankA = aId != null ? drawRanks[aId] : null
                const rankB = bId != null ? drawRanks[bId] : null
                const expectedId = rankA != null && rankB != null ? (rankA <= rankB ? aId : bId) : null
                const isUpsetPick = pickId != null && expectedId != null && pickId !== expectedId
                return (
                  <Fragment key={m.id}>
                    {/* Both opponents known is the bar, not TE coverage — a
                        player we have not matched to Tennis Explorer must not
                        take the button away from a real match. */}
                    {ha?.name && hb?.name && (
                      <button
                        className="cv-h2h"
                        style={{ top: y, left: gapX + H2H_X, pointerEvents: 'auto' }}
                        title={`Head-to-head: ${ha.name} vs ${hb.name}`}
                        onClick={() => setH2H({ p1: ha, p2: hb, match: m })}
                      >
                        H2H
                      </button>
                    )}
                    {/* Group chip: same pill as H2H, on the match outline's
                        LEFT border instead of its right (the outline overhangs
                        its column by 8px each side, which is what H2H_X
                        centres on). Completed matches only — an undecided
                        match has no outcome to have been right about. */}
                    {/* Hidden entirely while other players' picks are withheld
                        (a draw whose picks stay editable after the first ball).
                        The popup would open onto "0 / 0 / Nobody", which reads
                        as "nobody predicted this" rather than "not shown yet" —
                        a wrong answer is worse than no button. */}
                    {m.winner?.id != null && !m.is_bye && !predictionsHidden && (
                      <button
                        className="cv-group"
                        style={{ top: y, left: colIdx * (colW + COL_GAP) - H2H_X, pointerEvents: 'auto' }}
                        title={`Who predicted ${m.winner.name}?`}
                        aria-label={`Who predicted ${m.winner.name}?`}
                        onClick={() => setPredictorsMatch(m)}
                      >
                        <GroupIcon />
                      </button>
                    )}
                    {isUpsetPick && (
                      <UpsetBell style={{ top: y, left: gapX + H2H_X - BELL_OFFSET, pointerEvents: 'auto' }} />
                    )}
                  </Fragment>
                )
              })
            })}
          </div>
        </div>
        </div>
        </div>
      </div>
    </>
  )
}
