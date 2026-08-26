import { useState, useEffect } from 'react'
import { useParams, useNavigate, Outlet } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { listLeagues, getLeagueTournaments } from '../api/leagues'
import { getGlobalDraws, getComparePicks } from '../api/tournaments'
import { useAuth } from '../store/auth'
import { CreateLeagueModal, JoinLeagueModal } from './Home'
import './Home.css'
import './Leagues.css'

// The "Global" pseudo-league is rendered by LeagueDetail.jsx itself, for the
// /leagues index route (no :id param) — see App.jsx routing. One component
// for both real leagues and Global, so they can't drift out of sync.

export default function Leagues() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const [modal, setModal] = useState(null)
  // Settings/Invite modal state lives here (not in LeagueDetail) because the
  // buttons that trigger them are rendered in this top bar; LeagueDetail reads
  // them back via useOutletContext to render the actual modal overlays.
  const [editing, setEditing] = useState(false)
  const [showInvite, setShowInvite] = useState(false)

  useEffect(() => { setEditing(false); setShowInvite(false) }, [id])

  const { data: allLeagues } = useQuery({
    queryKey: ['leagues'],
    queryFn: listLeagues,
    enabled: !!user,
  })

  const myLeagues = (allLeagues ?? []).filter(lg =>
    lg.members?.some(m => m.id === user?.id)
  )
  // The API hands a site admin every league; the dropdown's membership
  // filter was quietly hiding the ones they are not in. Grouped after their
  // own so oversight does not bury participation.
  const otherLeagues = user?.is_admin
    ? (allLeagues ?? []).filter(lg => !lg.members?.some(m => m.id === user?.id))
    : []

  const isGlobal = id === undefined
  const currentLeague = !isGlobal ? (allLeagues ?? []).find(lg => lg.id === Number(id)) : null
  const currentLeagueName = isGlobal ? 'Global' : (currentLeague?.name ?? '…')
  const isOwner = !isGlobal && user?.id === currentLeague?.owner?.id
  const canInvite = !isGlobal && (isOwner || currentLeague?.allow_member_invites)
  // Who runs a league: its owner, any member it made admin, or a site admin —
  // the same three the server's _can_manage accepts for update and delete.
  const isLeagueAdmin = !isGlobal
    && (currentLeague?.members ?? []).some(m => m.id === user?.id && m.is_admin)
  const canManageSettings = !isGlobal && (isOwner || isLeagueAdmin || user?.is_admin)

  const selectValue = id != null ? String(id) : 'global'

  return (
    <div className="leagues-page">
      <div className="leagues-page-top">
        <div className="leagues-title-col">
          <h1 className="leagues-page-title">Leagues</h1>
        </div>

        <div className="leagues-name-center">
          <span className="leagues-current-league">{currentLeagueName}</span>
          <div className="leagues-selector-wrap">
            <select
              className="leagues-selector-select"
              value={selectValue}
              aria-label="Choose league"
              onChange={e => {
                const v = e.target.value
                navigate(v === 'global' ? '/leagues' : `/leagues/${v}`)
              }}
            >
              <option value="global">Global</option>
              {myLeagues.map(lg => (
                <option key={lg.id} value={String(lg.id)}>{lg.name}</option>
              ))}
              {otherLeagues.length > 0 && (
                <optgroup label="All leagues (site admin)">
                  {otherLeagues.map(lg => (
                    <option key={lg.id} value={String(lg.id)}>{lg.name}</option>
                  ))}
                </optgroup>
              )}
            </select>
            <span className="leagues-selector-arrow" aria-hidden="true">▾</span>
          </div>
        </div>

        <div className="leagues-top-right">
          {user && (
            <div className="leagues-btn-stack">
              <button className="leagues-stack-btn" onClick={() => setModal('create')}>Create</button>
              <button className="leagues-stack-btn" onClick={() => setModal('join')}>Join</button>
            </div>
          )}
        </div>
      </div>

      <ComparePicks leagueId={isGlobal ? null : Number(id)} isGlobal={isGlobal} />

      {/* Its own row below leagues-page-top entirely (not nested under the
          title) — previously lived inside .leagues-title-col, which made
          that column as wide as these buttons and pushed the league name
          far to the right of "LEAGUES" on narrow screens. */}
      {(canInvite || canManageSettings) && (
        <div className="leagues-actions-under">
          {canInvite && (
            <button className="leagues-icon-btn leagues-icon-btn--labeled" title="Share / Invite" aria-label="Share / Invite" onClick={() => setShowInvite(true)}>
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
              <span>Invite</span>
            </button>
          )}
          {canManageSettings && (
            <button className="leagues-icon-btn" title="Settings" aria-label="Settings" onClick={() => setEditing(s => !s)}>
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
            </button>
          )}
        </div>
      )}

      <Outlet context={{ editing, setEditing, showInvite, setShowInvite }} />
      {modal === 'create' && <CreateLeagueModal onClose={() => setModal(null)} />}
      {modal === 'join'   && <JoinLeagueModal   onClose={() => setModal(null)} />}
    </div>
  )
}


/** Everyone's late-round picks side by side. Collapsed by default: the
    expand arrow sits far left under the league selector, and the table only
    fetches once opened. One table per draw still in play; picks stay hidden
    (server-enforced) until the draw's own visibility rule opens them. */
function ComparePicks({ leagueId, isGlobal }) {
  const [open, setOpen] = useState(false)
  const { data: draws } = useQuery({
    queryKey: isGlobal ? ['global-draws'] : ['league-tournaments', String(leagueId)],
    queryFn: () => isGlobal ? getGlobalDraws() : getLeagueTournaments(leagueId),
    enabled: open,
  })
  const active = (draws ?? [])
    .map(d => d.tournament ?? d)
    .filter(d => d.status !== 'completed')
  return (
    <div className="compare-picks">
      <button
        className="compare-picks-toggle"
        aria-expanded={open}
        onClick={() => setOpen(o => !o)}
      >
        <span className={open ? 'cp-arrow cp-arrow--open' : 'cp-arrow'} aria-hidden="true">▸</span>
        Compare Picks
      </button>
      {open && active.map(d => (
        <CompareTable key={d.id} draw={d} leagueId={leagueId} />
      ))}
      {open && active.length === 0 && (
        <p className="compare-picks-empty">No draws in play.</p>
      )}
    </div>
  )
}

function CompareTable({ draw, leagueId }) {
  const { data } = useQuery({
    queryKey: ['compare-picks', draw.id, leagueId ?? 'global'],
    queryFn: () => getComparePicks(draw.id, leagueId),
    staleTime: 60_000,
  })
  if (!data) return null
  const title = `${draw.name}${draw.gender === 'M' ? ' (ATP)' : draw.gender === 'F' ? ' (WTA)' : ''}`
  if (data.hidden) {
    return (
      <div className="compare-table-card card">
        <h3 className="compare-table-title">{title}</h3>
        <p className="compare-picks-empty">Picks are hidden until the draw locks.</p>
      </div>
    )
  }
  if (!data.users.length) return null
  return (
    <div className="compare-table-card card">
      <h3 className="compare-table-title">{title}</h3>
      <div className="compare-table-scroll">
        <table className="compare-table">
          <thead>
            <tr>
              <th className="compare-table-user">User</th>
              {data.rounds.map(r => <th key={r}>{r}</th>)}
            </tr>
          </thead>
          <tbody>
            {data.users.map(u => (
              <tr key={u.user_id}>
                <td className="compare-table-user">{u.username}</td>
                {data.rounds.map(r => (
                  <td key={r}>
                    {(u.picks[r] ?? []).map((n, i) => (
                      <div key={i} className="compare-pick-name">{n}</div>
                    ))}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
