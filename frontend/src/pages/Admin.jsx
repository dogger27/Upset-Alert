import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { refreshAllCompleted, syncTournaments } from '../api/tournaments'
import { listAdminUsers } from '../api/auth'
import { useAuth } from '../store/auth'
import { Navigate, Link } from 'react-router-dom'
import './Admin.css'

const CURRENT_YEAR = new Date().getFullYear()

const ATP_URL = `https://en.wikipedia.org/wiki/${CURRENT_YEAR}_ATP_Tour`
const WTA_URL = `https://en.wikipedia.org/wiki/${CURRENT_YEAR}_WTA_Tour`

export default function Admin() {
  const { user } = useAuth()
  const qc = useQueryClient()

  const { data: adminUsers = [], isLoading: usersLoading } = useQuery({
    queryKey: ['admin-users'],
    queryFn: listAdminUsers,
    enabled: !!user,
  })

  const refreshMutation = useMutation({
    mutationFn: refreshAllCompleted,
    onSuccess: () => qc.invalidateQueries(['tournaments']),
  })

  const syncMutation = useMutation({
    mutationFn: syncTournaments,
    onSuccess: () => qc.invalidateQueries(['tournaments']),
  })

  if (!user) return <Navigate to="/login" replace />

  return (
    <div className="admin-page">
      <h1>Admin</h1>

      <div className="admin-grid">

        <div className="card admin-section">
          <h2>Tournaments</h2>

          <Link to="/tournaments" className="btn-secondary admin-link-btn">
            View Tournaments Table →
          </Link>

          <div className="admin-actions">
            <div className="admin-action">
              <div className="admin-action-meta">
                <span className="admin-action-name">Sync Tournaments</span>
                <span className="admin-action-desc">Correct wiki titles, discover new tournaments</span>
              </div>
              <div className="admin-action-ctrl">
                <button
                  className="btn-secondary"
                  onClick={() => syncMutation.mutate()}
                  disabled={syncMutation.isPending}
                >
                  {syncMutation.isPending ? 'Syncing…' : 'Run'}
                </button>
                {syncMutation.isSuccess && (
                  <span className="action-result success">
                    ✓ {syncMutation.data.updated} updated · {syncMutation.data.inserted} new
                  </span>
                )}
                {syncMutation.isError && (
                  <span className="action-result error">
                    {syncMutation.error?.response?.data?.detail || syncMutation.error?.message}
                  </span>
                )}
              </div>
            </div>

            <div className="admin-action">
              <div className="admin-action-meta">
                <span className="admin-action-name">Update Draw Data</span>
                <span className="admin-action-desc">Re-scrape active tournaments and overdue draws</span>
              </div>
              <div className="admin-action-ctrl">
                <button
                  className="btn-secondary"
                  onClick={() => refreshMutation.mutate()}
                  disabled={refreshMutation.isPending}
                >
                  {refreshMutation.isPending ? 'Updating…' : 'Run'}
                </button>
                {refreshMutation.isSuccess && (
                  <span className="action-result success">
                    ✓ {refreshMutation.data.refreshed} updated
                    {refreshMutation.data.failed?.length > 0 && (
                      <> · {refreshMutation.data.failed.length} failed</>
                    )}
                  </span>
                )}
                {refreshMutation.isError && (
                  <span className="action-result error">
                    {refreshMutation.error?.response?.data?.detail || refreshMutation.error?.message || 'Failed'}
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>

        <div className="card admin-section">
          <h2>
            Users
            <span className="admin-count">{adminUsers.length}</span>
          </h2>
          {usersLoading ? (
            <p className="muted" style={{ fontSize: '0.88rem' }}>Loading…</p>
          ) : (
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th className="td-left">Name</th>
                    <th className="td-left">Username</th>
                    <th className="td-left">Email</th>
                    <th>Admin</th>
                    <th>Joined</th>
                  </tr>
                </thead>
                <tbody>
                  {adminUsers.map(u => (
                    <tr key={u.id}>
                      <td className="td-left">{u.display_name}</td>
                      <td className="td-left td-muted">@{u.username}</td>
                      <td className="td-left td-muted">{u.email}</td>
                      <td>{u.is_admin ? '✓' : ''}</td>
                      <td className="td-muted td-nowrap">{u.created_at}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

      </div>

      <details className="card admin-section scraping-explainer">
        <summary>How Data Scraping Works</summary>

        <div className="scraping-step">
          <div className="scraping-step-header">
            <span className="scraping-step-num">1</span>
            <strong>Tournament Discovery</strong>
            <span className="scraping-schedule">Daily · midnight UTC</span>
          </div>
          <p>
            The server fetches the current season schedule from Wikipedia and builds the tournament list.
            These are the source pages for {CURRENT_YEAR}:
          </p>
          <div className="scraping-links">
            <a href={ATP_URL} target="_blank" rel="noopener noreferrer">{CURRENT_YEAR} ATP Tour ↗</a>
            <a href={WTA_URL} target="_blank" rel="noopener noreferrer">{CURRENT_YEAR} WTA Tour ↗</a>
          </div>
          <p>
            Each row in the schedule table that contains a Singles link is parsed for the
            tournament name, category (Grand Slam / 500 / 250 etc.), surface, draw size,
            city, and scheduled dates. Tournaments already in the database are updated in
            place; new ones are added automatically.
          </p>
        </div>

        <div className="scraping-step">
          <div className="scraping-step-header">
            <span className="scraping-step-num">2</span>
            <strong>Individual Draw Scraping</strong>
            <span className="scraping-schedule">Daily · noon UTC + on startup</span>
          </div>
          <p>
            For every active or upcoming tournament, the server fetches its dedicated
            singles Wikipedia page (e.g. <em>2026 French Open – Men's singles</em>) and
            parses the bracket template. This extracts:
          </p>
          <ul className="scraping-list">
            <li>Players, seeds, nationalities, and entry types (WC / Q / LL)</li>
            <li>Match pairings for every round</li>
            <li>Match scores and winners as results come in</li>
            <li>Exact tournament start/end dates from the infobox</li>
          </ul>
          <p>
            A tournament's Wikipedia page title is discovered from the season page (step 1)
            and confirmed on first successful fetch — that's when the globe icon appears on
            the Tournaments page. If the page doesn't exist yet (future tournament), the
            system keeps a placeholder and retries daily until Wikipedia creates it.
          </p>
        </div>

        <div className="scraping-step">
          <div className="scraping-step-header">
            <span className="scraping-step-num">3</span>
            <strong>Real-Time Updates via Wikimedia EventStreams</strong>
            <span className="scraping-schedule">Continuous</span>
          </div>
          <p>
            The server maintains a live connection to Wikimedia's EventStreams API — a
            server-sent event feed that broadcasts every Wikipedia page edit in real time.
            For each upcoming and active tournament, the backend subscribes to its singles
            page. The moment any editor updates a match result or adds a player to the
            draw, the server re-scrapes that page automatically — no waiting for the next
            scheduled job. Subscriptions are managed dynamically: tournaments are added
            when they move to "upcoming" status and removed when they complete.
          </p>
        </div>

        <div className="scraping-step">
          <div className="scraping-step-header">
            <span className="scraping-step-num">4</span>
            <strong>Manual Refresh</strong>
            <span className="scraping-schedule">On demand</span>
          </div>
          <p>
            The <strong>Update Draw Data</strong> action above re-runs step 2 immediately
            for all non-completed tournaments, bypassing the cache. Use it if a draw was
            just released and you don't want to wait for the next scheduled run.
            Completed tournaments are always skipped — their data is never overwritten.
          </p>
        </div>
      </details>
    </div>
  )
}
