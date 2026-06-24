import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import client from '../api/client'
import './HallOfFame.css'

function fetchHallOfFame() {
  return client.get('/tournaments/hall-of-fame').then(r => r.data)
}

const MEDAL = { 1: '🥇', 2: '🥈', 3: '🥉' }

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

                {section.entries.length === 0 ? (
                  <p className="hof-empty">No results yet.</p>
                ) : (
                  <div className="hof-card">
                    <table className="hof-table">
                      <thead>
                        <tr>
                          <th className="hof-th--rank">#</th>
                          <th>User</th>
                          <th>Tournament</th>
                          <th className="hof-th--num">Points</th>
                          <th className="hof-th--num">Correct</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {section.entries.map(entry => (
                          <tr key={`${entry.username}-${entry.tournament_id}`} className={entry.rank <= 3 ? `hof-row--top${entry.rank}` : ''}>
                            <td className="hof-rank">
                              {MEDAL[entry.rank] ?? `#${entry.rank}`}
                            </td>
                            <td className="hof-username">{entry.username}</td>
                            <td className="hof-tourn">
                              <span className="hof-gender">{entry.tournament_gender === 'M' ? 'ATP' : 'WTA'}</span>
                              {entry.tournament_name}{' '}
                              <span className="hof-year">{entry.tournament_year}</span>
                            </td>
                            <td className="hof-points">{entry.points}</td>
                            <td className="hof-muted">{entry.correct_count}</td>
                            <td className="hof-link-cell">
                              <Link className="hof-view-link" to={`/tournaments/${entry.tournament_id}`}>
                                View →
                              </Link>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
