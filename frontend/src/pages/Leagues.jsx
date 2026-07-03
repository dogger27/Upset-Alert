import { useState, useRef, useEffect } from 'react'
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

function LeagueSelector({ myLeagues, currentId, onNavigate }) {
  const navigate = useNavigate()
  const value = currentId != null ? String(currentId) : 'global'
  return (
    <select
      className="league-selector-select"
      autoFocus
      value={value}
      onChange={e => {
        const v = e.target.value
        navigate(v === 'global' ? '/leagues' : `/leagues/${v}`)
        onNavigate?.()
      }}
    >
      <option value="global">Global</option>
      {myLeagues.map(lg => (
        <option key={lg.id} value={String(lg.id)}>{lg.name}</option>
      ))}
    </select>
  )
}

export default function Leagues() {
  const { id } = useParams()
  const { user } = useAuth()
  const [modal, setModal] = useState(null)
  const [selectorOpen, setSelectorOpen] = useState(false)
  const titleGroupRef = useRef(null)

  useEffect(() => {
    if (!selectorOpen) return
    const handler = (e) => {
      if (titleGroupRef.current && !titleGroupRef.current.contains(e.target)) setSelectorOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [selectorOpen])

  const { data: allLeagues } = useQuery({
    queryKey: ['leagues'],
    queryFn: listLeagues,
    enabled: !!user,
  })

  const myLeagues = (allLeagues ?? []).filter(lg =>
    lg.members?.some(m => m.id === user?.id)
  )

  const currentLeagueName = id != null
    ? (allLeagues ?? []).find(lg => lg.id === Number(id))?.name ?? '…'
    : 'Global'

  return (
    <div className="leagues-page">
      <div className="leagues-page-top">
        <div className="leagues-title-group" ref={titleGroupRef}>
          <h1 className="leagues-page-title">Leagues</h1>
          <span className="leagues-current-league">{currentLeagueName}</span>
          <button
            className="leagues-selector-toggle"
            onClick={() => setSelectorOpen(o => !o)}
            aria-label="Choose league"
            aria-expanded={selectorOpen}
          >▾</button>
          {selectorOpen && (
            <div className="leagues-selector-popover">
              <LeagueSelector
                myLeagues={myLeagues}
                currentId={id ? Number(id) : null}
                onNavigate={() => setSelectorOpen(false)}
              />
            </div>
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
      <Outlet />
      {modal === 'create' && <CreateLeagueModal onClose={() => setModal(null)} />}
      {modal === 'join'   && <JoinLeagueModal   onClose={() => setModal(null)} />}
    </div>
  )
}
