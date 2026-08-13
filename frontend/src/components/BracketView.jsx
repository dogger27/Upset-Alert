/**
 * BracketView — full tournament bracket.
 *
 * mode="picks"  (default) — cascade from user picks; no scores; orange when a
 *                           player slot is TBD (user hasn't picked far enough).
 * mode="live"             — cascade from actual match results; scores shown; no orange.
 *
 * Both modes colour the whole match cell green (correct pick) or red (wrong pick).
 */

import { useState, useRef } from 'react'
import { createPortal } from 'react-dom'
import clsx from 'clsx'
import H2HPanel from './H2HPanel'
import { buildH2HSequence, buildMatchIndex, h2hNeighbours, resolveRealFirst } from '../utils/h2hSequence'
import './BracketView.css'

// IOC 3-letter → ISO 2-letter for flag emoji generation
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

function computeDrawRanks(players) {
  const ranks = {}
  const seeded = players.filter(p => p.seed != null)
  for (const p of seeded) ranks[p.id] = p.seed

  // Sort unseeded by world ranking, then assign sequential relative ranks after the seeds.
  // Offset = highest seed number present (not count), so withdrawn seeds don't cause collisions.
  const unseeded = players
    .filter(p => p.seed == null)
    .sort((a, b) => {
      if (a.ranking != null && b.ranking != null) return a.ranking - b.ranking
      if (a.ranking != null) return -1
      if (b.ranking != null) return 1
      return a.bracket_position - b.bracket_position
    })
  const offset = seeded.reduce((max, p) => Math.max(max, p.seed), 0)
  unseeded.forEach((p, i) => { ranks[p.id] = offset + i + 1 })
  return ranks
}

const MATCH_H = 58
const LABEL_H = 30
const SLOT_BASE = 74
export const COL_W = 252
export const COL_W_SCORES = 300
// Horizontal feeder length between columns — shortened from 24 alongside
// CombinedView's, to buy back width on a phone. Nothing is seated in this gap
// (BracketView's H2H strip lives inside the match box), so it only shortens the
// connector runs.
export const COL_GAP = 18



function resolveMatchPlayers(matches, picks, mode) {
  const byKey = {}
  for (const m of matches) byKey[`${m.round_number}:${m.match_number}`] = m

  const resolved = {}

  function getWinner(m) {
    if (!m) return null
    if (mode === 'live') return m.winner?.id ?? null
    if (m.is_bye) return m.player1?.id ?? null  // bye winner needs no pick
    return picks[m.id] ?? null
  }

  function resolve(m) {
    if (resolved[m.id]) return resolved[m.id]

    // In picks mode, R2+ slots must come entirely from the picks cascade —
    // the DB already stores actual match results in player1/player2 for
    // completed rounds, which would otherwise override the user's picks.
    const useDb = mode === 'live' || m.round_number === 1
    let p1id = useDb ? (m.player1?.id ?? null) : null
    let p2id = useDb ? (m.player2?.id ?? null) : null

    if (m.round_number > 1) {
      const f1 = byKey[`${m.round_number - 1}:${m.match_number * 2 - 1}`]
      const f2 = byKey[`${m.round_number - 1}:${m.match_number * 2}`]
      if (f1) resolve(f1)
      if (f2) resolve(f2)
      if (p1id == null) p1id = f1 ? getWinner(f1) : null
      if (p2id == null) p2id = f2 ? getWinner(f2) : null
    }
    resolved[m.id] = { p1: p1id, p2: p2id }
    return resolved[m.id]
  }

  for (const m of matches) resolve(m)
  return resolved
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

// Serving indicator. The two seams are point-symmetric circular arcs: one from
// the ball's top point to its left point, one from its bottom to its right,
// each bowing AWAY from the corner between its endpoints (centres of curvature
// at the box's top-left / bottom-right corners, hence r == the corner-to-
// endpoint distance of 12.04). That is real tennis-ball seam geometry — the
// previous pair of shallow horizontal curves read as an eye, not a ball.
// The dark green rim is stroked LAST so it trims both seams flush at the edge
// and separates the ball from the pale box behind it.
function TennisBall() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" style={{ display: 'block', flexShrink: 0 }}>
      <circle cx="12" cy="12" r="11" fill="#7ba81f"/>
      <g fill="none" stroke="#fff" strokeWidth="2">
        <path d="M12 1A12.04 12.04 0 0 1 1 12"/>
        <path d="M12 23A12.04 12.04 0 0 1 23 12"/>
      </g>
      <circle cx="12" cy="12" r="11" fill="none" stroke="#1b4332" strokeWidth="2"/>
    </svg>
  )
}

function ScoreCell({ val, bold }) {
  if (!val) return <span className="score-cell empty">·</span>
  const clean = val.replace(/r$/i, '')
  const tb = clean.match(/^(\d+)\((\d+)\)$/)
  const style = bold ? { fontWeight: 700 } : undefined
  if (tb) return (
    <span className="score-cell tb" style={style}>{tb[1]}<sup>{tb[2]}</sup></span>
  )
  return <span className="score-cell" style={style}>{clean}</span>
}

function hasRetirement(scores) {
  if (!scores) return { p1: false, p2: false }
  const check = (arr) => arr?.some(s => /r$/i.test(s)) ?? false
  return { p1: check(scores[0]), p2: check(scores[1]) }
}

/* A walkover — the loser withdrew before a ball was struck — is stored the way
   Wikipedia writes it: the withdrawing side's only score cell is the literal
   "w/o", the winner's is empty. So there are no games to render, and a match
   that was never played still has to say what happened to it.

   Marked on the side that carries the "w/o", which is the player who withdrew,
   matching where the retirement badge sits. */
const WALKOVER_RE = /^w\/?o$/i

function hasWalkover(scores) {
  if (!scores) return { p1: false, p2: false }
  const check = (arr) => arr?.some(v => WALKOVER_RE.test(String(v ?? '').trim())) ?? false
  return { p1: check(scores[0]), p2: check(scores[1]) }
}

function PlayerRow({
  playerId, playerById, drawRanks,
  isPicked, isWinner, isEliminated, isProjected, isDeadPick,
  scores, retired, walkover, onClick, locked,
  showTypeSlot, showScores, markWinner, showRowBg, showFlag,
  qualifierNum, isServing, boldScores,
  isHighlighted, onHover,
}) {
  const player = playerId != null ? playerById[playerId] : null

  let leftBadge = null
  let typeBadge = null

  if (player) {
    const rank = drawRanks?.[player.id]
    const rankTitle = player.ranking != null ? `Rank: ${player.ranking}` : undefined
    if (player.seed != null) {
      leftBadge = <span className="pos-badge seeded" title={rankTitle}>{player.seed}</span>
    } else if (rank != null) {
      leftBadge = <span className="pos-badge unseeded" title={rankTitle}>{rank}</span>
    }

    if (player.entry_type) {
      typeBadge = (
        <span className={`pos-badge entry entry-${player.entry_type.toLowerCase()}`}>
          {player.entry_type}
        </span>
      )
    }
  }

  if (!player || (player.entry_type === 'Q' && !player.name)) {
    const isQ = player?.entry_type === 'Q'
    const label = isQ ? `Qualifier${qualifierNum != null ? ` ${qualifierNum}` : ''}` : 'TBD'
    const isClickable = isQ && !locked && onClick
    return (
      <div
        className={clsx('player-row', { picked: isQ && isPicked, clickable: isClickable })}
        onClick={isClickable ? onClick : undefined}
      >
        <span className="badge-left-slot" />
        {showTypeSlot && <span className="badge-type-slot" />}
        <span className="pname muted">{label}</span>
      </div>
    )
  }

  const correctPick = isPicked && isWinner
  const wrongPick = isPicked && isEliminated
  const showTick = correctPick || (markWinner && isWinner)

  return (
    <div
      className={clsx('player-row', {
        picked: !markWinner && isPicked,
        winner: markWinner && isWinner,
        eliminated: isEliminated && showRowBg,
        'wrong-pick': wrongPick,
        'dead-pick': isDeadPick,
        projected: isProjected && !isWinner,
        clickable: !locked && onClick,
        highlight: isHighlighted,
        // Independent of `picked` (which is suppressed in live mode) — the
        // user's own pick should always render in black text, even in a
        // live/not-yet-started match where `picked`'s other styling doesn't apply.
        'pick-choice': isPicked,
      })}
      onClick={!locked && onClick ? onClick : undefined}
      onMouseEnter={onHover ? () => onHover(player.id) : undefined}
      onMouseLeave={onHover ? () => onHover(null) : undefined}
      title={player.nationality ? `${player.name} (${player.nationality})` : player.name}
    >
      <span className="badge-left-slot">{leftBadge}</span>
      {showTypeSlot && <span className="badge-type-slot">{typeBadge}</span>}
      <span className="pname">{player.name}</span>
      {isServing && <TennisBall />}
      {retired && <span className="ret-badge">ret.</span>}
      {walkover && <span className="ret-badge wo-badge">w/o</span>}
      {showTick && <span className="pick-result correct" title={correctPick ? 'Correct pick' : 'Winner'}>✓</span>}
      {wrongPick && <span className="pick-result wrong" title="Wrong pick">✗</span>}
      {showFlag && player.nationality && (() => {
        const iso2 = nationalityIso2(player.nationality)
        return iso2
          ? <span className={`fi fi-${iso2.toLowerCase()} player-flag`} title={player.nationality} />
          : null
      })()}
      {showScores && scores && scores.length > 0 && (
        <span className="score-row">
          {scores.map((s, i) => <ScoreCell key={i} val={s} bold={boldScores?.has(i)} />)}
        </span>
      )}
    </div>
  )
}

function playerNeedsTypeSlot(p) {
  return !!p?.entry_type
}

function MatchBox({ match, resolvedPlayers, h2hPair, playerById, drawRanks, picks, onPick, locked, style, mode, lossRound, onH2H, qualifierNums, forceTypeSlot, hoveredPlayerId, onHoverPlayer }) {
  const { p1: p1id, p2: p2id } = resolvedPlayers || { p1: match.player1?.id, p2: match.player2?.id }
  const pickedId = picks[match.id]
  const actualWinnerId = match.winner?.id

  const bellRef = useRef(null)
  const [tipPos, setTipPos] = useState(null)

  // "Projected" italic only applies in live mode (slot filled by cascade, not yet official)
  const p1IsProjected = mode === 'live' && !match.player1 && p1id != null
  const p2IsProjected = mode === 'live' && !match.player2 && p2id != null

  // Dead pick: player appears here (via picks cascade) but already lost in an earlier round
  const p1DeadPick = mode === 'picks' && p1id != null && lossRound[p1id] != null && lossRound[p1id] < match.round_number
  const p2DeadPick = mode === 'picks' && p2id != null && lossRound[p2id] != null && lossRound[p2id] < match.round_number

  const isLive = match.live_scores != null
  const isSuspended = match.live_scores?.[4] === 'suspended'
  // Live scores take priority; final scores shown only in live mode
  const scores = isLive ? match.live_scores : match.scores
  const p1Scores = scores?.[0] ?? null
  const p2Scores = scores?.[1] ?? null
  const ret = hasRetirement(match.scores)  // retirement markers only on final scores
  const wo = hasWalkover(match.scores)
  const isWalkover = wo.p1 || wo.p2

  // Serving ball: live_scores[2] is 1 (p1 serving) or 2 (p2) or null
  // Suppress during tiebreaks: both players' last game count is "6" → 6-6 in current set
  const servingPlayer = isLive ? (match.live_scores?.[2] ?? null) : null
  const inTiebreak = isLive && p1Scores?.length > 0 && p2Scores?.length > 0 &&
    p1Scores[p1Scores.length - 1] === '6' && p2Scores[p2Scores.length - 1] === '6'
  const p1Serving = servingPlayer === 1 && !inTiebreak
  const p2Serving = servingPlayer === 2 && !inTiebreak

  // Bold completed set scores for the winner of each set
  // live_scores[3] is [true/false/null, ...] from p1's perspective
  const setWinners = isLive ? (match.live_scores?.[3] ?? null) : null
  const p1BoldScores = setWinners ? new Set(setWinners.flatMap((w, i) => w === true  ? [i] : [])) : null
  const p2BoldScores = setWinners ? new Set(setWinners.flatMap((w, i) => w === false ? [i] : [])) : null


  const p1 = p1id != null ? playerById[p1id] : null
  const p2 = p2id != null ? playerById[p2id] : null
  const showTypeSlot = forceTypeSlot || playerNeedsTypeSlot(p1) || playerNeedsTypeSlot(p2)
  const showScores = mode === 'live'

  // H2H strip: both opponents must be known (works in live and picks mode).
  // Deliberately NOT gated on te_slug — an unmatched player would otherwise
  // take the button away from a match that is actually being played. See
  // buildH2HSequence.
  // H2H opens on the players who really met, not on the picks cascade — the
  // bracket around it still shows the cascade. See resolveRealFirst.
  const h2hP1 = h2hPair?.p1 != null ? playerById[h2hPair.p1] : p1
  const h2hP2 = h2hPair?.p2 != null ? playerById[h2hPair.p2] : p2
  const h2hAvailable = !!h2hP1?.name && !!h2hP2?.name

  // Upset: lower-ranked player won (picks mode: user's pick; live mode: actual result)
  const rank1 = drawRanks[p1id] ?? Infinity
  const rank2 = drawRanks[p2id] ?? Infinity
  const expectedWinnerId = rank1 <= rank2 ? p1id : p2id
  const bothKnown = p1id != null && p2id != null
  const isUpsetPick = bothKnown && (
    mode === 'picks'
      ? pickedId != null && pickedId !== expectedWinnerId
      : actualWinnerId != null && actualWinnerId !== expectedWinnerId
  )

  if (match.is_bye) {
    // Seed on the outer line of its match, bye on the inner one — see the
    // note in CombinedView.entrantBox for the ATP 7.16/7.18 derivation.
    // Even-numbered first-round matches put the seed BELOW the bye, which is
    // what places the #2 seed (or the lucky loser replacing them) on the very
    // last line of the draw. Display order only; no stored position changes.
    const rows = [
      <PlayerRow key="p" playerId={p1id} playerById={playerById} drawRanks={drawRanks}
        showTypeSlot={playerNeedsTypeSlot(p1)} isWinner locked showScores={false} />,
      <div key="b" className="player-row bye-slot"><span className="muted">BYE</span></div>,
    ]
    // Wrapped in .match-box-main like every other match. .match-box is a flex
    // ROW — that wrapper is what stacks the two lines — so returning the rows
    // as direct children laid the player and the BYE side by side in a box half
    // the height of its neighbours, which read as a missing slot rather than a
    // bye.
    return (
      <div className="match-box bye" style={style}>
        <div className="match-box-main">
          {match.match_number % 2 === 0 ? [rows[1], rows[0]] : rows}
        </div>
      </div>
    )
  }

  // Orange: picks mode only, when a player slot is still TBD
  const needsPick = mode === 'picks' && (p1id == null || p2id == null)

  // Red outline: both players known but no pick made (and user can still pick)
  const missingPick = mode === 'picks' && !needsPick && onPick != null && pickedId == null

  // Picked player already eliminated in an earlier round — this match can never be won by them
  const pickedIsDead = pickedId != null && ((pickedId === p1id && p1DeadPick) || (pickedId === p2id && p2DeadPick))

  const correctPick = mode === 'picks' && actualWinnerId != null && pickedId != null && pickedId === actualWinnerId
  const wrongPick   = mode === 'picks' && ((actualWinnerId != null && pickedId != null && pickedId !== actualWinnerId)
                    || (p1DeadPick && p2DeadPick)
                    || pickedIsDead)

  return (
    <div
      className={clsx('match-box', {
        'needs-pick': needsPick,
        'missing-pick': missingPick,
        'correct-pick': correctPick,
        'wrong-pick': wrongPick,
        'match-box--h2h': h2hAvailable,
        'match-box--live': isLive,
      })}
      style={style}
    >
      {isLive && !match.winner && (
        <span className={`in-progress-badge${isSuspended ? ' in-progress-badge--suspended' : ''}`}>
          {isSuspended ? 'Suspended' : 'In Progress'}
        </span>
      )}
      {isUpsetPick && (
        <span
          ref={bellRef}
          className="upset-bell"
          onMouseEnter={() => {
            const r = bellRef.current?.getBoundingClientRect()
            if (r) setTipPos({ x: r.left + r.width / 2, y: r.top })
          }}
          onMouseLeave={() => setTipPos(null)}
        >
          🔔
        </span>
      )}
      {isUpsetPick && tipPos && createPortal(
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
      <div className="match-box-main">
        <PlayerRow
          playerId={p1id} playerById={playerById} drawRanks={drawRanks}
          isPicked={pickedId === p1id}
          isWinner={actualWinnerId === p1id}
          isEliminated={actualWinnerId != null && actualWinnerId !== p1id && p1id != null}
          isDeadPick={p1DeadPick}
          isProjected={p1IsProjected}
          scores={isWalkover ? null : p1Scores}
          walkover={wo.p1}
          retired={ret.p1}
          onClick={mode === 'picks' && p1id != null ? () => onPick(match.id, p1id) : undefined}
          locked={locked}
          showTypeSlot={showTypeSlot}
          showScores={showScores}
          markWinner={mode === 'live'}
          showFlag={mode === 'picks'}
          qualifierNum={qualifierNums?.[p1id]}
          isServing={p1Serving}
          boldScores={p1BoldScores}
          isHighlighted={hoveredPlayerId != null && p1id === hoveredPlayerId}
          onHover={onHoverPlayer}
        />
        <PlayerRow
          playerId={p2id} playerById={playerById} drawRanks={drawRanks}
          isPicked={pickedId === p2id}
          isWinner={actualWinnerId === p2id}
          isEliminated={actualWinnerId != null && actualWinnerId !== p2id && p2id != null}
          isDeadPick={p2DeadPick}
          isProjected={p2IsProjected}
          scores={isWalkover ? null : p2Scores}
          walkover={wo.p2}
          retired={ret.p2}
          onClick={mode === 'picks' && p2id != null ? () => onPick(match.id, p2id) : undefined}
          locked={locked}
          showTypeSlot={showTypeSlot}
          showScores={showScores}
          markWinner={mode === 'live'}
          showFlag={mode === 'picks'}
          qualifierNum={qualifierNums?.[p2id]}
          isServing={p2Serving}
          boldScores={p2BoldScores}
          isHighlighted={hoveredPlayerId != null && p2id === hoveredPlayerId}
          onHover={onHoverPlayer}
        />
      </div>
      {h2hAvailable && (
        <button
          className="h2h-strip"
          onClick={() => onH2H(h2hP1, h2hP2, match)}
          title={`Head-to-head: ${p1.name} vs ${p2.name}`}
        >
          <span className="h2h-strip-label">H2H</span>
        </button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Connector lines
// ---------------------------------------------------------------------------

// leftCenters / rightCenters: explicit Y-centre of each match in the two
// columns (indexed by bracket order), so the connectors follow the actual
// match positions.
function ConnectorLines({ leftCenters, rightCenters, totalH }) {
  const lines = []
  const x1 = 0, xMid = COL_GAP / 2, x2 = COL_GAP
  for (let ri = 0; ri < rightCenters.length; ri++) {
    const rCenter = rightCenters[ri]
    const f1Center = leftCenters[ri * 2]
    const f2Center = leftCenters[ri * 2 + 1]

    // Straight elbows: a horizontal stub from each feeder, a vertical bus
    // spanning both feeders and the target, then a horizontal into the target.
    const pts = [f1Center, f2Center, rCenter].filter(v => v != null)
    const yMin = Math.min(...pts), yMax = Math.max(...pts)

    if (f1Center != null) lines.push(<line key={`f1h-${ri}`} x1={x1} y1={f1Center} x2={xMid} y2={f1Center} />)
    if (f2Center != null) lines.push(<line key={`f2h-${ri}`} x1={x1} y1={f2Center} x2={xMid} y2={f2Center} />)
    if (yMax > yMin) lines.push(<line key={`v-${ri}`} x1={xMid} y1={yMin} x2={xMid} y2={yMax} />)
    lines.push(<line key={`rh-${ri}`} x1={xMid} y1={rCenter} x2={x2} y2={rCenter} />)
  }

  return (
    <svg className="connector-svg" width={COL_GAP} height={totalH} style={{ flexShrink: 0 }}>
      <g stroke="#c8e6c9" strokeWidth="1.5" fill="none">{lines}</g>
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function BracketView({ tournament, matches, players, picks, onPick, locked, mode = 'picks', picksOwner = null, windowStart = 0, windowSize = 4, labelsHidden = false, insetLeft = 0 }) {
  const [h2hPlayers, setH2HPlayers] = useState(null) // { p1, p2, match }
  const [hoveredPlayerId, setHoveredPlayerId] = useState(null)

  const playerById = Object.fromEntries(players.map(p => [p.id, p]))
  const drawRanks = computeDrawRanks(players)
  const resolved = resolveMatchPlayers(matches, picks, mode)

  // Order for the panel's ‹ › arrows. Built from `resolved`, so in picks mode
  // it follows the user's own cascade rather than the official draw.
  // Real entrants first, so H2H never compares two players who never met —
  // in picks mode `resolved` is the user's cascade. See resolveRealFirst.
  const h2hResolved = resolveRealFirst(matches, resolved)
  const h2hSeq = buildH2HSequence(matches, h2hResolved, playerById)
  const h2hNav = h2hNeighbours(h2hSeq, h2hPlayers?.match?.id)
  const matchIndex = buildMatchIndex(matches)

  // Number unplaced Q slots by bracket position: Qualifier 1, Qualifier 2, …
  const qualifierNums = {}
  const unplacedQs = players
    .filter(p => p.entry_type === 'Q' && !p.name)
    .sort((a, b) => a.bracket_position - b.bracket_position)
  unplacedQs.forEach((p, i) => { qualifierNums[p.id] = i + 1 })

  // Build lossRound: playerId → round number they actually lost (for picks-mode strikethrough)
  const lossRound = {}
  if (mode === 'picks') {
    for (const m of matches) {
      if (m.winner?.id && !m.is_bye) {
        const wid = m.winner.id
        const loserId = wid === m.player1?.id ? m.player2?.id : m.player1?.id
        if (loserId) lossRound[loserId] = m.round_number
      }
    }
  }

  const rounds = {}
  for (const m of matches) {
    rounds[m.round_number] = rounds[m.round_number] || []
    rounds[m.round_number].push(m)
  }
  const roundNums = Object.keys(rounds).map(Number).sort((a, b) => a - b)

  const roundHasScores = {}
  for (const rn of roundNums) {
    roundHasScores[rn] = rounds[rn].some(
      m => (m.scores && m.scores.length > 0) || m.live_scores != null
    )
  }

  const roundHasTypeSlot = {}
  for (const rn of roundNums) {
    roundHasTypeSlot[rn] = rounds[rn].some(m => {
      const { p1: p1id, p2: p2id } = resolved[m.id] || { p1: m.player1?.id, p2: m.player2?.id }
      return playerNeedsTypeSlot(p1id != null ? playerById[p1id] : null)
          || playerNeedsTypeSlot(p2id != null ? playerById[p2id] : null)
    })
  }

  // Windowed view: only WINDOW rounds are shown at once (the parent controls
  // windowStart and windowSize). Clamp defensively in case the data shrank.
  const WINDOW = windowSize
  const maxStart = Math.max(0, roundNums.length - WINDOW)
  const start = Math.min(windowStart, maxStart)
  const visibleRounds = roundNums.slice(start, start + WINDOW)

  // Each window is a self-contained bracket: the left-most visible round is the
  // tight base (SLOT_BASE spacing), and every round to its right is centred
  // between its two feeders — clean straight feeds, always 4 rounds wide.
  const baseCount = rounds[visibleRounds[0]]?.length ?? 1
  const totalH = baseCount * SLOT_BASE
  const centersByRound = {}
  visibleRounds.forEach((rn, p) => {
    const count = rounds[rn].length
    if (p === 0) {
      centersByRound[rn] = Array.from({ length: count }, (_, i) => i * SLOT_BASE + SLOT_BASE / 2)
    } else {
      const prev = centersByRound[visibleRounds[p - 1]]
      centersByRound[rn] = Array.from({ length: count }, (_, j) => {
        const a = prev[2 * j], b = prev[2 * j + 1]
        if (a != null && b != null) return (a + b) / 2
        if (a != null) return a
        return j * SLOT_BASE + SLOT_BASE / 2
      })
    }
  })

  return (
    <>
    {h2hPlayers && (
      <H2HPanel
        slug1={h2hPlayers.p1.te_slug}
        slug2={h2hPlayers.p2.te_slug}
        player1={h2hPlayers.p1}
        player2={h2hPlayers.p2}
        tournSurface={tournament?.surface}
        tournGender={tournament?.gender}
        beforeDrawId={tournament?.id}
        beforeRound={h2hPlayers.match?.round_number}
        match={h2hPlayers.match}
        matchOrder={matchIndex.order}
        matchTotal={matchIndex.total}
        picks={picks}
        onPick={onPick}
        canPick={mode === 'picks' && !locked}
        onPrev={h2hNav.prev ? () => setH2HPlayers(h2hNav.prev) : null}
        onNext={h2hNav.next ? () => setH2HPlayers(h2hNav.next) : null}
        onClose={() => setH2HPlayers(null)}
      />
    )}
    <div className="bracket-scroll" style={insetLeft ? { paddingLeft: insetLeft } : undefined}>
      <div className={clsx('bracket-labels', { 'bracket-labels--collapsed': labelsHidden })} style={{ paddingLeft: 0 }}>
        {visibleRounds.map((rn, i) => {
          const colW = roundHasScores[rn] ? COL_W_SCORES : COL_W
          return (
            <div key={rn} style={{ display: 'flex', flexShrink: 0 }}>
              <div className="round-label" style={{ width: colW }}>
                {rounds[rn][0]?.round_name || `Round ${rn}`}
              </div>
              {i < visibleRounds.length - 1 && <div style={{ width: COL_GAP }} />}
            </div>
          )
        })}
      </div>

      <div className="bracket-body" style={{ height: totalH }}>
        {visibleRounds.map((rn, colIdx) => {
          const colW = roundHasScores[rn] ? COL_W_SCORES : COL_W
          const roundMatches = [...rounds[rn]].sort((a, b) => a.match_number - b.match_number)
          const centers = centersByRound[rn]

          return (
            <div key={rn} style={{ display: 'flex', flexShrink: 0 }}>
              <div className="bracket-col" style={{ width: colW, height: totalH }}>
                {roundMatches.map((m, i) => {
                  const top = centers[i] - MATCH_H / 2
                  return (
                    <MatchBox
                      key={m.id}
                      match={m}
                      resolvedPlayers={resolved[m.id]}
                      h2hPair={h2hResolved[m.id]}
                      playerById={playerById}
                      drawRanks={drawRanks}
                      picks={picks}
                      onPick={onPick}
                      locked={locked}
                      mode={mode}
                      lossRound={lossRound}
                      onH2H={(p1, p2, match) => setH2HPlayers({ p1, p2, match })}
                      qualifierNums={qualifierNums}
                      forceTypeSlot={roundHasTypeSlot[rn]}
                      hoveredPlayerId={hoveredPlayerId}
                      onHoverPlayer={setHoveredPlayerId}
                      style={{ position: 'absolute', top, left: 6, right: 6 }}
                    />
                  )
                })}
              </div>

              {colIdx < visibleRounds.length - 1 && (
                <ConnectorLines
                  key={`conn-${rn}`}
                  leftCenters={centersByRound[rn]}
                  rightCenters={centersByRound[visibleRounds[colIdx + 1]]}
                  totalH={totalH}
                />
              )}
            </div>
          )
        })}
      </div>
    </div>
    </>
  )
}
