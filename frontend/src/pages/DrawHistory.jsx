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
      <div className="dh-card-header">
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
        {dateRange && <div className="dh-card-dates">{dateRange}</div>}
        {r0 && (
          <div className="dh-card-bottom-row">
            <span className="dh-bottom-points">Points: <strong>{r0.points}</strong></span>
            <span className="dh-bottom-correct">Correct: <strong>{r0.correct_count} / {entry.total_matches}</strong>{pct}</span>
            <Link className="dh-picks-link" to={`/tournaments/${entry.tournament_id}`}>
              My Picks →
            </Link>
          </div>
        )}
      </div>

      <div className="dh-results">
        <div className="dh-results-header">
          <span>Group</span>
          <span>Rank</span>
        </div>
        {entry.results.map((r, i) => (
          <div key={i} className={`dh-result-row${r.league_id == null ? ' dh-row--global' : ''}`}>
            <span className="dh-group-name">{r.league_name}</span>
            <span className="dh-rank-cell">
              <span className={`dh-rank ${rankBadge(r.rank)}`}>#{r.rank} / {r.total_participants}</span>
            </span>
          </div>
        ))}
      </div>
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
      const y = entry.year ?? new Date(entry.start_date + 'T00:00:00').getFullYear()
      ;(byYear[y] ??= []).push(entry)
    }
  }
  const years = Object.keys(byYear).sort((a, b) => b - a)

  return (
    <div className="dh-page">
      <div className="dh-container">
        <div className="dh-header">
          <h1 className="dh-title">My Draw History</h1>
        </div>

        {isLoading && <div className="dh-state">Loading…</div>}
        {isError && <div className="dh-state dh-state--error">Could not load draw history.</div>}

        {data && data.length === 0 && (
          <div className="dh-state">
            You haven't competed in any draws yet.{' '}
            <Link to="/">Browse tournaments</Link> to get started.
          </div>
        )}

        {years.map(year => {
          const entries = byYear[year]
          const atpEntries = entries.filter(e => e.gender === 'M')
          const wtaEntries = entries.filter(e => e.gender !== 'M')
          return (
            <div key={year} className="dh-year-section">
              <h2 className="dh-year-label">{year}</h2>
              <div className="dh-year-columns">
                <div className="dh-column">
                  <div className="dh-column-label dh-column-label--atp">ATP</div>
                  {atpEntries.length === 0
                    ? <div className="dh-column-empty">—</div>
                    : atpEntries.map(e => <TournamentCard key={e.tournament_id} entry={e} />)
                  }
                </div>
                <div className="dh-column">
                  <div className="dh-column-label dh-column-label--wta">WTA</div>
                  {wtaEntries.length === 0
                    ? <div className="dh-column-empty">—</div>
                    : wtaEntries.map(e => <TournamentCard key={e.tournament_id} entry={e} />)
                  }
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
