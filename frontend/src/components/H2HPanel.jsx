import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getH2H } from '../api/players'
import './H2HPanel.css'

function teKeys(tournSurface) {
  if (!tournSurface) return []
  const s = tournSurface.toLowerCase()
  if (s.includes('clay')) return ['Clay']
  if (s.includes('grass')) return ['Grass']
  return ['Hard', 'Indoors', 'Carpet']
}

function surfaceLabel(key) {
  if (!key) return '—'
  if (key === 'Indoors') return 'Indoor'
  return key
}

function fmtRound(round) {
  if (!round || round === '—') return '—'
  // Qualifying: "Q-2R" → "Q2"
  const qm = round.match(/^Q-(\d+)R?$/i)
  if (qm) return `Q${qm[1]}`
  // Main draw numbered rounds: "1R" → "R1", "2R" → "R2"
  const rm = round.match(/^(\d+)R$/i)
  if (rm) return `R${rm[1]}`
  return round
}

// TE names come as "Surname Firstname" — move last word to front as fallback
function fmtName(teName) {
  if (!teName) return teName
  const parts = teName.trim().split(/\s+/)
  if (parts.length <= 1) return teName
  return `${parts[parts.length - 1]} ${parts.slice(0, -1).join(' ')}`
}

function calcAge(dob) {
  if (!dob) return null
  const today = new Date()
  const birth = new Date(dob)
  let age = today.getFullYear() - birth.getFullYear()
  const mo = today.getMonth() - birth.getMonth()
  if (mo < 0 || (mo === 0 && today.getDate() < birth.getDate())) age--
  return age
}

function flipScore(score) {
  if (!score) return score
  return score.split(', ').map(set => {
    const parts = set.split('-')
    if (parts.length !== 2) return set
    return `${parts[1]}-${parts[0]}`
  }).join(', ')
}

function EloInfoPopup({ onClose }) {
  return (
    <div className="h2h-elo-popup-backdrop" onClick={onClose}>
      <div className="h2h-elo-popup" onClick={e => e.stopPropagation()}>
        <div className="h2h-elo-popup-header">
          <span className="h2h-elo-popup-title">About Elo Rating</span>
          <button className="h2h-elo-popup-close" onClick={onClose}>✕</button>
        </div>
        <p className="h2h-elo-popup-body">
          Elo measures a player's overall career strength based on match results,
          weighted by opponent quality. A win over a top-10 player boosts your
          rating more than a win over a qualifier. The rank shown is each player's
          position among all active players on tour — #1 is the strongest.
        </p>
        <p className="h2h-elo-popup-source">Source: tennisabstract.com · Updated weekly</p>
      </div>
    </div>
  )
}

export default function H2HPanel({ slug1, slug2, player1, player2, tournSurface, onClose }) {
  const [surfFilter, setSurfFilter] = useState('all') // 'all' | 'surface'
  const [showEloInfo, setShowEloInfo] = useState(false)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['h2h', slug1, slug2],
    queryFn: () => getH2H(slug1, slug2),
    staleTime: 15 * 60 * 1000,
  })

  const slug1IsA = data ? slug1 === data.slug_a : true
  const name_p1 = slug1IsA ? data?.name_a : data?.name_b
  const name_p2 = slug1IsA ? data?.name_b : data?.name_a
  const wins_p1 = slug1IsA ? data?.wins_a : data?.wins_b
  const wins_p2 = slug1IsA ? data?.wins_b : data?.wins_a

  const rank_p1 = player1?.ranking ?? null
  const rank_p2 = player2?.ranking ?? null
  const elo_rank_p1 = player1?.elo_rank ?? null
  const elo_rank_p2 = player2?.elo_rank ?? null
  const age_p1 = calcAge(player1?.date_of_birth)
  const age_p2 = calcAge(player2?.date_of_birth)

  const surfKeys = teKeys(tournSurface)
  let surf_p1 = 0, surf_p2 = 0
  if (data?.surface_wins) {
    for (const key of surfKeys) {
      const sw = data.surface_wins[key]
      if (sw) {
        surf_p1 += slug1IsA ? sw[0] : sw[1]
        surf_p2 += slug1IsA ? sw[1] : sw[0]
      }
    }
  }
  const hasSurfData = (surf_p1 + surf_p2) > 0
  const surfLabel = surfKeys.length ? surfaceLabel(surfKeys[0]) : ''

  const matches = data?.matches ?? []
  const displayMatches = surfFilter === 'surface'
    ? matches.filter(m => surfKeys.includes(m.surface))
    : matches
  const showRank = rank_p1 != null || rank_p2 != null
  const showElo = elo_rank_p1 != null || elo_rank_p2 != null
  const showAge = age_p1 != null || age_p2 != null

  return (
    <div className="h2h-backdrop" onClick={onClose}>
      {showEloInfo && <EloInfoPopup onClose={() => setShowEloInfo(false)} />}
      <div className="h2h-panel" onClick={e => e.stopPropagation()}>
        <button className="h2h-close" onClick={onClose} aria-label="Close">✕</button>

        {/* Header grid: label | p1 | vs | p2 */}
        <div className="h2h-header">
          {/* Names row — always use our API names (Firstname Lastname order) */}
          <div className="h2h-label" />
          <div className="h2h-col-val h2h-player-name">{player1?.name ?? fmtName(name_p1)}</div>
          <div className="h2h-vs">vs</div>
          <div className="h2h-col-val h2h-player-name">{player2?.name ?? fmtName(name_p2)}</div>

          {/* Overall row — click to show all matches */}
          {data && <>
            <button
              className={`h2h-label h2h-filter-btn${surfFilter === 'all' ? ' h2h-filter-active' : ''}`}
              onClick={() => setSurfFilter('all')}
            >Overall</button>
            <div className="h2h-col-val h2h-wins">{wins_p1}</div>
            <div />
            <div className="h2h-col-val h2h-wins">{wins_p2}</div>
          </>}

          {/* Surface row — click to filter matches by surface */}
          {data && surfKeys.length > 0 && <>
            <button
              className={`h2h-label h2h-filter-btn${surfFilter === 'surface' ? ' h2h-filter-active' : ''}`}
              onClick={() => setSurfFilter('surface')}
            >{surfLabel}</button>
            <div className="h2h-col-val h2h-wins">{surf_p1}</div>
            <div />
            <div className="h2h-col-val h2h-wins">{surf_p2}</div>
          </>}

          {/* Divider */}
          {data && <div className="h2h-divider" />}

          {/* Rank row */}
          {showRank && <>
            <div className="h2h-label">Rank</div>
            <div className="h2h-col-val h2h-meta-val">{rank_p1 ?? '—'}</div>
            <div />
            <div className="h2h-col-val h2h-meta-val">{rank_p2 ?? '—'}</div>
          </>}

          {/* Elo row */}
          {showElo && <>
            <div className="h2h-label h2h-label-with-info">
              Elo Rank
              <button className="h2h-info-btn" onClick={() => setShowEloInfo(true)} aria-label="About Elo">ⓘ</button>
            </div>
            <div className="h2h-col-val h2h-meta-val">{elo_rank_p1 != null ? `#${elo_rank_p1}` : '—'}</div>
            <div />
            <div className="h2h-col-val h2h-meta-val">{elo_rank_p2 != null ? `#${elo_rank_p2}` : '—'}</div>
          </>}

          {/* Age row */}
          {showAge && <>
            <div className="h2h-label">Age</div>
            <div className="h2h-col-val h2h-meta-val">{age_p1 ?? '—'}</div>
            <div />
            <div className="h2h-col-val h2h-meta-val">{age_p2 ?? '—'}</div>
          </>}
        </div>

        {isLoading && <div className="h2h-loading">Loading H2H data…</div>}
        {isError && <div className="h2h-error">Could not load H2H data.</div>}

        {data && !isLoading && (
          matches.length > 0 ? (
            <div className="h2h-table-wrap">
              <table className="h2h-table">
                <thead>
                  <tr>
                    <th>Score</th>
                    <th>Winner</th>
                    <th>Surface</th>
                    <th>Year</th>
                    <th>Tournament</th>
                    <th>Rnd</th>
                  </tr>
                </thead>
                <tbody>
                  {displayMatches.map((m, idx) => {
                    const isWin = slug1IsA ? m.winner === 'a' : m.winner === 'b'
                    const displayScore = slug1IsA ? m.score : flipScore(m.score)
                    const winnerIsP1 = slug1IsA ? m.winner === 'a' : m.winner === 'b'
                    const winnerName = winnerIsP1
                      ? (player1?.name ?? fmtName(data.name_a))
                      : (player2?.name ?? fmtName(data.name_b))
                    return (
                      <tr key={idx} className={isWin ? 'h2h-row-win' : 'h2h-row-loss'}>
                        <td className="h2h-score">{displayScore || '—'}</td>
                        <td className="h2h-winner">{winnerName}</td>
                        <td className="h2h-surface">{surfaceLabel(m.surface)}</td>
                        <td className="h2h-year">{m.year ?? '—'}</td>
                        <td className="h2h-tourn">{m.tournament ?? '—'}</td>
                        <td className="h2h-round">{fmtRound(m.round)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="h2h-empty">No head-to-head matches found.</div>
          )
        )}
      </div>
    </div>
  )
}
