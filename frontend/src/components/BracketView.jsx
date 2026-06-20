/**
 * BracketView — full tournament bracket.
 *
 * mode="picks"  (default) — cascade from user picks; no scores; orange when a
 *                           player slot is TBD (user hasn't picked far enough).
 * mode="live"             — cascade from actual match results; scores shown; no orange.
 *
 * Both modes colour the whole match cell green (correct pick) or red (wrong pick).
 */

import { useState } from 'react'
import clsx from 'clsx'
import H2HPanel from './H2HPanel'
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

  // Sort unseeded by world ranking, then assign sequential relative ranks after the seeds
  const unseeded = players
    .filter(p => p.seed == null)
    .sort((a, b) => {
      if (a.ranking != null && b.ranking != null) return a.ranking - b.ranking
      if (a.ranking != null) return -1
      if (b.ranking != null) return 1
      return a.bracket_position - b.bracket_position
    })
  const offset = seeded.length
  unseeded.forEach((p, i) => { ranks[p.id] = offset + i + 1 })
  return ranks
}

const MATCH_H = 58
const LABEL_H = 30
const SLOT_BASE = 82
const COL_W = 252
const COL_GAP = 24



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

function ScoreCell({ val }) {
  if (!val) return <span className="score-cell empty">·</span>
  const clean = val.replace(/r$/i, '')
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
  isPicked, isWinner, isEliminated, isProjected, isDeadPick,
  scores, retired, onClick, locked,
  showTypeSlot, showScores, markWinner, showRowBg, showFlag,
  qualifierNum,
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
        picked: !markWinner && isPicked && !isWinner,
        winner: isWinner,
        eliminated: isEliminated && showRowBg,
        'wrong-pick': wrongPick,
        'dead-pick': isDeadPick,
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
          {scores.map((s, i) => <ScoreCell key={i} val={s} />)}
        </span>
      )}
    </div>
  )
}

function playerNeedsTypeSlot(p) {
  return !!p?.entry_type
}

function MatchBox({ match, resolvedPlayers, playerById, drawRanks, picks, onPick, locked, style, mode, lossRound, onH2H, qualifierNums }) {
  const { p1: p1id, p2: p2id } = resolvedPlayers || { p1: match.player1?.id, p2: match.player2?.id }
  const pickedId = picks[match.id]
  const actualWinnerId = match.winner?.id

  // "Projected" italic only applies in live mode (slot filled by cascade, not yet official)
  const p1IsProjected = mode === 'live' && !match.player1 && p1id != null
  const p2IsProjected = mode === 'live' && !match.player2 && p2id != null

  // Dead pick: player appears here (via picks cascade) but already lost in an earlier round
  const p1DeadPick = mode === 'picks' && p1id != null && lossRound[p1id] != null && lossRound[p1id] < match.round_number
  const p2DeadPick = mode === 'picks' && p2id != null && lossRound[p2id] != null && lossRound[p2id] < match.round_number

  const scores = match.scores
  const p1Scores = scores?.[0] ?? null
  const p2Scores = scores?.[1] ?? null
  const ret = hasRetirement(scores)

  const p1 = p1id != null ? playerById[p1id] : null
  const p2 = p2id != null ? playerById[p2id] : null
  const showTypeSlot = playerNeedsTypeSlot(p1) || playerNeedsTypeSlot(p2)
  const showScores = mode === 'live'

  // H2H strip: both players must have TE slugs (works in live and picks mode)
  const h2hAvailable = !!p1?.te_slug && !!p2?.te_slug

  if (match.is_bye) {
    return (
      <div className="match-box bye" style={style}>
        <PlayerRow playerId={p1id} playerById={playerById} drawRanks={drawRanks}
          showTypeSlot={playerNeedsTypeSlot(p1)} isWinner locked showScores={false} />
        <div className="player-row bye-slot"><span className="muted">BYE</span></div>
      </div>
    )
  }

  // Orange: picks mode only, when a player slot is still TBD
  const needsPick = mode === 'picks' && (p1id == null || p2id == null)

  const correctPick = mode === 'picks' && actualWinnerId != null && pickedId != null && pickedId === actualWinnerId
  const wrongPick   = mode === 'picks' && ((actualWinnerId != null && pickedId != null && pickedId !== actualWinnerId)
                    || (p1DeadPick && p2DeadPick))

  return (
    <div
      className={clsx('match-box', {
        'needs-pick': needsPick,
        'correct-pick': correctPick,
        'wrong-pick': wrongPick,
        'match-box--h2h': h2hAvailable,
      })}
      style={style}
    >
      <div className="match-box-main">
        <PlayerRow
          playerId={p1id} playerById={playerById} drawRanks={drawRanks}
          isPicked={pickedId === p1id}
          isWinner={actualWinnerId === p1id}
          isEliminated={actualWinnerId != null && actualWinnerId !== p1id && p1id != null}
          isDeadPick={p1DeadPick}
          isProjected={p1IsProjected}
          scores={p1Scores}
          retired={ret.p1}
          onClick={mode === 'picks' && p1id != null ? () => onPick(match.id, p1id) : undefined}
          locked={locked}
          showTypeSlot={showTypeSlot}
          showScores={showScores}
          markWinner={mode === 'live'}
          showFlag={mode === 'picks'}
          qualifierNum={qualifierNums?.[p1id]}
        />
        <PlayerRow
          playerId={p2id} playerById={playerById} drawRanks={drawRanks}
          isPicked={pickedId === p2id}
          isWinner={actualWinnerId === p2id}
          isEliminated={actualWinnerId != null && actualWinnerId !== p2id && p2id != null}
          isDeadPick={p2DeadPick}
          isProjected={p2IsProjected}
          scores={p2Scores}
          retired={ret.p2}
          onClick={mode === 'picks' && p2id != null ? () => onPick(match.id, p2id) : undefined}
          locked={locked}
          showTypeSlot={showTypeSlot}
          showScores={showScores}
          markWinner={mode === 'live'}
          showFlag={mode === 'picks'}
          qualifierNum={qualifierNums?.[p2id]}
        />
      </div>
      {h2hAvailable && (
        <button
          className="h2h-strip"
          onClick={() => onH2H(p1, p2)}
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

function ConnectorLines({ leftMatches, rightMatches, totalH }) {
  const lines = []
  for (let ri = 0; ri < rightMatches.length; ri++) {
    const rSlot = totalH / rightMatches.length
    const rCenter = ri * rSlot + rSlot / 2
    const lSlot = totalH / leftMatches.length
    const f1Center = (ri * 2) * lSlot + lSlot / 2
    const f2Center = (ri * 2 + 1) * lSlot + lSlot / 2
    const x1 = 0, xMid = COL_GAP / 2, x2 = COL_GAP

    lines.push(<line key={`f1h-${ri}`} x1={x1} y1={f1Center} x2={xMid} y2={f1Center} />)
    lines.push(<line key={`f2h-${ri}`} x1={x1} y1={f2Center} x2={xMid} y2={f2Center} />)
    lines.push(<line key={`v-${ri}`} x1={xMid} y1={f1Center} x2={xMid} y2={f2Center} />)
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

export default function BracketView({ tournament, matches, players, picks, onPick, locked, mode = 'picks', picksOwner = null }) {
  const [h2hPlayers, setH2HPlayers] = useState(null) // { p1, p2 } player objects

  const playerById = Object.fromEntries(players.map(p => [p.id, p]))
  const drawRanks = computeDrawRanks(players)
  const resolved = resolveMatchPlayers(matches, picks, mode)

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

  const r1Count = rounds[roundNums[0]]?.length ?? 1
  const totalH = r1Count * SLOT_BASE

  return (
    <>
    {h2hPlayers && (
      <H2HPanel
        slug1={h2hPlayers.p1.te_slug}
        slug2={h2hPlayers.p2.te_slug}
        player1={h2hPlayers.p1}
        player2={h2hPlayers.p2}
        tournSurface={tournament?.surface}
        onClose={() => setH2HPlayers(null)}
      />
    )}
    <div className="bracket-scroll">
      <div className="bracket-labels" style={{ paddingLeft: 0 }}>
        {roundNums.map((rn, i) => (
          <div key={rn} style={{ display: 'flex', flexShrink: 0 }}>
            <div className="round-label" style={{ width: COL_W }}>
              {rounds[rn][0]?.round_name || `Round ${rn}`}
            </div>
            {i < roundNums.length - 1 && <div style={{ width: COL_GAP }} />}
          </div>
        ))}
      </div>

      <div className="bracket-body" style={{ height: totalH }}>
        {roundNums.map((rn, colIdx) => {
          const roundMatches = [...rounds[rn]].sort((a, b) => a.match_number - b.match_number)
          const slotH = totalH / roundMatches.length

          return (
            <div key={rn} style={{ display: 'flex', flexShrink: 0 }}>
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
                      onPick={onPick}
                      locked={locked}
                      mode={mode}
                      lossRound={lossRound}
                      onH2H={(p1, p2) => setH2HPlayers({ p1, p2 })}
                      qualifierNums={qualifierNums}
                      style={{ position: 'absolute', top, left: 6, right: 6 }}
                    />
                  )
                })}
              </div>

              {colIdx < roundNums.length - 1 && (() => {
                const nextRn = roundNums[colIdx + 1]
                const leftMs = [...rounds[rn]].sort((a, b) => a.match_number - b.match_number)
                const rightMs = [...rounds[nextRn]].sort((a, b) => a.match_number - b.match_number)
                return (
                  <ConnectorLines key={`conn-${rn}`} leftMatches={leftMs} rightMatches={rightMs} totalH={totalH} />
                )
              })()}
            </div>
          )
        })}
      </div>
    </div>
    </>
  )
}
