import { useMutation, useQueryClient } from '@tanstack/react-query'
import { refreshAllCompleted, syncTournaments } from '../api/tournaments'
import { useAuth } from '../store/auth'
import { Navigate, Link } from 'react-router-dom'
import './Admin.css'

const CURRENT_YEAR = new Date().getFullYear()

const ATP_URL = `https://en.wikipedia.org/wiki/${CURRENT_YEAR}_ATP_Tour`
const WTA_URL = `https://en.wikipedia.org/wiki/${CURRENT_YEAR}_WTA_Tour`

export default function Admin() {
  const { user } = useAuth()
  if (!user) return <Navigate to="/login" replace />

  const qc = useQueryClient()

  const refreshMutation = useMutation({
    mutationFn: refreshAllCompleted,
    onSuccess: () => qc.invalidateQueries(['tournaments']),
  })

  const syncMutation = useMutation({
    mutationFn: syncTournaments,
    onSuccess: () => qc.invalidateQueries(['tournaments']),
  })

  return (
    <div className="admin-page">
      <h1>Admin</h1>

      <div className="card admin-section" style={{ width: 'fit-content' }}>
        <h2>Tournaments</h2>
        <p className="muted" style={{ marginBottom: '1rem', fontSize: '0.88rem' }}>
          View all tournaments, draw status, Wikipedia links, and scraping details.
        </p>
        <Link to="/tournaments" className="btn-secondary" style={{ display: 'inline-block' }}>
          Open Tournaments Table →
        </Link>
      </div>

      <div className="card admin-section" style={{ width: 'fit-content' }}>
        <h2>Data</h2>
        <p className="muted" style={{ marginBottom: '1rem', fontSize: '0.88rem' }}>
          Tournaments are auto-discovered daily. Use these buttons to manually trigger updates.
        </p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          {/* Sync Tournaments — discovery + title correction + scrape */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
            <div>
              <button
                className="btn-secondary"
                onClick={() => syncMutation.mutate()}
                disabled={syncMutation.isPending}
              >
                {syncMutation.isPending ? 'Syncing…' : 'Sync Tournaments'}
              </button>
              <div className="muted" style={{ fontSize: '0.75rem', marginTop: '0.2rem' }}>
                Re-runs discovery: corrects wiki page titles, finds new tournaments
              </div>
            </div>
            {syncMutation.isSuccess && (
              <span style={{ fontSize: '0.85rem', color: '#15803d' }}>
                ✓ {syncMutation.data.updated} updated · {syncMutation.data.inserted} new · {syncMutation.data.skipped} unchanged
              </span>
            )}
            {syncMutation.isError && (
              <span style={{ fontSize: '0.85rem', color: '#dc2626' }}>
                Error: {syncMutation.error?.response?.data?.detail || syncMutation.error?.message}
              </span>
            )}
          </div>

          {/* Update Draw Data — re-scrape started + overdue upcoming tournaments */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
            <div>
              <button
                className="btn-secondary"
                onClick={() => refreshMutation.mutate()}
                disabled={refreshMutation.isPending}
              >
                {refreshMutation.isPending ? 'Updating…' : 'Update Draw Data'}
              </button>
              <div className="muted" style={{ fontSize: '0.75rem', marginTop: '0.2rem' }}>
                Re-scrapes draws for active tournaments and any whose draw date has passed
              </div>
            </div>
            {refreshMutation.isSuccess && (
              <span style={{ fontSize: '0.85rem', color: '#15803d' }}>
                ✓ {refreshMutation.data.refreshed} updated
                {refreshMutation.data.failed?.length > 0 && (
                  <span style={{ color: '#b45309', marginLeft: '0.5rem' }}>
                    · {refreshMutation.data.failed.length} failed: {refreshMutation.data.failed.join(', ')}
                  </span>
                )}
              </span>
            )}
            {refreshMutation.isError && (
              <span style={{ fontSize: '0.85rem', color: '#dc2626' }}>
                Error: {refreshMutation.error?.response?.data?.detail || refreshMutation.error?.message || 'Update failed'}
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="card admin-section scraping-explainer" style={{ maxWidth: 680 }}>
        <h2>How Data Scraping Works</h2>

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
            <a href={ATP_URL} target="_blank" rel="noopener noreferrer">
              {CURRENT_YEAR} ATP Tour ↗
            </a>
            <a href={WTA_URL} target="_blank" rel="noopener noreferrer">
              {CURRENT_YEAR} WTA Tour ↗
            </a>
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
            The <strong>Update Draw Data</strong> button above re-runs step 2 immediately
            for all non-completed tournaments, bypassing the cache. Use it if a draw was
            just released and you don't want to wait for the next scheduled run.
            Completed tournaments are always skipped — their data is never overwritten.
          </p>
        </div>
      </div>
    </div>
  )
}
