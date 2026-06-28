import { Fragment } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import client from '../api/client'
import './DrawHistory.css'

function fetchMyHistory() {
  return client.get('/auth/me/draw-history').then(r => ({ username: null, entries: r.data }))
}
function fetchUserHistory(userId) {
  return client.get(`/auth/users/${userId}/draw-history`).then(r => r.data)
}

function categoryShort(cat) {
  if (!cat) return ''
  if (cat.includes('Slam') || cat.includes('slam')) return 'Grand Slam'
  if (cat.includes('1000')) return '1000'
  if (cat.includes('500')) return '500'
  return '250'
}

function rankBadge(rank) {
  if (rank === 1) return 'dh-rank--gold'
  if (rank === 2) return 'dh-rank--silver'
  if (rank === 3) return 'dh-rank--bronze'
  return ''
}

function fmtDateRange(start, end) {
  if (!start) return null
  const s = new Date(start + 'T00:00:00')
  const fmt = (d, opts) => d.toLocaleDateString('en-US', opts)
  if (!end) return fmt(s, { month: 'short', day: 'numeric' })
  const e = new Date(end + 'T00:00:00')
  if (s.getMonth() === e.getMonth() && s.getFullYear() === e.getFullYear()) {
    return `${fmt(s, { month: 'short', day: 'numeric' })} – ${e.getDate()}`
  }
  return `${fmt(s, { month: 'short', day: 'numeric' })} – ${fmt(e, { month: 'short', day: 'numeric' })}`
}

const BracketIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="17" y1="12" x2="24" y2="12"/>
    <polyline points="17,6 17,18"/>
    <line x1="10" y1="6" x2="17" y2="6"/>
    <line x1="10" y1="18" x2="17" y2="18"/>
    <polyline points="10,3 10,9"/>
    <polyline points="10,15 10,21"/>
    <line x1="3" y1="3" x2="10" y2="3"/>
    <line x1="3" y1="9" x2="10" y2="9"/>
    <line x1="3" y1="15" x2="10" y2="15"/>
    <line x1="3" y1="21" x2="10" y2="21"/>
  </svg>
)

function TournamentCard({ entry, userId }) {
  const isATP = entry.gender === 'M'
  const catLabel = entry.category ? `${isATP ? 'ATP' : 'WTA'} ${categoryShort(entry.category)}` : null
  const dateRange = fmtDateRange(entry.start_date, entry.end_date)
  const r0 = entry.results[0]
  const pct = entry.total_matches > 0
    ? ` (${(r0.correct_count / entry.total_matches * 100).toFixed(1)}%)`
    : ''

  return (
    <div className="dh-card">
      {/* Title row: badge + name | date range */}
      <div className="dh-card-title">
        <span className="dh-title-left">
          {catLabel && (
            <span className={`dh-category ${isATP ? 'dh-category--atp' : 'dh-category--wta'}`}>
              {catLabel}
            </span>
          )}
          <span className="dh-tourn-name">{entry.name}</span>
        </span>
        {dateRange && <span className="dh-date-right">{dateRange}</span>}
      </div>

      {/* Stats row: points + correct (no picks button) */}
      {r0 && (
        <div className="dh-stats-row">
          <span className="dh-bottom-points">Points: <strong>{r0.points}</strong></span>
          <span className="dh-bottom-correct">Correct: <strong>{r0.correct_count} / {entry.total_matches}</strong>{pct}</span>
        </div>
      )}

      <div className="dh-divider" />

      <span className="dh-col-label dh-col-label--icon" />
      <span className="dh-col-label dh-col-label--group">Group</span>
      <span className="dh-col-label dh-col-label--rank">Rank</span>

      {entry.results.map((r, i) => {
        const isGlobal = r.league_id == null
        const isLast = i === entry.results.length - 1
        const cls = (base) =>
          [base, isGlobal ? 'dh-row--global' : '', isLast ? 'dh-row-last' : ''].filter(Boolean).join(' ')
        const params = new URLSearchParams()
        if (userId) params.set('user', String(userId))
        if (r.league_id) params.set('league', String(r.league_id))
        const qs = params.toString()
        const drawUrl = `/tournaments/${entry.tournament_id}${qs ? '?' + qs : ''}`
        return (
          <Fragment key={i}>
            <span className={cls('dh-row-icon')}>
              <Link to={drawUrl} className="dh-bracket-link" title={`View draw · ${r.league_name}`}>
                <BracketIcon />
              </Link>
            </span>
            <span className={cls('dh-group-name')}>{r.league_name}</span>
            <span className={cls('dh-rank-cell')}>
              <span className={`dh-rank ${rankBadge(r.rank)}`}>#{r.rank} / {r.total_participants}</span>
            </span>
          </Fragment>
        )
      })}
    </div>
  )
}

export default function DrawHistory() {
  const [searchParams] = useSearchParams()
  const userIdParam = searchParams.get('user')
  const userId = userIdParam ? Number(userIdParam) : null

  const { data, isLoading, isError } = useQuery({
    queryKey: ['draw-history', userId],
    queryFn: () => userId ? fetchUserHistory(userId) : fetchMyHistory(),
    staleTime: 5 * 60 * 1000,
  })

  const username = data?.username ?? null
  const entries = data?.entries ?? (Array.isArray(data) ? data : [])

  const byYear = {}
  if (entries.length > 0) {
    for (const entry of entries) {
      const yr = entry.year ?? (entry.start_date ? entry.start_date.slice(0, 4) : '?')
      if (!byYear[yr]) byYear[yr] = []
      byYear[yr].push(entry)
    }
    // Sort within each year: most recent first
    for (const yr of Object.keys(byYear)) {
      byYear[yr].sort((a, b) => {
        if (!a.start_date) return 1
        if (!b.start_date) return -1
        return b.start_date.localeCompare(a.start_date)
      })
    }
  }

  const years = Object.keys(byYear).sort((a, b) => b - a)
  const pageTitle = 'Draw History'

  if (isLoading) return <div className="dh-page"><div className="dh-container"><p className="dh-state">Loading…</p></div></div>
  if (isError)   return <div className="dh-page"><div className="dh-container"><p className="dh-state dh-state--error">Failed to load draw history.</p></div></div>
  if (!entries || entries.length === 0) return (
    <div className="dh-page">
      <div className="dh-container">
        <div className="dh-header">
          <div className="dh-header-row">
            <h1 className="dh-title">{pageTitle}</h1>
            {username && <span className="dh-username-label">{username}</span>}
          </div>
        </div>
        <p className="dh-state">No completed tournaments yet. <Link to="/">Browse tournaments →</Link></p>
      </div>
    </div>
  )

  return (
    <div className="dh-page">
      <div className="dh-container">
        <div className="dh-header">
          <div className="dh-header-row">
            <h1 className="dh-title">{pageTitle}</h1>
            {username && <span className="dh-username-label">{username}</span>}
          </div>
        </div>

        {years.map(yr => {
          const yrEntries = byYear[yr]
          const atp = yrEntries.filter(e => e.gender === 'M')
          const wta = yrEntries.filter(e => e.gender === 'F')

          return (
            <div key={yr} className="dh-year-section">
              <div className="dh-year-label">{yr}</div>
              <div className="dh-year-columns">
                <div className="dh-column">
                  <div className="dh-column-label dh-column-label--atp">ATP</div>
                  {atp.length > 0
                    ? atp.map(e => <TournamentCard key={e.tournament_id} entry={e} userId={userId} />)
                    : <div className="dh-column-empty">—</div>}
                </div>
                <div className="dh-column">
                  <div className="dh-column-label dh-column-label--wta">WTA</div>
                  {wta.length > 0
                    ? wta.map(e => <TournamentCard key={e.tournament_id} entry={e} userId={userId} />)
                    : <div className="dh-column-empty">—</div>}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
