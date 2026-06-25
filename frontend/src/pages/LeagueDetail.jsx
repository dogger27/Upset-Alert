import { useState, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getLeague, getLeagueTournaments, getLeaderboard, getRoundScores, updateLeague, setMemberAdmin, removeMember, deleteLeague } from '../api/leagues'
import { useAuth } from '../store/auth'
import UserName from '../components/UserName'
import './LeagueDetail.css'

const SCORING_LABELS = {
  classic: 'Classic Bracket',
  atp_wta: 'ATP/WTA Points Mirror',
  upset_bonus: 'Classic + Upset Bonus',
  custom: 'Custom',
}


function tierValue(category) {
  const c = (category || '').toUpperCase()
  if (c.includes('SLAM') || c.includes('GRAND')) return 4
  if (c.includes('1000')) return 3
  if (c.includes('500')) return 2
  return 1
}

function tierLabel(category) {
  const c = (category || '').toUpperCase()
  if (c.includes('SLAM') || c.includes('GRAND')) return 'Grand Slam'
  if (c.includes('1000')) return '1000'
  if (c.includes('500')) return '500'
  return '250'
}

function SortTh({ col, active, dir, onSort, children }) {
  return (
    <th
      className={`lt-th-sort${active ? ' lt-th-active' : ''}`}
      onClick={() => onSort(col)}
    >
      {children}
      <span className="lt-sort-icon">{active ? (dir === 'desc' ? ' ▼' : ' ▲') : ' ↕'}</span>
    </th>
  )
}

export default function LeagueDetail() {
  const { id } = useParams()
  const { user } = useAuth()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [showInvite, setShowInvite] = useState(false)
  const [selectedTournamentId, setSelectedTournamentId] = useState(null)
  const [sortBy, setSortBy] = useState('start_date')
  const [sortDir, setSortDir] = useState('desc')

  const handleSort = (col) => {
    if (sortBy === col) setSortDir(d => d === 'desc' ? 'asc' : 'desc')
    else { setSortBy(col); setSortDir('desc') }
  }

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

  // Hooks must be called before any early returns.
  // Active tournaments → bar chart visualization (always visible)
  // Non-active (upcoming + completed ≥2 members) → sortable table
  const activeTournaments = useMemo(
    () => leagueTournaments.filter(lt => lt.tournament.status === 'active'),
    [leagueTournaments]
  )
  const tableRows = useMemo(() => {
    const rows = leagueTournaments.filter(
      lt => lt.tournament.status !== 'active' &&
           (lt.tournament.status !== 'completed' || lt.picker_count >= 2)
    )
    return [...rows].sort((a, b) => {
      let va, vb
      if (sortBy === 'members') {
        va = a.picker_count; vb = b.picker_count
      } else if (sortBy === 'start_date') {
        va = a.tournament.start_date || ''; vb = b.tournament.start_date || ''
      } else {
        va = tierValue(a.tournament.category); vb = tierValue(b.tournament.category)
      }
      if (va === vb) return 0
      return sortDir === 'desc' ? (vb > va ? 1 : -1) : (va > vb ? 1 : -1)
    })
  }, [leagueTournaments, sortBy, sortDir])

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

      {/* Tournaments */}
      <div className="card league-tournaments-section">
        <h2>Tournaments</h2>
        {activeTournaments.length === 0 && tableRows.length === 0 ? (
          <p className="muted">No picks have been submitted yet. Members can make picks from the Tournaments page.</p>
        ) : (
          <>
            {/* Active tournaments — round-by-round bar charts */}
            {activeTournaments.map(({ tournament: t, picker_count }) => (
              <RoundProgressChart
                key={t.id}
                tournament={t}
                pickerCount={picker_count}
                leagueId={Number(id)}
                leagueMemberCount={league.member_count}
                showRealName={league.show_real_name}
                selected={selectedTournamentId === t.id}
                onSelect={() => setSelectedTournamentId(t.id === selectedTournamentId ? null : t.id)}
              />
            ))}

            {/* Completed + upcoming — sortable table */}
            {tableRows.length > 0 && (
              <div className={`lt-completed-wrap${activeTournaments.length > 0 ? ' lt-completed-wrap--separator' : ''}`}>
                {activeTournaments.length > 0 && <p className="lt-completed-heading">Completed</p>}
                <table className="lt-completed-table">
                  <thead>
                    <tr>
                      <th className="lt-th-tourn">Tournament</th>
                      <th className="lt-th-gender">Tour</th>
                      <SortTh col="tier" active={sortBy === 'tier'} dir={sortDir} onSort={handleSort}>Level</SortTh>
                      <SortTh col="start_date" active={sortBy === 'start_date'} dir={sortDir} onSort={handleSort}>Date</SortTh>
                      <SortTh col="members" active={sortBy === 'members'} dir={sortDir} onSort={handleSort}>Members</SortTh>
                    </tr>
                  </thead>
                  <tbody>
                    {tableRows.map(({ tournament: t, picker_count }) => (
                      <tr
                        key={t.id}
                        className={`lt-completed-row${selectedTournamentId === t.id ? ' lt-completed-row--selected' : ''}`}
                        onClick={() => setSelectedTournamentId(t.id === selectedTournamentId ? null : t.id)}
                      >
                        <td className="lt-td-name">
                          {t.name}
                          <span className="lt-td-year"> {t.year}</span>
                        </td>
                        <td className="lt-td-gender">
                          <span className={`lt-gender-badge lt-gender-badge--${t.gender === 'M' ? 'm' : 'f'}`}>
                            {t.gender === 'M' ? 'ATP' : 'WTA'}
                          </span>
                        </td>
                        <td className="lt-td-tier">{tierLabel(t.category)}</td>
                        <td className="lt-td-date">
                          {t.start_date ? new Date(t.start_date + 'T00:00:00').toLocaleDateString('en-CA', { month: 'short', day: 'numeric' }) : '—'}
                        </td>
                        <td className="lt-td-members">
                          <span className="lt-members-num">{picker_count}</span>
                          <span className="lt-members-label"> / {league.member_count}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
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

// R1=Red R2=Orange R3=Yellow R4=Green R5=Blue R6=Purple R7=Violet
const ROUND_COLORS      = ['#ef4444', '#f97316', '#eab308', '#22c55e', '#3b82f6', '#8b5cf6', '#d946ef']
const ROUND_DARK_COLORS = ['#7f1d1d', '#7c2d12', '#713f12', '#14532d', '#1e3a8a', '#3b0764', '#4a044e']
const ROUND_LABELS = ['R1', 'R2', 'R3', 'R4', 'QF', 'SF', 'F']

function RoundProgressChart({ tournament: t, pickerCount, leagueId, leagueMemberCount, showRealName, selected, onSelect }) {
  const { data = [] } = useQuery({
    queryKey: ['round-scores', leagueId, t.id],
    queryFn: () => getRoundScores(leagueId, t.id),
    refetchInterval: 60_000,
  })

  const maxTotal = Math.max(...data.map(e => e.total), 1)
  // Which rounds have any points scored
  const activeRounds = ROUND_COLORS.map((_, i) => data.some(e => e.round_points[i] > 0) ? i : null).filter(i => i !== null)

  return (
    <div
      className={`lt-progress-block${selected ? ' lt-progress-block--selected' : ''}`}
      onClick={onSelect}
    >
      <div className="lt-progress-header">
        <span className={`lt-gender-badge lt-gender-badge--${t.gender === 'M' ? 'm' : 'f'}`}>
          {t.gender === 'M' ? 'ATP' : 'WTA'} {tierLabel(t.category)}
        </span>
        <span className="lt-progress-title">{t.name} {t.year}</span>
        <span className="lt-progress-meta">{pickerCount}/{leagueMemberCount} competing</span>
      </div>

      {data.length === 0 ? (
        <p className="lt-progress-empty">No picks submitted yet.</p>
      ) : (
        <>
          {activeRounds.length > 0 && (
            <div className="lt-progress-legend">
              {activeRounds.map(i => (
                <span key={i} className="lt-legend-item">
                  <span className="lt-legend-dot" style={{ background: ROUND_COLORS[i] }} />
                  {ROUND_LABELS[i]}
                </span>
              ))}
            </div>
          )}
          <div className="lt-progress-rows">
            {data.map(entry => (
              <div key={entry.user_id} className="lt-progress-row">
                {entry.full_name && entry.full_name !== entry.username ? (
                  <span className="lt-progress-name username-hover" data-tooltip={entry.full_name}>
                    <span className="lt-progress-name-text">{entry.username}</span>
                  </span>
                ) : (
                  <span className="lt-progress-name">
                    <span className="lt-progress-name-text">{entry.username}</span>
                  </span>
                )}
                <div className="lt-bar-track">
                  {entry.round_points.map((pts, i) => pts > 0 ? (
                    <div
                      key={i}
                      className="lt-bar-segment"
                      style={{
                        width: `${(pts / maxTotal) * 100}%`,
                        background: ROUND_COLORS[i],
                      }}
                      title={`${ROUND_LABELS[i]}: ${pts} pts`}
                    >
                      <span className="lt-bar-label" style={{ color: ROUND_DARK_COLORS[i] }}>{pts}</span>
                    </div>
                  ) : null)}
                </div>
                <span className="lt-progress-total">{entry.total} pts</span>
              </div>
            ))}
          </div>
        </>
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
