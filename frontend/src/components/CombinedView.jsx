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
import './CombinedView.css'

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
    return picks?.[m.id] ?? m.winner?.id ?? null
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

// One set cell → { g: games, tb: tiebreak points | null }
function parseSet(cell) {
  const m = cell != null ? String(cell).replace(/r$/i, '').match(/^(\d+)(?:\((\d+)\))?/) : null
  return m ? { g: m[1], tb: m[2] ?? null } : { g: '', tb: null }
}

// Render the score oriented winner-first as "7-6³, 3-6, 7-5, 6-0": sets joined
// by ", "; tiebreak shown only for the set's LOSER, as a superscript. If either
// side's score cells carry a trailing "r" (retirement), append " (ret.)".
function scoreNodes(scores, winnerIsP1) {
  if (!scores || scores.length < 2) return null
  const a = winnerIsP1 ? scores[0] : scores[1]
  const b = winnerIsP1 ? scores[1] : scores[0]
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
      {sets.map((s, i) => <span key={i}>{i > 0 ? ', ' : ''}{s}</span>)}
      {retired && <span className="cv-ret"> (ret.)</span>}
    </>
  )
}

const BOX_H = 32
const SLOT = 58          // fallback slot (missing feeders only)
const PAIR_SLOT = 130    // vertical slot per MATCH (pair) in the base column
const PAIR_OFF = 24      // half the centre-to-centre gap of a match's two opponents
const COL_W = 260
const COL_GAP = 64       // wide enough to seat the H2H chip on the connector "T"
const H2H_X = 8          // H2H chip's x within the gap — centred on the match box's right border
const BELL_OFFSET = 34   // distance (px) the bell sits left of the H2H chip's centre

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
      <g stroke="#7fbf8f" strokeWidth="1.5" fill="none">{lines}</g>
    </svg>
  )
}

export default function CombinedView({ tournament, matches, players, picks, onPick, locked = true, windowStart = 0, windowSize = 4 }) {
  const [h2h, setH2H] = useState(null)

  const playerById = Object.fromEntries(players.map(p => [p.id, p]))
  const drawRanks = computeDrawRanks(players)

  // Number unplaced Q slots by bracket position: Qualifier 1, Qualifier 2, …
  // (mirror of BracketView so the Combined view labels them identically)
  const qualifierNums = {}
  players
    .filter(p => p.entry_type === 'Q' && !p.name)
    .sort((a, b) => a.bracket_position - b.bracket_position)
    .forEach((p, i) => { qualifierNums[p.id] = i + 1 })

  const isUnnamedQ = (p) => p?.entry_type === 'Q' && !p.name
  const slotName = (p, abbrev) => {
    if (!p) return 'TBD'
    if (isUnnamedQ(p)) {
      const n = qualifierNums[p.id]
      return `Qualifier${n != null ? ` ${n}` : ''}`
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
    return () => onPick(nextMatch.id, playerId)
  }

  function entrantBox(c, i) {
    const match = R[0][Math.floor(i / 2)]
    const pid = i % 2 === 0 ? match.player1?.id : match.player2?.id
    const player = pid != null ? playerById[pid] : null
    const isBye = match.is_bye && i % 2 === 1 && pid == null
    const onClick = isBye ? null : nextMatchOnClick(0, i, pid)
    return { key: `e${i}`, player, isBye, kind: 'entrant', clickable: !!onClick, onClick }
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

    const onClick = nextMatchOnClick(c, i, displayId)

    return {
      key: `w${match.id}`, player, correct, wrong, score,
      realName: wrong && realPlayer ? abbrevName(realPlayer.name) : null,
      realFullName: wrong && realPlayer ? realPlayer.name : null,
      match, abbrev: true, kind: 'winner', clickable: !!onClick, onClick,
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
                <div className="cv-col" style={{ width: COL_W, height: totalH }}>
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
                    return (
                      <div
                        key={`mo${m.id}`}
                        className={`cv-match-outline${isMissingPick ? ' cv-match-outline--missing' : ''}`}
                        style={{ top, height }}
                      />
                    )
                  })}

                  {Array.from({ length: count }, (_, i) => {
                    const box = c === 0 ? entrantBox(c, i) : winnerBox(c, i)
                    const p = box.player
                    return (
                      <div key={box.key} className="cv-slot" style={{ top: cc[i] }}>
                        <div
                          className={`cv-box${box.isBye ? ' cv-box--bye' : ''}${!box.isBye && !p ? ' cv-box--tbd' : ''}${box.correct ? ' cv-box--correct' : ''}${box.wrong ? ' cv-box--wrong' : ''}${box.clickable ? ' cv-box--clickable' : ''}`}
                          onClick={box.onClick}
                        >
                          {box.isBye ? (
                            <span className="cv-name cv-name--muted">BYE</span>
                          ) : (
                            <>
                              <span className="cv-badges"><SeedBadge player={p} drawRanks={drawRanks} /></span>
                              <Flag nat={p?.nationality} />
                              <span className={`cv-name${isUnnamedQ(p) ? ' cv-name--muted' : ''}`} title={p?.nationality ? `${p.name} (${p.nationality})` : (p?.name || undefined)}>
                                {slotName(p, box.abbrev)}
                              </span>
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
              const gapX = colIdx * (COL_W + COL_GAP) + COL_W
              return nextCenters.map((y, ri) => {
                const m = R[nextC - 1][ri]
                const { p1: aId, p2: bId } = resolved[m.id] || {}
                const a = aId != null ? playerById[aId] : null
                const b = bId != null ? playerById[bId] : null
                const pickId = picks?.[m.id] ?? null
                const rankA = aId != null ? drawRanks[aId] : null
                const rankB = bId != null ? drawRanks[bId] : null
                const expectedId = rankA != null && rankB != null ? (rankA <= rankB ? aId : bId) : null
                const isUpsetPick = pickId != null && expectedId != null && pickId !== expectedId
                return (
                  <Fragment key={m.id}>
                    {a?.te_slug && b?.te_slug && (
                      <button
                        className="cv-h2h"
                        style={{ top: y, left: gapX + H2H_X, pointerEvents: 'auto' }}
                        title={`Head-to-head: ${a.name} vs ${b.name}`}
                        onClick={() => setH2H({ p1: a, p2: b, round: m.round_number })}
                      >
                        H2H
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
    </>
  )
}
