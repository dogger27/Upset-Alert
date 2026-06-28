import { useParams, useNavigate, Outlet } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { listLeagues } from '../api/leagues'
import { useAuth } from '../store/auth'
import './Leagues.css'

function LeaguesNav({ myLeagues, currentId }) {
  const navigate = useNavigate()
  return (
    <nav className="leagues-nav-panel">
      <button
        className={`leagues-nav-item${!currentId ? ' leagues-nav-item--active' : ''}`}
        onClick={() => navigate('/')}
      >
        <span className="leagues-nav-name">Global</span>
        <span className="leagues-nav-count">🌍</span>
      </button>
      {myLeagues.map(lg => (
        <button
          key={lg.id}
          className={`leagues-nav-item${currentId === lg.id ? ' leagues-nav-item--active' : ''}`}
          onClick={() => navigate(`/leagues/${lg.id}`)}
        >
          <span className="leagues-nav-name">{lg.name}</span>
          <span className="leagues-nav-count">{lg.member_count}</span>
        </button>
      ))}
    </nav>
  )
}

export default function Leagues() {
  const { id } = useParams()
  const { user } = useAuth()

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
      </div>
      <div className="leagues-layout">
        <LeaguesNav myLeagues={myLeagues} currentId={id ? Number(id) : null} />
        <div className="leagues-detail-area">
          <Outlet />
        </div>
      </div>
    </div>
  )
}
