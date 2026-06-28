import { useState, useMemo, useRef, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getLeague, getLeagueTournaments, getRoundScores, updateLeague, setMemberAdmin, removeMember, deleteLeague, shareLeagueByEmail, getGrandSlamTotals } from '../api/leagues'
import { getGlobalRoundScores } from '../api/tournaments'
import { useAuth } from '../store/auth'
import UserName from '../components/UserName'
import { computeCohortInfo, getDisplayStatus, DISPLAY_STATUS_LABELS } from '../utils/drawStatus.js'
import './LeagueDetail.css'

const SCORING_LABELS = {
  classic: 'Classic Bracket',
  atp_wta: 'ATP/WTA Points Mirror',
  upset_bonus: 'Classic + Upset Bonus',
  custom: 'Custom',
}


function fmtLockTime(closingTime) {
  if (!closingTime) return ''
  const d = new Date(closingTime.endsWith('Z') || closingTime.includes('+') ? closingTime : closingTime + 'Z')
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })
}

function LgToast({ message, onDone }) {
  useEffect(() => { const t = setTimeout(onDone, 4000); return () => clearTimeout(t) }, [onDone])
  return <div className="lt-toast">{message}</div>
}

function tierValue(category) {
  const c = (category || '').toUpperCase()
  if (c.includes('SLAM') || c.includes('GRAND')) return 4
  if (c.includes('1000')) return 3
  if (c.includes('500')) return 2
  return 1
}

const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
function fmtDrawDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr + 'T00:00:00')
  return `${MONTHS[d.getMonth()]} ${String(d.getDate()).padStart(2, '0')}`
}

function tierLabel(category) {
  const c = (category || '').toUpperCase()
  if (c.includes('SLAM') || c.includes('GRAND')) return 'Grand Slam'
  if (c.includes('1000')) return '1000'
  if (c.includes('500')) return '500'
  return '250'
}

export default function LeagueDetail() {
  const { id } = useParams()
  const { user } = useAuth()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [showInvite, setShowInvite] = useState(false)

  const [statusFilter, setStatusFilter] = useState(null) // null = auto (first non-empty)

  const { data: league, isLoading } = useQuery({
    queryKey: ['league', id],
    queryFn: () => getLeague(Number(id)),
  })

  const { data: leagueTournaments = [] } = useQuery({
    queryKey: ['league-tournaments', id],
    queryFn: () => getLeagueTournaments(Number(id)),
    refetchInterval: 60_000,
  })

  const { data: gsData } = useQuery({
    queryKey: ['gs-totals', id],
    queryFn: () => getGrandSlamTotals(Number(id)),
  })

  // Group non-upcoming tournaments by display status: Open → Active → Last Week → Previous.
  // Within each group sort by tier desc, then start_date desc.
  const STATUS_ORDER = { open: 0, active: 1, lastweek: 2, previous: 3 }
  const categoryGroups = useMemo(() => {
    const tournaments = leagueTournaments.map(lt => lt.tournament)
    const cohortInfo = computeCohortInfo(tournaments)
    const groups = new Map()
    for (const lt of leagueTournaments) {
      const ds = getDisplayStatus(lt.tournament, cohortInfo)
      if (ds === 'upcoming') continue
      if (lt.picker_count <= 1) continue
      if (!groups.has(ds)) groups.set(ds, { key: ds, label: DISPLAY_STATUS_LABELS[ds], order: STATUS_ORDER[ds] ?? 9, items: [] })
      groups.get(ds).items.push(lt)
    }
    for (const g of groups.values()) {
      g.items.sort((a, b) => {
        const td = tierValue(b.tournament.category) - tierValue(a.tournament.category)
        if (td !== 0) return td
        return (b.tournament.start_date || '') > (a.tournament.start_date || '') ? 1 : -1
      })
    }
    return [...groups.values()].sort((a, b) => a.order - b.order)
  }, [leagueTournaments])

  if (isLoading) return <div className="page-loading">Loading…</div>
  if (!league) return null

  const isOwner = user?.id === league.owner.id
  const canInvite = isOwner || league.allow_member_invites

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
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" style={{verticalAlign:'-2px',marginRight:'5px'}}><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
              Share / Invite
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

      <div className="league-body-row">
        {/* Draws */}
        <div className="card league-tournaments-section">
          {(() => {
            const STATUS_TABS = ['open', 'active', 'lastweek', 'previous']
            const countByStatus = Object.fromEntries(STATUS_TABS.map(s => [s, 0]))
            for (const g of categoryGroups) countByStatus[g.key] = g.items.length
            const firstNonEmpty = categoryGroups[0]?.key ?? 'open'
            const activeTab = statusFilter ?? firstNonEmpty
            const visibleGroup = categoryGroups.find(g => g.key === activeTab)
            return (
              <>
                <div className="lt-draws-header">
                  <h2>Draws</h2>
                  {categoryGroups.length > 0 && (
                    <div className="lt-status-tabs">
                      {STATUS_TABS.map(s => {
                        const count = countByStatus[s]
                        const empty = count === 0
                        return (
                          <button
                            key={s}
                            className={['lt-status-tab', activeTab === s && 'lt-status-tab--active', empty && 'lt-status-tab--empty'].filter(Boolean).join(' ')}
                            disabled={empty}
                            onClick={() => setStatusFilter(s)}
                          >
                            {DISPLAY_STATUS_LABELS[s]} ({count})
                          </button>
                        )
                      })}
                    </div>
                  )}
                </div>
                {categoryGroups.length === 0 ? (
                  <p className="muted">No picks have been submitted yet. Members can make picks from the Tournaments page.</p>
                ) : !visibleGroup ? (
                  <p className="muted">No draws for this status.</p>
                ) : (
                  <div className="lt-category-group">
                    {visibleGroup.items.map(({ tournament: t, picker_count }) => (
                      <RoundProgressChart
                        key={t.id}
                        tournament={t}
                        pickerCount={picker_count}
                        leagueId={Number(id)}
                        leagueMemberCount={league.member_count}
                        showRealName={league.show_real_name}
                      />
                    ))}
                  </div>
                )}
              </>
            )
          })()}
        </div>

        {/* Members sidebar */}
        <div className="card league-members-section">
          <h2>Members</h2>
          <p className="league-members-subtitle">{gsData?.year ?? new Date().getFullYear()} Grand Slam Point Tally</p>
          <table className="league-members-table">
            <thead>
              <tr>
                <th className="lmt-name" />
                <th className="lmt-pts">ATP</th>
                <th className="lmt-pts">WTA</th>
              </tr>
            </thead>
            <tbody>
              {(gsData?.members ?? league.members.map(m => ({ user_id: m.id, username: m.username, full_name: m.full_name, atp_points: null, wta_points: null }))).map(m => (
                <tr key={m.user_id}>
                  <td className="lmt-name" title={m.username}>
                    <a href={`/draw-history?user=${m.user_id}`} target="_blank" rel="noopener noreferrer" className="lmt-name-link">
                      <UserName user={{ id: m.user_id, username: m.username, full_name: m.full_name }} showRealName={league.show_real_name} />
                    </a>
                  </td>
                  <td className="lmt-pts">{m.atp_points ?? '–'}</td>
                  <td className="lmt-pts">{m.wta_points ?? '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

    </div>
  )
}

// R1=Red R2=Orange R3=Yellow R4=Green R5=Blue R6=Purple R7=Violet
const ROUND_COLORS      = ['#ef4444', '#f97316', '#eab308', '#22c55e', '#3b82f6', '#8b5cf6', '#d946ef']
const ROUND_DARK_COLORS = ['#7f1d1d', '#7c2d12', '#713f12', '#14532d', '#1e3a8a', '#3b0764', '#4a044e']
function getRoundLabel(index, numRounds) {
  const fromEnd = numRounds - 1 - index
  if (fromEnd === 0) return 'F'
  if (fromEnd === 1) return 'SF'
  if (fromEnd === 2) return 'QF'
  return `R${index + 1}`
}

export function RoundProgressChart({ tournament: t, pickerCount, leagueId, leagueMemberCount, showRealName }) {
  const { user } = useAuth()
  const [toast, setToast] = useState(null)
  const toastKey = useRef(0)
  const { data: rawData } = useQuery({
    queryKey: leagueId != null ? ['round-scores', leagueId, t.id] : ['global-round-scores', t.id],
    queryFn: leagueId != null ? () => getRoundScores(leagueId, t.id) : () => getGlobalRoundScores(t.id),
    refetchInterval: 60_000,
  })

  const entries = rawData?.entries ?? []
  const completedMatchesCount = rawData?.completed_matches_count ?? 0
  const roundsWithMatches = rawData?.rounds_with_matches ?? []

  const numRounds = entries.length > 0 ? entries[0].round_points.length : (t.num_rounds ?? ROUND_COLORS.length)
  const finalPlayed = roundsWithMatches.includes(numRounds)
  const PLACE_ICONS = ['🏆', '🥈', '🥉']
  // rounds_with_matches is 1-indexed; convert to 0-indexed
  const activeRounds = roundsWithMatches.length > 0
    ? roundsWithMatches.map(r => r - 1)
    : Array.from({ length: numRounds }, (_, i) => i).filter(i => entries.some(e => e.round_points[i] > 0))
  const perRoundMax = activeRounds.map(i => {
    const vals = entries.map(e => e.round_points[i] ?? 0)
    return Math.max(...vals, 1)
  })

  // A round is complete when the next round has started, or it's the last played round and the final was played
  const completedRoundNums = new Set(
    roundsWithMatches.filter((r, i) => i < roundsWithMatches.length - 1 || finalPlayed)
  )
  // For each active column, the set of user_ids who won that round (null = round not yet complete or no points)
  const roundWinnerSets = activeRounds.map((roundIdx) => {
    if (!completedRoundNums.has(roundIdx + 1)) return null
    const maxPts = Math.max(...entries.map(e => e.round_points[roundIdx] ?? 0))
    if (maxPts <= 0) return null
    return new Set(entries.filter(e => (e.round_points[roundIdx] ?? 0) === maxPts).map(e => e.user_id))
  })
  const userById = Object.fromEntries(entries.map(e => [e.user_id, e.username]))
  const roundWinnerLabels = activeRounds.map((_, col) => {
    const ws = roundWinnerSets[col]
    if (!ws || ws.size === 0) return null
    const names = [...ws].map(uid => userById[uid] ?? '?').sort()
    const others = names.length - 1
    return others > 0
      ? `Round Winner: ${names[0]} + ${others} other${others > 1 ? 's' : ''}`
      : `Round Winner: ${names[0]}`
  })

  return (
    <div className="lt-progress-block">
      <div className="lt-progress-header">
        <div className="lt-header-left">
          <span className={`lt-gender-badge lt-gender-badge--${t.gender === 'M' ? 'm' : 'f'}`}>
            {t.gender === 'M' ? 'ATP' : 'WTA'} {tierLabel(t.category)}
          </span>
          {(t.start_date || t.end_date) && (
            <span className="lt-progress-date">
              {fmtDrawDate(t.start_date)}{t.end_date ? ` – ${fmtDrawDate(t.end_date)}` : ''}
            </span>
          )}
        </div>
        <span className="lt-progress-title">{t.name} {t.year}</span>
        {t.surface && <span className="lt-progress-meta">{t.surface}</span>}
      </div>

      {toast && <LgToast key={toast.key} message={toast.msg} onDone={() => setToast(null)} />}
      {entries.length === 0 ? (
        <p className="lt-progress-empty">No picks submitted yet.</p>
      ) : (
        <>
          <div className="lt-progress-row lt-progress-header-row">
            <span /><span /><span />
            <div className="lt-bar-track">
              {activeRounds.map((i, col) => (
                <div key={i} className="lt-bar-col lt-bar-col--label" style={{ flex: perRoundMax[col] }} title={roundWinnerLabels[col] ?? undefined}>
                  {getRoundLabel(i, numRounds)}
                </div>
              ))}
            </div>
            <span className="lt-progress-total lt-progress-col-header">Score</span>
            {completedMatchesCount > 0 && (
              <span className="lt-progress-correct lt-progress-col-header"># Correct</span>
            )}
          </div>
          <div className="lt-progress-rows">
            {entries.map((entry, entryIndex) => (
              <div key={entry.user_id} className="lt-progress-row">
                <span className="lt-pos-num">{entryIndex + 1}.</span>
                {entry.full_name && entry.full_name !== entry.username ? (
                  <span className="lt-progress-name username-hover" data-tooltip={entry.full_name}>
                    {finalPlayed && entryIndex < 3 && <span className="lt-place-icon">{PLACE_ICONS[entryIndex]}</span>}
                    <span className="lt-progress-name-text">{entry.username}</span>
                  </span>
                ) : (
                  <span className="lt-progress-name">
                    {finalPlayed && entryIndex < 3 && <span className="lt-place-icon">{PLACE_ICONS[entryIndex]}</span>}
                    <span className="lt-progress-name-text">{entry.username}</span>
                  </span>
                )}
                <button
                  className="lt-bracket-btn"
                  title={`View ${entry.username}'s bracket`}
                  onClick={e => {
                    e.stopPropagation()
                    if (t.status === 'open' && entry.user_id !== user?.id) {
                      toastKey.current += 1
                      const lockStr = fmtLockTime(t.closing_time)
                      setToast({ key: toastKey.current, msg: `Opponents' picks will be available after pick selection closes${lockStr ? ': ' + lockStr : ''}.` })
                      return
                    }
                    window.open(`/tournaments/${t.id}?user=${entry.user_id}&league=${leagueId}`, '_blank')
                  }}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
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
                </button>
                <div className="lt-bar-track">
                  {activeRounds.map((i, col) => {
                    const pts = entry.round_points[i]
                    const fillPct = (pts / perRoundMax[col]) * 100
                    const isWinner = roundWinnerSets[col]?.has(entry.user_id) ?? false
                    return (
                      <div key={i} className="lt-bar-col" style={{ flex: perRoundMax[col] }} title={roundWinnerLabels[col] ?? undefined}>
                        {pts > 0 ? (
                          <div
                            className={`lt-bar-segment${isWinner ? ' lt-bar-winner' : ''}`}
                            style={{ width: `${fillPct}%`, background: ROUND_COLORS[i] }}
                          >
                            <span className="lt-bar-label" style={{ color: ROUND_DARK_COLORS[i] }}>{pts}</span>
                          </div>
                        ) : (
                          <span className="lt-bar-zero">0</span>
                        )}
                      </div>
                    )
                  })}
                </div>
                <span className="lt-progress-total">{entry.total} pts</span>
                {completedMatchesCount > 0 && (
                  <span className="lt-progress-correct">
                    {entry.correct_count}/{completedMatchesCount}
                  </span>
                )}
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
  const [emailInput, setEmailInput] = useState('')
  const [sendResults, setSendResults] = useState(null)

  const copy = () => {
    navigator.clipboard.writeText(league.invite_code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const sendMutation = useMutation({
    mutationFn: () => shareLeagueByEmail(league.id, emailInput),
    onSuccess: (data) => setSendResults(data.results),
  })

  return (
    <div className="invite-modal-overlay" onClick={onClose}>
      <div className="invite-modal" onClick={e => e.stopPropagation()}>
        <div className="invite-modal-header">
          <h3>Share League</h3>
          <button className="invite-modal-close" onClick={onClose}>✕</button>
        </div>

        <div className="invite-section-heading">Share via Invite Code</div>
        <p className="invite-modal-msg">
          Tell friends to click <strong>Join</strong> from the dashboard and enter this code.
        </p>
        <div className="invite-code-block">
          <div className="invite-code-label">Invite Code</div>
          <div className="invite-code-value">{league.invite_code}</div>
        </div>
        <button className="btn-primary invite-copy-btn" onClick={copy}>
          {copied ? '✓ Copied!' : 'Copy Invite Code'}
        </button>

        <div className="invite-or-divider"><span>OR</span></div>
        <div className="invite-section-heading invite-section-heading--email">Share via Email</div>
        {sendResults ? (
          <div className="invite-email-results">
            {sendResults.map((r, i) => (
              <div key={i} className={`invite-email-result invite-email-result--${r.status}`}>
                {r.status === 'added' && <>✓ <strong>{r.email}</strong> — added to league as <strong>@{r.username}</strong></>}
                {r.status === 'invited' && <>✉ <strong>{r.email}</strong> — invite sent</>}
                {r.status === 'already_member' && <>· <strong>{r.email}</strong> — already a member (@{r.username})</>}
              </div>
            ))}
            <button className="invite-email-again" onClick={() => { setSendResults(null); setEmailInput('') }}>
              Send more invites
            </button>
          </div>
        ) : (
          <>
            <textarea
              className="invite-email-input"
              placeholder="Enter email addresses, separated by commas"
              value={emailInput}
              onChange={e => setEmailInput(e.target.value)}
              rows={3}
            />
            {sendMutation.isError && (
              <p className="invite-email-error">Failed to send — please try again.</p>
            )}
            <button
              className="btn-primary invite-copy-btn"
              onClick={() => sendMutation.mutate()}
              disabled={sendMutation.isPending || !emailInput.trim()}
            >
              {sendMutation.isPending ? 'Sending…' : 'Send Invites'}
            </button>
          </>
        )}
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
                    title={m.is_admin ? 'Remove league admin' : 'Make league admin'}
                  >
                    {m.is_admin ? 'Remove League Admin' : 'Make League Admin'}
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
