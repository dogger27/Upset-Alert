import { useState } from 'react'
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

function LeagueSelector({ myLeagues, currentId }) {
  const navigate = useNavigate()
  const value = currentId != null ? String(currentId) : 'global'
  return (
    <div className="league-selector">
      <label className="league-selector-label">Selected League:</label>
      <select
        className="league-selector-select"
        value={value}
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
    </div>
  )
}

export default function Leagues() {
  const { id } = useParams()
  const { user } = useAuth()
  const [modal, setModal] = useState(null)

  const { data: allLeagues } = useQuery({
    queryKey: ['leagues'],
    queryFn: listLeagues,
    enabled: !!user,
  })

  const myLeagues = (allLeagues ?? []).filter(lg =>
    lg.members?.some(m => m.id === user?.id)
  )

  return (
    <div className="leagues-page">
      <div className="leagues-page-top">
        <h1 className="leagues-page-title">Leagues</h1>
        <div className="leagues-top-right">
          <LeagueSelector myLeagues={myLeagues} currentId={id ? Number(id) : null} />
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
