import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getLeague, getLeagueTournaments, getLeaderboard, updateLeague } from '../api/leagues'
import { useAuth } from '../store/auth'
import './LeagueDetail.css'

const SCORING_LABELS = {
  classic: 'Classic Bracket',
  atp_wta: 'ATP/WTA Points Mirror',
  upset_bonus: 'Classic + Upset Bonus',
  custom: 'Custom',
}

const GENDER_COLORS = { M: '#edf3ff', F: '#fff0f5' }
const GENDER_BORDERS = { M: '#93b8ff', F: '#ffb3c6' }

export default function LeagueDetail() {
  const { id } = useParams()
  const { user } = useAuth()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [selectedTournamentId, setSelectedTournamentId] = useState(null)

  const { data: league, isLoading } = useQuery({
    queryKey: ['league', id],
    queryFn: () => getLeague(Number(id)),
  })

  const { data: leagueTournaments = [] } = useQuery({
    queryKey: ['league-tournaments', id],
    queryFn: () => getLeagueTournaments(Number(id)),
    refetchInterval: 60_000,
  })

  const { data: leaderboard } = useQuery({
    queryKey: ['leaderboard', id, selectedTournamentId],
    queryFn: () => getLeaderboard(Number(id), selectedTournamentId),
    enabled: !!selectedTournamentId,
    refetchInterval: 60_000,
  })

  if (isLoading) return <div className="page-loading">Loading…</div>
  if (!league) return null

  const isOwner = user?.id === league.owner.id
  const entries = leaderboard?.entries ?? []
  const selectedTournament = leagueTournaments.find(lt => lt.tournament.id === selectedTournamentId)?.tournament

  return (
    <div className="league-detail">
      <div className="league-detail-header">
        <div>
          <h1>{league.name}</h1>
          <p className="muted">
            {SCORING_LABELS[league.scoring_mode]} ·{' '}
            {league.member_count} member{league.member_count !== 1 ? 's' : ''} ·{' '}
            <span className={`status-badge status-${league.is_public ? 'public' : 'private'}`}>
              {league.is_public ? 'Public' : 'Private'}
            </span>
          </p>
        </div>
        <div className="league-header-actions">
          {isOwner && (
            <button className="btn-secondary" onClick={() => setEditing(s => !s)}>
              {editing ? 'Cancel' : 'Settings'}
            </button>
          )}
        </div>
      </div>

      {!league.is_public && (
        <div className="invite-banner">
          Invite friends — share this code: <strong>{league.invite_code}</strong>{' '}
          (League ID: <strong>{league.id}</strong>)
        </div>
      )}

      {editing && isOwner && (
        <LeagueSettings league={league} onDone={() => { setEditing(false); qc.invalidateQueries(['league', id]) }} />
      )}

      {/* Members */}
      <div className="card league-members-section">
        <h2>Members</h2>
        <div className="league-members-list">
          {league.members.map(m => (
            <span key={m.id} className="league-member-chip">
              {m.display_name}
            </span>
          ))}
        </div>
      </div>

      {/* Tournament cards */}
      <div className="card league-tournaments-section">
        <h2>Tournaments</h2>
        {leagueTournaments.length === 0 ? (
          <p className="muted">No picks have been submitted yet. Members can make picks from the Tournaments page.</p>
        ) : (
          <div className="league-tournaments-grid">
            {leagueTournaments.map(({ tournament: t, picker_count }) => (
              <button
                key={t.id}
                className={`league-tournament-card${selectedTournamentId === t.id ? ' selected' : ''}`}
                style={{
                  background: GENDER_COLORS[t.gender] || '#fff',
                  borderColor: selectedTournamentId === t.id ? '#3b82f6' : (GENDER_BORDERS[t.gender] || '#ddd'),
                }}
                onClick={() => setSelectedTournamentId(t.id === selectedTournamentId ? null : t.id)}
              >
                <div className="ltc-name">{t.name}</div>
                <div className="ltc-meta muted">
                  {t.gender === 'M' ? "Men's" : "Women's"}
                  {t.category && ` · ${t.category.replace(/^(ATP|WTA)\s+/, '')}`}
                </div>
                {t.city && <div className="ltc-city muted">{t.city}</div>}
                <div className="ltc-count">
                  <span className="ltc-count-num">{picker_count}</span>
                  <span className="ltc-count-label"> member{picker_count !== 1 ? 's' : ''} participating</span>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Leaderboard */}
      {selectedTournamentId && (
        <div className="leaderboard-wrap card">
          <div className="leaderboard-header">
            <h2>{selectedTournament ? `${selectedTournament.year} ${selectedTournament.name}` : 'Leaderboard'}</h2>
            <button
              className="btn-secondary"
              onClick={() => navigate(`/tournaments/${selectedTournamentId}`)}
            >
              View Draw
            </button>
          </div>
          {entries.length === 0 ? (
            <p className="muted">No picks submitted yet for this tournament.</p>
          ) : (
            <table className="leaderboard-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Player</th>
                  <th>Points</th>
                  <th>Correct</th>
                  <th>Champion</th>
                  <th>Finalist</th>
                </tr>
              </thead>
              <tbody>
                {entries.map(e => (
                  <tr key={e.user.id} className={e.user.id === user?.id ? 'my-row' : ''}>
                    <td>{e.rank}</td>
                    <td>{e.user.display_name}</td>
                    <td className="pts">{e.total_points}</td>
                    <td>{e.correct_count}</td>
                    <td>{e.champion_correct ? '✓' : '–'}</td>
                    <td>{e.finalist_correct ? '✓' : '–'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}

function LeagueSettings({ league, onDone }) {
  const qc = useQueryClient()
  const [name, setName] = useState(league.name)
  const [isPublic, setIsPublic] = useState(league.is_public)
  const [mode, setMode] = useState(league.scoring_mode)
  const [error, setError] = useState('')

  const mutation = useMutation({
    mutationFn: (data) => updateLeague(league.id, data),
    onSuccess: () => { qc.invalidateQueries(['league', String(league.id)]); onDone() },
    onError: (e) => setError(e.response?.data?.detail || 'Failed'),
  })

  return (
    <div className="card settings-panel">
      <h3>League Settings</h3>
      <div className="form-row">
        <label>Name</label>
        <input value={name} onChange={e => setName(e.target.value)} />
      </div>
      <div className="form-row">
        <label>Scoring mode</label>
        <select value={mode} onChange={e => setMode(e.target.value)}>
          <option value="classic">Classic Bracket</option>
          <option value="atp_wta">ATP/WTA Points Mirror</option>
          <option value="upset_bonus">Classic + Upset Bonus</option>
          <option value="custom">Custom</option>
        </select>
      </div>
      <div className="form-row form-check">
        <label>
          <input type="checkbox" checked={isPublic} onChange={e => setIsPublic(e.target.checked)} />
          &nbsp;Public league
        </label>
      </div>
      {error && <p className="error">{error}</p>}
      <button
        className="btn-primary"
        onClick={() => mutation.mutate({ name, is_public: isPublic, scoring_mode: mode })}
        disabled={mutation.isPending}
      >
        Save
      </button>
    </div>
  )
}
