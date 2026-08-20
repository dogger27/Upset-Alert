import { useState, useEffect, useRef } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useQuery, useQueries } from '@tanstack/react-query'
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

// overlay: compact (phone) draw mode — the sidebar floats over the draw
// instead of taking flex-row space, so the bracket can use the full width.
// showOop: render the order-of-play button in this sidebar. Now set on every
// screen — the sidebar's top-left is where it lives, phone and desktop alike,
// so there is one place to look for it rather than two depending on width.
export default function DrawSidebar({ tournamentId, tournament, selectedUserId, defaultLeagueId, onSelectUser, onLeagueChange, collapsed = false, onToggleCollapsed, overlay = false, showOop = false }) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [selectedLeagueId, setSelectedLeagueId] = useState(defaultLeagueId ?? 'global')

  // Publish the active league so the draw itself can scope per-match views to
  // it (the predictors popup). From an effect, not the change handler, so the
  // initial value — which may come from the ?league= deep link — is published
  // too. The callback is held in a ref so an inline arrow from the parent
  // can't turn this into a re-render loop.
  const leagueCbRef = useRef(onLeagueChange)
  leagueCbRef.current = onLeagueChange
  useEffect(() => {
    leagueCbRef.current?.(selectedLeagueId === 'global' ? null : Number(selectedLeagueId))
  }, [selectedLeagueId])
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

  // Fetch leaderboard for every user league in parallel to get per-draw picker counts
  const leagueLeaderboardResults = useQueries({
    queries: myLeagues.map(lg => ({
      queryKey: ['leaderboard', lg.id, tournamentId],
      queryFn: () => getLeaderboard(lg.id, tournamentId),
      enabled: !!user,
    })),
  })

  // null = still loading; 0 = no pickers; N = N pickers
  const leaguePickerCount = {}
  myLeagues.forEach((lg, i) => {
    const d = leagueLeaderboardResults[i]
    leaguePickerCount[lg.id] = d?.isLoading ? null : (d?.data?.entries?.length ?? 0)
  })

  // Only show leagues where ≥2 members competed; show all while still loading
  const visibleLeagues = myLeagues.filter(lg =>
    leaguePickerCount[lg.id] === null || leaguePickerCount[lg.id] >= 2
  )

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
    if (!user?.is_admin && status !== 'active' && status !== 'completed') {
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
    <aside className={`draw-sidebar${collapsed ? ' draw-sidebar--collapsed' : ''}${overlay ? ' draw-sidebar--overlay' : ''}${showOop && !collapsed ? ' draw-sidebar--with-oop' : ''}`}>
      <button
        className="sidebar-collapse-btn"
        onClick={() => onToggleCollapsed?.()}
        title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        {/* Invisible sizer forcing this button to the same width/height as
            the round-nav pager button, in every draw mode (same trick, same
            text — see .round-nav-label--sizer in TournamentDraw.css). */}
        {collapsed && (
          <span className="round-nav-label round-nav-label--sizer" aria-hidden="true">CHAMP</span>
        )}
        <span className="sidebar-collapse-glyph">{collapsed ? '›' : '‹'}</span>
      </button>

      {/* Mirrors the collapse button across the top of the open sidebar. Only
          while expanded — collapsed it is a narrow strip with no room. A
          gated on oop_first_seen_at, not oop_url: the latter holds only TODAY's
          PDF and goes null overnight and between rounds, which greyed the
          button out even though the parsed schedule was still there to show.
          Once a tournament has published an order of play, we have one. */}
      {showOop && !collapsed && (
        tournament?.oop_first_seen_at ? (
          <Link
            to={`/schedule?tournament=${tournament.tournament_id}&draw=${tournament.id}${tournament.oop_date ? `&date=${tournament.oop_date}` : ''}`}
            className="sidebar-oop-btn"
            title="Today's order of play"
          >
            Order of Play
          </Link>
        ) : (
          <span
            className="sidebar-oop-btn sidebar-oop-btn--none"
            title="No order of play published for today yet"
            aria-disabled="true"
          >
            Order of Play
          </span>
        )
      )}

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
            <div className="sidebar-league-select-row">
              <select
                className="sidebar-select"
                value={selectedLeagueId}
                onChange={e => {
                  setSelectedLeagueId(e.target.value)
                  onSelectUser(null)
                }}
              >
                <option value="global">Global{globalEntries.length > 0 ? ` (${globalEntries.length})` : ''}</option>
                {visibleLeagues.map(lg => {
                  const count = leaguePickerCount[lg.id]
                  return (
                    <option key={lg.id} value={lg.id}>
                      {lg.name}{count != null ? ` (${count})` : ''}
                    </option>
                  )
                })}
              </select>
              <button
                type="button"
                className="sidebar-league-goto-btn"
                title="Go to this league's page"
                aria-label="Go to this league's page"
                onClick={() => navigate(isGlobal ? '/leagues' : `/leagues/${selectedLeagueId}`)}
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                  <circle cx="9" cy="7" r="4" />
                  <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                  <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                </svg>
              </button>
            </div>
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
                    const noUpset = entry.has_upset_pick === false
                    return (
                      <li
                        key={m.id}
                        className={['sidebar-member sidebar-member--standing sidebar-member--global', isActive && 'sidebar-member--selected', noUpset && 'sidebar-member--no-upset'].filter(Boolean).join(' ')}
                        onClick={() => handleMemberClick(m.id, m.username)}
                        title={noUpset ? `${m.display_name} (must pick at least 1 upset to compete)` : m.display_name}
                      >
                        <span className="sidebar-rank">{i + 1}</span>
                        <span className="sidebar-points">{entry.total_points % 1 === 0 ? entry.total_points : entry.total_points.toFixed(1)}</span>
                        <span className="sidebar-member-name">@{m.username}</span>
                        <button
                          type="button"
                          className="sidebar-user-history-btn"
                          title={`${m.username}'s Draw History`}
                          aria-label={`${m.username}'s Draw History`}
                          onClick={e => { e.stopPropagation(); navigate(`/draw-history?user=${m.id}`) }}
                        >
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                            <circle cx="12" cy="7" r="4" />
                          </svg>
                        </button>
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
                    const noUpset = entry.has_upset_pick === false
                    return (
                      <li
                        key={m.id}
                        className={['sidebar-member sidebar-member--standing sidebar-member--global', isActive && 'sidebar-member--selected', noUpset && 'sidebar-member--no-upset'].filter(Boolean).join(' ')}
                        onClick={() => handleMemberClick(m.id, m.username)}
                        title={noUpset ? `${m.display_name} (must pick at least 1 upset to compete)` : m.display_name}
                      >
                        <span className="sidebar-rank">{i + 1}</span>
                        <span className="sidebar-points">{entry.total_points % 1 === 0 ? entry.total_points : entry.total_points.toFixed(1)}</span>
                        <span className="sidebar-member-name">@{m.username}</span>
                        <button
                          type="button"
                          className="sidebar-user-history-btn"
                          title={`${m.username}'s Draw History`}
                          aria-label={`${m.username}'s Draw History`}
                          onClick={e => { e.stopPropagation(); navigate(`/draw-history?user=${m.id}`) }}
                        >
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                            <circle cx="12" cy="7" r="4" />
                          </svg>
                        </button>
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
