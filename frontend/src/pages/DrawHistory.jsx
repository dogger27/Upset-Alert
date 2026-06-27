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

function rankBadge(rank, total) {
  if (rank === 1) return 'dh-rank--gold'
  if (rank === 2) return 'dh-rank--silver'
  if (rank === 3) return 'dh-rank--bronze'
  return ''
}

export default function DrawHistory() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['draw-history'],
    queryFn: fetchDrawHistory,
    staleTime: 5 * 60 * 1000,
  })

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

        {data && data.length > 0 && (
          <div className="dh-list">
            {data.map(entry => (
              <div key={entry.tournament_id} className="dh-card">
                <div className="dh-card-header">
                  <div className="dh-card-title">
                    <span className={`dh-surface ${surfaceClass(entry.surface)}`}>
                      {entry.surface || '—'}
                    </span>
                    {entry.category && (
                      <span className="dh-category">
                        {entry.gender === 'M' ? 'ATP' : 'WTA'} {categoryShort(entry.category)}
                      </span>
                    )}
                    <span className="dh-tourn-name">{entry.name}</span>
                    <Link className="dh-picks-link" to={`/tournaments/${entry.tournament_id}`}>
                      View my picks →
                    </Link>
                  </div>
                </div>

                <table className="dh-table">
                  <thead>
                    <tr>
                      <th>Group</th>
                      <th>Rank</th>
                      <th>Players</th>
                      <th>Points</th>
                      <th>Correct</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entry.results.map((r, i) => (
                      <tr key={i} className={r.league_id == null ? 'dh-row--global' : ''}>
                        <td className="dh-group-name">{r.league_name}</td>
                        <td>
                          <span className={`dh-rank ${rankBadge(r.rank, r.total_participants)}`}>
                            #{r.rank}
                          </span>
                          <span className="dh-total"> / {r.total_participants}</span>
                        </td>
                        <td className="dh-muted">{r.total_participants}</td>
                        <td className="dh-points">{r.points}</td>
                        <td className="dh-muted">
                          {r.correct_count} / {entry.total_matches}{entry.total_matches > 0 ? ` (${(r.correct_count / entry.total_matches * 100).toFixed(1)}%)` : ''}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
