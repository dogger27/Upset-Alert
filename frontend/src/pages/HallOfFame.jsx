import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import client from '../api/client'
import { useAuth } from '../store/auth'
import './HallOfFame.css'

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

function fetchHallOfFame() {
  return client.get('/tournaments/hall-of-fame').then(r => r.data)
}

const MEDAL = { 1: '🥇', 2: '🥈', 3: '🥉' }

const TOP_N = 5

function rowClass(entry) {
  const classes = []
  if (entry.rank <= 3) classes.push(`hof-row--top${entry.rank}`)
  if (entry.rank > TOP_N) classes.push('hof-row--extra')
  if (entry.is_current_user) classes.push('hof-row--me')
  return classes.join(' ')
}

function GenderTable({ entries, tour }) {
  return (
    <div className="hof-gender-col">
      <p className={`hof-gender-label hof-gender-label--${tour.toLowerCase()}`}>{tour}</p>
      {entries.length === 0 ? (
        <p className="hof-empty">No results yet.</p>
      ) : (
        <div className="hof-card">
          <table className="hof-table">
            <thead>
              <tr>
                <th className="hof-th--rank">#</th>
                <th>User</th>
                <th>Tournament</th>
                <th className="hof-th--num">Correct</th>
                <th className="hof-th--num">Pts</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {entries.map(entry => (
                <tr key={`${entry.username}-${entry.tournament_id}`} className={rowClass(entry)}>
                  <td className="hof-rank">{MEDAL[entry.rank] ?? `#${entry.rank}`}</td>
                  <td className="hof-username">{entry.username}</td>
                  <td className="hof-tourn">
                    {entry.tournament_name}{' '}
                    <span className="hof-year">{entry.tournament_year}</span>
                  </td>
                  <td className="hof-correct">
                    <span className="hof-correct-frac">{entry.correct_count}/{entry.total_matches}</span>{' '}
                    <span className="hof-correct-pct">({pct(entry)}%)</span>
                  </td>
                  <td className="hof-points">{entry.points}</td>
                  <td className="hof-link-cell">
                    <Link className="hof-view-link" to={`/tournaments/${entry.tournament_id}`} title="View draw">
                      <BracketIcon />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function pct(entry) {
  if (!entry.total_matches) return '0.0'
  return ((entry.correct_count / entry.total_matches) * 100).toFixed(1)
}

export default function HallOfFame() {
  const user = useAuth(s => s.user)
  const { data, isLoading, isError } = useQuery({
    queryKey: ['hall-of-fame', user?.id ?? null],
    queryFn: fetchHallOfFame,
    staleTime: 10 * 60 * 1000,
  })

  return (
    <div className="hof-page">
      <div className="hof-container">
        <div className="hof-header">
          <h1 className="hof-title">Hall of Fame</h1>
          <p className="hof-subtitle">Top 5 all-time scores by tournament tier — global standings</p>
        </div>

        {isLoading && <div className="hof-state">Loading…</div>}
        {isError && <div className="hof-state hof-state--error">Could not load Hall of Fame.</div>}

        {data && (
          <div className="hof-sections">
            {data.map(section => (
              <div key={section.tier} className="hof-section">
                <h2 className="hof-tier-heading">{section.tier}</h2>
                <div className="hof-two-col">
                  <GenderTable entries={section.men} tour="ATP" />
                  <GenderTable entries={section.women} tour="WTA" />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
