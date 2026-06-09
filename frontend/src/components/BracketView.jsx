/**
 * BracketView — full tournament bracket with:
 *  - Proper vertical centering: round N winners sit between their feeder matches
 *  - Bracket position shown for every player (seed badge = real seed, grey = draw position)
 *  - Set scores displayed next to each player
 *  - Connector lines linking feeder matches to the next round
 *  - Predicted winners cascade through unpopulated later rounds
 */

import clsx from 'clsx'
import './BracketView.css'

// Layout constants
const MATCH_H = 58       // px — height of a 2-player match box
const LABEL_H = 30       // px — round label row height
const SLOT_BASE = 82     // px — vertical slot size for R1 matches
const COL_W = 252        // px — width of each round column
const COL_GAP = 24       // px — gap between columns (for connector lines)

// ---------------------------------------------------------------------------
// Draw rank computation
// Uses player.ranking (real ATP/WTA rank) when available.
// Falls back to: seeds first, then unseeded by entry type, then bracket pos.
// ---------------------------------------------------------------------------

const ENTRY_ORDER = { null: 0, undefined: 0, 'LL': 1, 'PR': 1, 'WC': 2, 'Q': 3 }

function computeDrawRanks(players) {
  // Every player gets a 1-based draw position: real seeds keep their seed number,
  // unseeded players are numbered sequentially after the seeds ordered by bracket position.
  const ranks = {}
  const seeded = players.filter(p => p.seed != null)
  for (const p of seeded) ranks[p.id] = p.seed

  const unseeded = players
    .filter(p => p.seed == null)
    .sort((a, b) => {
      const ea = ENTRY_ORDER[a.entry_type] ?? 0
      const eb = ENTRY_ORDER[b.entry_type] ?? 0
      if (ea !== eb) return ea - eb
      return a.bracket_position - b.bracket_position
    })

  const offset = seeded.length
  unseeded.forEach((p, i) => { ranks[p.id] = offset + i + 1 })
  return ranks
}

// ---------------------------------------------------------------------------
// Player cascade resolution
// ---------------------------------------------------------------------------

function resolveMatchPlayers(matches, picks) {
  const byKey = {}
  for (const m of matches) byKey[`${m.round_number}:${m.match_number}`] = m

  const resolved = {}

  function getWinner(m) {
    if (!m) return null
    if (m.winner?.id != null) return m.winner.id
    return picks[m.id] ?? null
  }

  function resolve(m) {
    if (resolved[m.id]) return resolved[m.id]
    let p1id = m.player1?.id ?? null
    let p2id = m.player2?.id ?? null

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

function ScoreCell({ val }) {
  if (!val) return <span className="score-cell empty">·</span>
  // Strip retirement marker for display ("2r" → "2")
  const clean = val.replace(/r$/i, '')
  // Tiebreak: "7(4)" → 7 with superscript 4
  const tb = clean.match(/^(\d+)\((\d+)\)$/)
  if (tb) return (
    <span className="score-cell tb">{tb[1]}<sup>{tb[2]}</sup></span>
  )
  return <span className="score-cell">{clean}</span>
}

function hasRetirement(scores) {
  if (!scores) return { p1: false, p2: false }
  const check = (arr) => arr?.some(s => /r$/i.test(s)) ?? false
  return { p1: check(scores[0]), p2: check(scores[1]) }
}

function PlayerRow({
  playerId, playerById, drawRanks,
  isPicked, isWinner, isEliminated, isProjected,
  scores, retired, onClick, locked,
  showTypeSlot,
}) {
  const player = playerId != null ? playerById[playerId] : null

  let leftBadge = null

  let typeBadge = null

  if (player) {
    const rank = drawRanks?.[player.id]
    const isQ = player.entry_type === 'Q'

    // Slot 1 (leftmost): draw position — seed number for seeded players,
    //   sequential draw rank for unseeded (same for qualifiers, WCs, etc.)
    if (player.seed != null) {
      leftBadge = <span className="pos-badge seeded">{player.seed}</span>
    } else if (rank != null) {
      leftBadge = <span className="pos-badge unseeded">{rank}</span>
    } else {
      leftBadge = <span className="pos-badge nr" title="Not Ranked">NR</span>
    }

    // Slot 2 (between draw position and name): entry-type label for all entry types.
    if (player.entry_type) {
      typeBadge = (
        <span className={`pos-badge entry entry-${player.entry_type.toLowerCase()}`}>
          {player.entry_type}
        </span>
      )
    }
  }

  if (!player) {
    return (
      <div className="player-row empty">
        <span className="badge-left-slot" />
        {showTypeSlot && <span className="badge-type-slot" />}
        <span className="pname muted">TBD</span>
      </div>
    )
  }

  return (
    <div
      className={clsx('player-row', {
        picked: isPicked && !isWinner,
        winner: isWinner,
        eliminated: isEliminated,
        projected: isProjected && !isWinner,
        clickable: !locked && onClick,
      })}
      onClick={!locked && onClick ? onClick : undefined}
      title={player.nationality ? `${player.name} (${player.nationality})` : player.name}
    >
      <span className="badge-left-slot">{leftBadge}</span>
      {showTypeSlot && <span className="badge-type-slot">{typeBadge}</span>}
      <span className="pname">{player.name}</span>
      {retired && <span className="ret-badge">ret.</span>}
      {scores && scores.length > 0 && (
        <span className="score-row">
          {scores.map((s, i) => <ScoreCell key={i} val={s} />)}
        </span>
      )}
    </div>
  )
}

// Returns true when a player has an entry type that occupies slot 2.
function playerNeedsTypeSlot(p) {
  return !!p?.entry_type
}

function MatchBox({ match, resolvedPlayers, playerById, drawRanks, picks, stalePicks, onPick, locked, style }) {
  const { p1: p1id, p2: p2id } = resolvedPlayers || { p1: match.player1?.id, p2: match.player2?.id }
  const pickedId = picks[match.id]
  const actualWinnerId = match.winner?.id

  const p1IsProjected = !match.player1 && p1id != null
  const p2IsProjected = !match.player2 && p2id != null

  const scores = match.scores  // [[p1_s1,...], [p2_s1,...]] or null
  const p1Scores = scores?.[0] ?? null
  const p2Scores = scores?.[1] ?? null
  const ret = hasRetirement(scores)

  // Only reserve the type slot when at least one player in this match needs it,
  // so names align within the box without wasting space in other matches.
  const p1 = p1id != null ? playerById[p1id] : null
  const p2 = p2id != null ? playerById[p2id] : null
  const showTypeSlot = playerNeedsTypeSlot(p1) || playerNeedsTypeSlot(p2)

  if (match.is_bye) {
    return (
      <div className="match-box bye" style={style}>
        <PlayerRow playerId={p1id} playerById={playerById} drawRanks={drawRanks}
          showTypeSlot={playerNeedsTypeSlot(p1)} isWinner locked />
        <div className="player-row bye-slot"><span className="muted">BYE</span></div>
      </div>
    )
  }

  const pickIsStale = pickedId != null && pickedId !== p1id && pickedId !== p2id
  const needsPick = actualWinnerId == null &&
    !match.is_bye &&
    (pickedId == null || pickIsStale || stalePicks?.has(match.id))

  return (
    <div className={clsx('match-box', { 'needs-pick': needsPick })} style={style}>
      <PlayerRow
        playerId={p1id} playerById={playerById} drawRanks={drawRanks}
        isPicked={pickedId === p1id}
        isWinner={actualWinnerId === p1id}
        isEliminated={actualWinnerId != null && actualWinnerId !== p1id && p1id != null}
        isProjected={p1IsProjected}
        scores={p1Scores}
        retired={ret.p1}
        onClick={p1id != null ? () => onPick(match.id, p1id) : undefined}
        locked={locked}
        showTypeSlot={showTypeSlot}
      />
      <PlayerRow
        playerId={p2id} playerById={playerById} drawRanks={drawRanks}
        isPicked={pickedId === p2id}
        isWinner={actualWinnerId === p2id}
        isEliminated={actualWinnerId != null && actualWinnerId !== p2id && p2id != null}
        isProjected={p2IsProjected}
        scores={p2Scores}
        retired={ret.p2}
        onClick={p2id != null ? () => onPick(match.id, p2id) : undefined}
        locked={locked}
        showTypeSlot={showTypeSlot}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Connector lines SVG between two adjacent columns
// ---------------------------------------------------------------------------

function ConnectorLines({ leftMatches, rightMatches, totalH }) {
  // For each right-side match, draw lines from its two feeders' centers to its center
  const lines = []
  for (let ri = 0; ri < rightMatches.length; ri++) {
    const rSlot = totalH / rightMatches.length
    const rCenter = ri * rSlot + rSlot / 2

    // Two feeders
    const lSlot = totalH / leftMatches.length
    const f1Center = (ri * 2) * lSlot + lSlot / 2
    const f2Center = (ri * 2 + 1) * lSlot + lSlot / 2
    const midY = (f1Center + f2Center) / 2

    const x1 = 0, xMid = COL_GAP / 2, x2 = COL_GAP

    // Horizontal from feeder 1 right edge to midX
    lines.push(<line key={`f1h-${ri}`} x1={x1} y1={f1Center} x2={xMid} y2={f1Center} />)
    // Horizontal from feeder 2 right edge to midX
    lines.push(<line key={`f2h-${ri}`} x1={x1} y1={f2Center} x2={xMid} y2={f2Center} />)
    // Vertical between the two feeder midpoints
    lines.push(<line key={`v-${ri}`} x1={xMid} y1={f1Center} x2={xMid} y2={f2Center} />)
    // Horizontal from midX to the right-side match center
    lines.push(<line key={`rh-${ri}`} x1={xMid} y1={rCenter} x2={x2} y2={rCenter} />)
  }

  return (
    <svg
      className="connector-svg"
      width={COL_GAP}
      height={totalH}
      style={{ flexShrink: 0 }}
    >
      <g stroke="#c8e6c9" strokeWidth="1.5" fill="none">
        {lines}
      </g>
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function BracketView({ tournament, matches, players, picks, stalePicks, onPick, locked }) {
  const playerById = Object.fromEntries(players.map(p => [p.id, p]))
  const drawRanks = computeDrawRanks(players)
  const resolved = resolveMatchPlayers(matches, picks)

  const rounds = {}
  for (const m of matches) {
    rounds[m.round_number] = rounds[m.round_number] || []
    rounds[m.round_number].push(m)
  }
  const roundNums = Object.keys(rounds).map(Number).sort((a, b) => a - b)

  const r1Count = rounds[roundNums[0]]?.length ?? 1
  const totalH = r1Count * SLOT_BASE

  return (
    <div className="bracket-scroll">
      {/* Round labels row */}
      <div className="bracket-labels" style={{ paddingLeft: 0 }}>
        {roundNums.map((rn, i) => (
          <div key={rn} style={{ display: 'flex', flexShrink: 0 }}>
            <div className="round-label" style={{ width: COL_W }}>
              {rounds[rn][0]?.round_name || `Round ${rn}`}
            </div>
            {i < roundNums.length - 1 && (
              <div style={{ width: COL_GAP }} />
            )}
          </div>
        ))}
      </div>

      {/* Bracket body */}
      <div className="bracket-body" style={{ height: totalH }}>
        {roundNums.map((rn, colIdx) => {
          const roundMatches = [...rounds[rn]].sort((a, b) => a.match_number - b.match_number)
          const slotH = totalH / roundMatches.length

          return (
            <div key={rn} style={{ display: 'flex', flexShrink: 0 }}>
              {/* Column */}
              <div className="bracket-col" style={{ width: COL_W, height: totalH }}>
                {roundMatches.map((m, i) => {
                  const top = i * slotH + (slotH - MATCH_H) / 2
                  return (
                    <MatchBox
                      key={m.id}
                      match={m}
                      resolvedPlayers={resolved[m.id]}
                      playerById={playerById}
                      drawRanks={drawRanks}
                      picks={picks}
                      stalePicks={stalePicks}
                      onPick={onPick}
                      locked={locked}
                      style={{ position: 'absolute', top, left: 6, right: 6 }}
                    />
                  )
                })}
              </div>

              {/* Connector lines between this and next column */}
              {colIdx < roundNums.length - 1 && (() => {
                const nextRn = roundNums[colIdx + 1]
                const leftMs = [...rounds[rn]].sort((a, b) => a.match_number - b.match_number)
                const rightMs = [...rounds[nextRn]].sort((a, b) => a.match_number - b.match_number)
                return (
                  <ConnectorLines
                    key={`conn-${rn}`}
                    leftMatches={leftMs}
                    rightMatches={rightMs}
                    totalH={totalH}
                  />
                )
              })()}
            </div>
          )
        })}
      </div>
    </div>
  )
}
