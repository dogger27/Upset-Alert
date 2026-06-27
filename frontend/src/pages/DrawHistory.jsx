import { Fragment } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import client from '../api/client'
import './DrawHistory.css'

function fetchDrawHistory() {
  return client.get('/auth/me/draw-history').then(r => r.data)
}

function categoryShort(cat) {
  if (!cat) return ''
  if (cat.includes('Slam') || cat.includes('slam')) return 'Grand Slam'
  if (cat.includes('1000')) return '1000'
  if (cat.includes('500')) return '500'
  return '250'
}

function surfaceClass(surface) {
  if (!surface) return ''
  const s = surface.toLowerCase()
  if (s.includes('clay')) return 'dh-surface--clay'
  if (s.includes('grass')) return 'dh-surface--grass'
  return 'dh-surface--hard'
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
  if (!end) return fmt(s, { month: 'long', day: 'numeric' })
  const e = new Date(end + 'T00:00:00')
  if (s.getMonth() === e.getMonth() && s.getFullYear() === e.getFullYear()) {
    return `${fmt(s, { month: 'long', day: 'numeric' })} – ${e.getDate()}`
  }
  return `${fmt(s, { month: 'long', day: 'numeric' })} – ${fmt(e, { month: 'long', day: 'numeric' })}`
}

function TournamentCard({ entry }) {
  const isATP = entry.gender === 'M'
  const catLabel = entry.category ? `${isATP ? 'ATP' : 'WTA'} ${categoryShort(entry.category)}` : null
  const dateRange = fmtDateRange(entry.start_date, entry.end_date)
  const r0 = entry.results[0]
  const pct = entry.total_matches > 0
    ? ` (${(r0.correct_count / entry.total_matches * 100).toFixed(1)}%)`
    : ''

  return (
    <div className="dh-card">
      {/* Title — spans all 3 grid columns */}
      <div className="dh-card-title">
        <span className="dh-title-left">
          {catLabel && (
            <span className={`dh-category ${isATP ? 'dh-category--atp' : 'dh-category--wta'}`}>
              {catLabel}
            </span>
          )}
          <span className="dh-tourn-name">{entry.name}</span>
        </span>
        <span className={`dh-surface dh-surface--right ${surfaceClass(entry.surface)}`}>
          {entry.surface || '—'}
        </span>
      </div>

      {/* Dates — spans all 3 grid columns */}
      {dateRange && <div className="dh-card-dates">{dateRange}</div>}

      {/* Stats — 3 separate grid cells (col1 | col2 | col3) */}
      {r0 && <>
        <span className="dh-bottom-points">Points: <strong>{r0.points}</strong></span>
        <span className="dh-bottom-correct">Correct: <strong>{r0.correct_count} / {entry.total_matches}</strong>{pct}</span>
        <Link className="dh-picks-link" to={`/tournaments/${entry.tournament_id}`}>My Picks →</Link>
      </>}

      {/* Section divider — spans all 3 grid columns */}
      <div className="dh-divider" />

      {/* Column headers — 3 grid cells */}
      <span className="dh-col-label dh-col-label--group">Group</span>
      <span className="dh-col-label dh-col-label--rank">Rank</span>
      <span className="dh-col-label dh-col-label--end" />

      {/* Result rows — 3 grid cells each */}
      {entry.results.map((r, i) => {
        const isGlobal = r.league_id == null
        const isLast = i === entry.results.length - 1
        const cls = (base) =>
          [base, isGlobal ? 'dh-row--global' : '', isLast ? 'dh-row-last' : ''].filter(Boolean).join(' ')
        return (
          <Fragment key={i}>
            <span className={cls('dh-group-name')}>{r.league_name}</span>
            <span className={cls('dh-rank-cell')}>
              <span className={`dh-rank ${rankBadge(r.rank)}`}>#{r.rank} / {r.total_participants}</span>
            </span>
            <span className={cls('dh-row-end')} />
          </Fragment>
        )
      })}
    </div>
  )
}

export default function DrawHistory() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['draw-history'],
    queryFn: fetchDrawHistory,
    staleTime: 5 * 60 * 1000,
  })

  // Group by year, sort by start_date within each year, years descending
  const byYear = {}
  if (data) {
    const sorted = [...data].sort((a, b) => {
      if (!a.start_date) return 1
      if (!b.start_date) return -1
      return a.start_date.localeCompare(b.start_date)
    })
    for (const entry of sorted) {
      const yr = entry.year ?? (entry.start_date ? entry.start_date.slice(0, 4) : '?')
      if (!byYear[yr]) byYear[yr] = []
      byYear[yr].push(entry)
    }
  }

  const years = Object.keys(byYear).sort((a, b) => b - a)

  if (isLoading) return <div className="dh-page"><div className="dh-container"><p className="dh-state">Loading…</p></div></div>
  if (isError)   return <div className="dh-page"><div className="dh-container"><p className="dh-state dh-state--error">Failed to load draw history.</p></div></div>
  if (!data || data.length === 0) return (
    <div className="dh-page">
      <div className="dh-container">
        <div className="dh-header"><h1 className="dh-title">My Draw History</h1></div>
        <p className="dh-state">No completed tournaments yet. <Link to="/tournaments">Browse tournaments →</Link></p>
      </div>
    </div>
  )

  return (
    <div className="dh-page">
      <div className="dh-container">
        <div className="dh-header">
          <h1 className="dh-title">My Draw History</h1>
        </div>

        {years.map(yr => {
          const entries = byYear[yr]
          const atp = entries.filter(e => e.gender === 'M')
          const wta = entries.filter(e => e.gender === 'F')
          const maxLen = Math.max(atp.length, wta.length)

          return (
            <div key={yr} className="dh-year-section">
              <div className="dh-year-label">{yr}</div>
              <div className="dh-year-columns">
                <div className="dh-column">
                  <div className="dh-column-label dh-column-label--atp">ATP (M)</div>
                  {atp.length > 0
                    ? atp.map(e => <TournamentCard key={e.tournament_id} entry={e} />)
                    : <div className="dh-column-empty">—</div>}
                </div>
                <div className="dh-column">
                  <div className="dh-column-label dh-column-label--wta">WTA (F)</div>
                  {wta.length > 0
                    ? wta.map(e => <TournamentCard key={e.tournament_id} entry={e} />)
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
