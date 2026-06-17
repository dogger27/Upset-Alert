import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getLeague, getLeagueTournaments, getLeaderboard, updateLeague, setMemberAdmin, removeMember, deleteLeague } from '../api/leagues'
import { useAuth } from '../store/auth'
import UserName from '../components/UserName'
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
  const [showInvite, setShowInvite] = useState(false)
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
  const canInvite = isOwner || league.allow_member_invites
  const entries = leaderboard?.entries ?? []
  const selectedTournament = leagueTournaments.find(lt => lt.tournament.id === selectedTournamentId)?.tournament

  return (
    <div className="league-detail">
      <div className="league-detail-header">
        <div>
          <h1>{league.name}</h1>
          <p className="muted">
            {SCORING_LABELS[league.scoring_mode]} ·{' '}
            {league.member_count} member{league.member_count !== 1 ? 's' : ''}
          </p>
        </div>
        <div className="league-header-actions">
          {canInvite && (
            <button className="btn-secondary" onClick={() => setShowInvite(true)}>
              Invite
            </button>
          )}
          {isOwner && (
            <button className="btn-secondary" onClick={() => setEditing(s => !s)}>
              {editing ? 'Cancel' : 'Settings'}
            </button>
          )}
        </div>
      </div>

      {showInvite && (
        <InviteModal league={league} onClose={() => setShowInvite(false)} />
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
              <UserName user={m} showRealName={league.show_real_name} />
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
                  <span className="ltc-count-label"> member{picker_count !== 1 ? 's' : ''} competing</span>
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
                    <td><UserName user={e.user} showRealName={league.show_real_name} /></td>
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

function InviteModal({ league, onClose }) {
  const [copied, setCopied] = useState(false)

  const copy = () => {
    navigator.clipboard.writeText(league.invite_code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="invite-modal-overlay" onClick={onClose}>
      <div className="invite-modal" onClick={e => e.stopPropagation()}>
        <div className="invite-modal-header">
          <h3>Invite Friends</h3>
          <button className="invite-modal-close" onClick={onClose}>✕</button>
        </div>
        <p className="invite-modal-msg">
          Send this invite code to your friends! Tell them to click <strong>Join</strong> from the dashboard and enter this code.
        </p>
        <div className="invite-code-block">
          <div className="invite-code-label">Invite Code</div>
          <div className="invite-code-value">{league.invite_code}</div>
        </div>
        <button className="btn-primary invite-copy-btn" onClick={copy}>
          {copied ? '✓ Copied!' : 'Copy Invite Code'}
        </button>
      </div>
    </div>
  )
}

function LeagueSettings({ league, onDone, currentUserId }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [name, setName] = useState(league.name)
  const [mode, setMode] = useState(league.scoring_mode)
  const [showRealName, setShowRealName] = useState(league.show_real_name)
  const [allowMemberInvites, setAllowMemberInvites] = useState(league.allow_member_invites)
  const [error, setError] = useState('')
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [deleteConfirmText, setDeleteConfirmText] = useState('')

  const mutation = useMutation({
    mutationFn: (data) => updateLeague(league.id, data),
    onSuccess: () => { qc.invalidateQueries(['league', String(league.id)]); onDone() },
    onError: (e) => setError(e.response?.data?.detail || 'Failed'),
  })

  const adminMutation = useMutation({
    mutationFn: ({ userId, isAdmin }) => setMemberAdmin(league.id, userId, isAdmin),
    onSuccess: () => qc.invalidateQueries(['league', String(league.id)]),
  })

  const removeMutation = useMutation({
    mutationFn: (userId) => removeMember(league.id, userId),
    onSuccess: () => qc.invalidateQueries(['league', String(league.id)]),
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteLeague(league.id),
    onSuccess: () => { qc.invalidateQueries(['leagues']); navigate('/') },
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
          <input type="checkbox" checked={showRealName} onChange={e => setShowRealName(e.target.checked)} />
          &nbsp;Enable &ldquo;Show Real Name&rdquo; on hover
        </label>
      </div>
      <div className="form-row form-check">
        <label>
          <input type="checkbox" checked={allowMemberInvites} onChange={e => setAllowMemberInvites(e.target.checked)} />
          &nbsp;Allow all members to invite others
        </label>
      </div>
      {error && <p className="error">{error}</p>}
      <button
        className="btn-primary"
        onClick={() => mutation.mutate({ name, scoring_mode: mode, show_real_name: showRealName, allow_member_invites: allowMemberInvites })}
        disabled={mutation.isPending}
      >
        Save
      </button>

      <div className="settings-members">
        <h4 className="settings-members-title">Members</h4>
        {league.members.map(m => {
          const isOwner = m.id === league.owner.id
          return (
            <div key={m.id} className="settings-member-row">
              <span className="settings-member-name">
                @{m.username}
                {isOwner && <span className="settings-member-badge owner">Owner</span>}
                {!isOwner && m.is_admin && <span className="settings-member-badge admin">Admin</span>}
              </span>
              <div className="settings-member-actions">
                {!isOwner && (
                  <button
                    className={`settings-admin-btn${m.is_admin ? ' active' : ''}`}
                    onClick={() => adminMutation.mutate({ userId: m.id, isAdmin: !m.is_admin })}
                    disabled={adminMutation.isPending}
                    title={m.is_admin ? 'Remove admin' : 'Make admin'}
                  >
                    {m.is_admin ? 'Remove Admin' : 'Make Admin'}
                  </button>
                )}
                {!isOwner && (
                  <button
                    className="settings-remove-btn"
                    onClick={() => { if (window.confirm(`Remove @${m.username}?`)) removeMutation.mutate(m.id) }}
                    disabled={removeMutation.isPending}
                  >
                    Remove
                  </button>
                )}
              </div>
            </div>
          )
        })}
      </div>

      <div className="settings-danger-zone">
        {!showDeleteConfirm ? (
          <button className="btn-danger" onClick={() => setShowDeleteConfirm(true)}>
            Delete League
          </button>
        ) : (
          <div className="settings-delete-confirm">
            <p className="settings-delete-warning">
              ⚠️ <strong>This cannot be undone.</strong> Deleting this league will permanently remove all members, history, and leaderboard data.
            </p>
            <p className="settings-delete-prompt">
              Type <strong>{league.name}</strong> to confirm:
            </p>
            <input
              className="settings-delete-input"
              value={deleteConfirmText}
              onChange={e => setDeleteConfirmText(e.target.value)}
              placeholder={league.name}
              autoFocus
            />
            <div className="settings-delete-actions">
              <button className="btn-secondary" onClick={() => { setShowDeleteConfirm(false); setDeleteConfirmText('') }}>
                Cancel
              </button>
              <button
                className="btn-danger"
                disabled={deleteConfirmText !== league.name || deleteMutation.isPending}
                onClick={() => deleteMutation.mutate()}
              >
                {deleteMutation.isPending ? 'Deleting…' : 'Permanently Delete'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
