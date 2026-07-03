import { useState, useEffect } from 'react'
import { useParams, useNavigate, Outlet } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { listLeagues } from '../api/leagues'
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

  const isGlobal = id === undefined
  const currentLeague = !isGlobal ? (allLeagues ?? []).find(lg => lg.id === Number(id)) : null
  const currentLeagueName = isGlobal ? 'Global' : (currentLeague?.name ?? '…')
  const isOwner = !isGlobal && user?.id === currentLeague?.owner?.id
  const canInvite = !isGlobal && (isOwner || currentLeague?.allow_member_invites)

  const selectValue = id != null ? String(id) : 'global'

  return (
    <div className="leagues-page">
      <div className="leagues-page-top">
        <div className="leagues-title-group">
          <h1 className="leagues-page-title">Leagues</h1>
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
            </select>
            <span className="leagues-selector-arrow" aria-hidden="true">▾</span>
          </div>

          {canInvite && (
            <button className="leagues-icon-btn" title="Share / Invite" aria-label="Share / Invite" onClick={() => setShowInvite(true)}>
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
            </button>
          )}
          {isOwner && (
            <button className="leagues-icon-btn" title="Settings" aria-label="Settings" onClick={() => setEditing(s => !s)}>
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
            </button>
          )}
        </div>
        <div className="leagues-top-right">
          {user && (
            <>
              <button className="btn-secondary leagues-action-btn" onClick={() => setModal('join')}>Join League</button>
              <button className="btn-primary leagues-action-btn" onClick={() => setModal('create')}>Create League</button>
            </>
          )}
        </div>
      </div>

      <Outlet context={{ editing, setEditing, showInvite, setShowInvite }} />
      {modal === 'create' && <CreateLeagueModal onClose={() => setModal(null)} />}
      {modal === 'join'   && <JoinLeagueModal   onClose={() => setModal(null)} />}
    </div>
  )
}
