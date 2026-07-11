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
import { useState } from 'react'
import H2HPanel from './H2HPanel'
import './CombinedView.css'

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

function abbrevName(full) {
  if (!full) return ''
  const parts = full.trim().split(/\s+/)
  if (parts.length === 1) return parts[0]
  return `${parts[0][0]}. ${parts.slice(1).join(' ')}`
}

// One set cell → { g: games, tb: tiebreak points | null }
function parseSet(cell) {
  const m = cell != null ? String(cell).replace(/r$/i, '').match(/^(\d+)(?:\((\d+)\))?/) : null
  return m ? { g: m[1], tb: m[2] ?? null } : { g: '', tb: null }
}

// Render the score oriented winner-first as "7-6³, 3-6, 7-5, 6-0": sets joined
// by ", "; tiebreak shown only for the set's LOSER, as a superscript.
function scoreNodes(scores, winnerIsP1) {
  if (!scores || scores.length < 2) return null
  const a = winnerIsP1 ? scores[0] : scores[1]
  const b = winnerIsP1 ? scores[1] : scores[0]
  const n = Math.max(a?.length ?? 0, b?.length ?? 0)
  const sets = []
  for (let i = 0; i < n; i++) {
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
  return sets.map((s, i) => <span key={i}>{i > 0 ? ', ' : ''}{s}</span>)
}

const BOX_H = 32
const SLOT = 58          // fallback slot (missing feeders only)
const PAIR_SLOT = 108    // vertical slot per MATCH (pair) in the base column
const PAIR_OFF = 24      // half the centre-to-centre gap of a match's two opponents
const COL_W = 210
const COL_GAP = 44       // wide enough to seat the H2H chip on the connector "T"

function Flag({ nat }) {
  const iso2 = nationalityIso2(nat)
  if (!iso2) return <span className="cv-flag cv-flag--empty" />
  return <span className={`fi fi-${iso2.toLowerCase()} cv-flag`} title={nat} />
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
      <g stroke="#c8e6c9" strokeWidth="1.5" fill="none">{lines}</g>
    </svg>
  )
}

export default function CombinedView({ tournament, matches, players, picks, windowStart = 0, windowSize = 4 }) {
  const [h2h, setH2H] = useState(null)

  const playerById = Object.fromEntries(players.map(p => [p.id, p]))
  const drawRanks = computeDrawRanks(players)

  // Rounds (arrays of matches, sorted by match_number)
  const byRound = {}
  for (const m of matches) (byRound[m.round_number] ||= []).push(m)
  const roundNums = Object.keys(byRound).map(Number).sort((a, b) => a - b)
  const R = roundNums.map(rn => [...byRound[rn]].sort((a, b) => a.match_number - b.match_number))
  const N = R.length
  if (N === 0) return null

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

  // ---- box builders -------------------------------------------------------
  function entrantBox(c, i) {
    const match = R[0][Math.floor(i / 2)]
    const pid = i % 2 === 0 ? match.player1?.id : match.player2?.id
    const player = pid != null ? playerById[pid] : null
    const isBye = match.is_bye && i % 2 === 1 && pid == null
    return { key: `e${i}`, player, isBye, kind: 'entrant' }
  }

  function winnerBox(c, i) {
    const match = R[c - 1][i]
    const realId = match.winner?.id ?? null
    const pickId = picks?.[match.id] ?? null
    const displayId = pickId ?? realId
    const player = displayId != null ? playerById[displayId] : null
    const correct = pickId != null && realId != null && pickId === realId
    const wrong = pickId != null && realId != null && pickId !== realId
    const realPlayer = realId != null ? playerById[realId] : null
    const winnerIsP1 = realId != null && realId === match.player1?.id
    const score = match.is_bye ? null : scoreNodes(match.scores, winnerIsP1)
    return {
      key: `w${match.id}`, player, correct, wrong, score,
      realName: wrong && realPlayer ? abbrevName(realPlayer.name) : null,
      realFullName: wrong && realPlayer ? realPlayer.name : null,
      match, abbrev: true, kind: 'winner',
    }
  }

  const colX = (idx) => idx * (COL_W + COL_GAP)

  return (
    <>
      {h2h && (
        <H2HPanel
          slug1={h2h.p1.te_slug} slug2={h2h.p2.te_slug}
          player1={h2h.p1} player2={h2h.p2}
          tournSurface={tournament?.surface} tournGender={tournament?.gender}
          beforeDrawId={tournament?.id} beforeRound={h2h.round}
          onClose={() => setH2H(null)}
        />
      )}
      <div className="cv-scroll">
        <div className="cv-labels">
          {visible.map((c, i) => {
            const label = c === 0
              ? (R[0][0]?.round_name || 'Round 1')
              : c < N ? (R[c][0]?.round_name || `Round ${c + 1}`) : 'Champion'
            return (
              <div key={c} style={{ display: 'flex', flexShrink: 0 }}>
                <div className="cv-label" style={{ width: COL_W }}>{label}</div>
                {i < visible.length - 1 && <div style={{ width: COL_GAP }} />}
              </div>
            )
          })}
        </div>

        <div className="cv-body" style={{ height: totalH }}>
          {visible.map((c, colIdx) => {
            const count = colCount(c)
            const cc = centers[c]
            return (
              <div key={c} style={{ display: 'flex', flexShrink: 0 }}>
                <div className="cv-col" style={{ width: COL_W, height: totalH }}>
                  {Array.from({ length: count }, (_, i) => {
                    const box = c === 0 ? entrantBox(c, i) : winnerBox(c, i)
                    const p = box.player
                    return (
                      <div key={box.key} className="cv-slot" style={{ top: cc[i] }}>
                        {box.realName && <div className="cv-real-winner" title={box.realFullName || undefined}>{box.realName}</div>}
                        <div className={`cv-box${box.isBye ? ' cv-box--bye' : ''}${box.correct ? ' cv-box--correct' : ''}${box.wrong ? ' cv-box--wrong' : ''}`}>
                          {box.isBye ? (
                            <span className="cv-name cv-name--muted">BYE</span>
                          ) : (
                            <>
                              <span className="cv-badges"><SeedBadge player={p} drawRanks={drawRanks} /></span>
                              <Flag nat={p?.nationality} />
                              <span className="cv-name" title={p?.nationality ? `${p.name} (${p.nationality})` : (p?.name || undefined)}>
                                {p ? (box.abbrev ? abbrevName(p.name) : p.name) : 'TBD'}
                              </span>
                              <EntryBadge player={p} />
                            </>
                          )}
                        </div>
                        {colIdx > 0 && box.score && <div className="cv-score">{box.score}</div>}
                      </div>
                    )
                  })}
                </div>

                {colIdx < visible.length - 1 && (() => {
                  const nextC = visible[colIdx + 1]
                  return (
                    <div className="cv-gap" style={{ width: COL_GAP, height: totalH, position: 'relative' }}>
                      <Connectors leftCenters={cc} rightCenters={centers[nextC]} totalH={totalH} />
                      {/* H2H chip on the connector "T" feeding each next-column winner */}
                      {nextC >= 1 && centers[nextC].map((y, ri) => {
                        const m = R[nextC - 1][ri]
                        const a = m.player1?.id != null ? playerById[m.player1.id] : null
                        const b = m.player2?.id != null ? playerById[m.player2.id] : null
                        if (!a?.te_slug || !b?.te_slug) return null
                        return (
                          <button
                            key={`h${m.id}`}
                            className="cv-h2h"
                            style={{ top: y, left: COL_GAP / 2 }}
                            title={`Head-to-head: ${a.name} vs ${b.name}`}
                            onClick={() => setH2H({ p1: a, p2: b, round: m.round_number })}
                          >
                            H2H
                          </button>
                        )
                      })}
                    </div>
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
