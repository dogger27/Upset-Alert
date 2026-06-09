import { useMutation, useQueryClient } from '@tanstack/react-query'
import { refreshAllCompleted } from '../api/tournaments'
import { useAuth } from '../store/auth'
import { Navigate } from 'react-router-dom'
import './Admin.css'

export default function Admin() {
  const { user } = useAuth()
  if (!user) return <Navigate to="/login" replace />

  const qc = useQueryClient()

  const refreshCompletedMutation = useMutation({
    mutationFn: refreshAllCompleted,
    onSuccess: () => qc.invalidateQueries(['tournaments']),
  })

  return (
    <div className="admin-page">
      <h1>Admin</h1>

      <div className="card admin-section" style={{ width: 'fit-content' }}>
        <h2>Data</h2>
        <p className="muted" style={{ marginBottom: '1rem', fontSize: '0.88rem' }}>
          Tournaments are auto-discovered daily. Draws update in real-time via Wikipedia EventStreams.
        </p>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <button
            className="btn-secondary"
            onClick={() => refreshCompletedMutation.mutate()}
            disabled={refreshCompletedMutation.isPending}
            title="Re-scrape all completed tournaments to pick up any missed results"
          >
            {refreshCompletedMutation.isPending ? 'Refreshing…' : 'Refresh Completed'}
          </button>
          {refreshCompletedMutation.isSuccess && (
            <span className="muted" style={{ fontSize: '0.82rem' }}>
              ✓ {refreshCompletedMutation.data.refreshed} refreshed
              {refreshCompletedMutation.data.failed?.length > 0 &&
                ` · ${refreshCompletedMutation.data.failed.length} failed`}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
