import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import client from '../api/client'
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

function GenderTable({ entries, label }) {
  return (
    <div className="hof-gender-col">
      <p className="hof-gender-label">{label}</p>
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
                <th className="hof-th--num">Pts</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {entries.map(entry => (
                <tr key={`${entry.username}-${entry.tournament_id}`} className={entry.rank <= 3 ? `hof-row--top${entry.rank}` : ''}>
                  <td className="hof-rank">{MEDAL[entry.rank] ?? `#${entry.rank}`}</td>
                  <td className="hof-username">{entry.username}</td>
                  <td className="hof-tourn">
                    {entry.tournament_name}{' '}
                    <span className="hof-year">{entry.tournament_year}</span>
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

export default function HallOfFame() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['hall-of-fame'],
    queryFn: fetchHallOfFame,
    staleTime: 10 * 60 * 1000,
  })

  return (
    <div className="hof-page">
      <div className="hof-container">
        <div className="hof-header">
          <h1 className="hof-title">Hall of Fame</h1>
          <p className="hof-subtitle">Top 10 all-time scores by tournament tier — global standings</p>
        </div>

        {isLoading && <div className="hof-state">Loading…</div>}
        {isError && <div className="hof-state hof-state--error">Could not load Hall of Fame.</div>}

        {data && (
          <div className="hof-sections">
            {data.map(section => (
              <div key={section.tier} className="hof-section">
                <h2 className="hof-tier-heading">{section.tier}</h2>
                <div className="hof-two-col">
                  <GenderTable entries={section.men} label="Men" />
                  <GenderTable entries={section.women} label="Women" />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
