import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { listLeagues, getLeaderboard } from '../api/leagues'
import { getGlobalStandings } from '../api/tournaments'
import { useAuth } from '../store/auth'
import './DrawSidebar.css'

function fmtLockTime(closingTime) {
  if (!closingTime) return ''
  const d = new Date(closingTime.endsWith('Z') || closingTime.includes('+') ? closingTime : closingTime + 'Z')
  return d.toLocaleString('en-US', {
    month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit',
    timeZoneName: 'short',
  })
}

function Toast({ message, onDone }) {
  useEffect(() => {
    const t = setTimeout(onDone, 3500)
    return () => clearTimeout(t)
  }, [onDone])

  return <div className="sidebar-toast">{message}</div>
}

export default function DrawSidebar({ tournamentId, tournament, selectedUserId, onSelectUser }) {
  const { user } = useAuth()
  const [collapsed, setCollapsed] = useState(false)
  const [selectedLeagueId, setSelectedLeagueId] = useState('global')
  const [toast, setToast] = useState(null)
  const toastKey = useRef(0)

  const { data: leagues } = useQuery({
    queryKey: ['leagues'],
    queryFn: listLeagues,
    enabled: !!user,
  })

  const myLeagues = leagues?.filter(lg =>
    lg.members?.some(m => m.id === user?.id)
  ) ?? []

  const isGlobal = selectedLeagueId === 'global'

  const { data: globalStandings } = useQuery({
    queryKey: ['standings', tournamentId],
    queryFn: () => getGlobalStandings(tournamentId),
  })

  const leagueId = isGlobal ? null : Number(selectedLeagueId)
  const { data: leaderboard } = useQuery({
    queryKey: ['leaderboard', leagueId, tournamentId],
    queryFn: () => getLeaderboard(leagueId, tournamentId),
    enabled: !isGlobal && leagueId != null,
  })

  // Global: standings entries with rank+points; League: leaderboard entries
  const globalEntries = globalStandings ?? []
  const leagueEntries = leaderboard?.entries ?? []

  // The user whose draw is currently displayed — always shown dark green
  const activeDrawUserId = selectedUserId ?? user?.id

  function handleMemberClick(memberId, username) {
    if (memberId === user?.id) {
      onSelectUser(memberId === selectedUserId ? null : memberId, username)
      return
    }
    const status = tournament?.status
    if (status !== 'active' && status !== 'completed') {
      const lockStr = fmtLockTime(tournament?.closing_time)
      toastKey.current += 1
      setToast({
        key: toastKey.current,
        msg: `Opponents' picks will be available after pick selection closes${lockStr ? ': ' + lockStr : ''}.`,
      })
      return
    }
    onSelectUser(memberId === selectedUserId ? null : memberId, username)
  }

  return (
    <aside className={`draw-sidebar${collapsed ? ' draw-sidebar--collapsed' : ''}`}>
      <button
        className="sidebar-collapse-btn"
        onClick={() => setCollapsed(c => !c)}
        title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        {collapsed ? '›' : '‹'}
      </button>

      {!collapsed && toast && (
        <Toast
          key={toast.key}
          message={toast.msg}
          onDone={() => setToast(null)}
        />
      )}

      {!collapsed && (
        <>
          <div className="sidebar-league-select">
            <label className="sidebar-select-label">League</label>
            <select
              className="sidebar-select"
              value={selectedLeagueId}
              onChange={e => {
                setSelectedLeagueId(e.target.value)
                onSelectUser(null)
              }}
            >
              <option value="global">Global{globalEntries.length > 0 ? ` (${globalEntries.length})` : ''}</option>
              {myLeagues.map(lg => (
                <option key={lg.id} value={lg.id}>{lg.name}{lg.member_count > 0 ? ` (${lg.member_count})` : ''}</option>
              ))}
            </select>
          </div>

          <div className="sidebar-members">
            {isGlobal ? (
              <>
                <div className="sidebar-section-title">Standings</div>
                <div className="sidebar-members-count sidebar-standing-header sidebar-standing-header--global">
                  <span>#</span>
                  <span>Pts</span>
                  <span>User</span>
                </div>
                {globalEntries.length === 0 && (
                  <p className="sidebar-empty">No picks submitted yet.</p>
                )}
                <ul className="sidebar-member-list">
                  {globalEntries.map((entry, i) => {
                    const m = entry.user
                    const isActive = m.id === activeDrawUserId
                    return (
                      <li
                        key={m.id}
                        className={['sidebar-member sidebar-member--standing sidebar-member--global', isActive && 'sidebar-member--selected'].filter(Boolean).join(' ')}
                        onClick={() => handleMemberClick(m.id, m.username)}
                        title={m.display_name}
                      >
                        <span className="sidebar-rank">{i + 1}</span>
                        <span className="sidebar-points">{entry.total_points % 1 === 0 ? entry.total_points : entry.total_points.toFixed(1)}</span>
                        <span className="sidebar-member-name">@{m.username}</span>
                      </li>
                    )
                  })}
                </ul>
              </>
            ) : (
              <>
                <div className="sidebar-section-title">Standings</div>
                <div className="sidebar-members-count sidebar-standing-header sidebar-standing-header--global">
                  <span>#</span>
                  <span>Pts</span>
                  <span>User</span>
                </div>
                {leagueEntries.length === 0 && (
                  <p className="sidebar-empty">No picks submitted yet.</p>
                )}
                <ul className="sidebar-member-list">
                  {leagueEntries.map((entry, i) => {
                    const m = entry.user
                    const isActive = m.id === activeDrawUserId
                    return (
                      <li
                        key={m.id}
                        className={['sidebar-member sidebar-member--standing sidebar-member--global', isActive && 'sidebar-member--selected'].filter(Boolean).join(' ')}
                        onClick={() => handleMemberClick(m.id, m.username)}
                        title={m.display_name}
                      >
                        <span className="sidebar-rank">{i + 1}</span>
                        <span className="sidebar-points">{entry.total_points % 1 === 0 ? entry.total_points : entry.total_points.toFixed(1)}</span>
                        <span className="sidebar-member-name">@{m.username}</span>
                      </li>
                    )
                  })}
                </ul>
              </>
            )}
          </div>
        </>
      )}
    </aside>
  )
}
