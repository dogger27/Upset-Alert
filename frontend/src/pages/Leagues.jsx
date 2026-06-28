import { useState, useMemo } from 'react'
import { useParams, useNavigate, Outlet } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { listLeagues } from '../api/leagues'
import { listTournaments } from '../api/tournaments'
import { useAuth } from '../store/auth'
import { computeCohortInfo, getDisplayStatus, DISPLAY_STATUS_LABELS } from '../utils/drawStatus.js'
import { RoundProgressChart } from './LeagueDetail'
import './Leagues.css'

function LeaguesNav({ myLeagues, currentId }) {
  const navigate = useNavigate()
  return (
    <nav className="leagues-nav-panel">
      <div className="leagues-nav-bubble">
        <button
          className={`leagues-nav-item${!currentId ? ' leagues-nav-item--active' : ''}`}
          onClick={() => navigate('/leagues')}
        >
          <span className="leagues-nav-name">Global</span>
        </button>
        {myLeagues.map(lg => (
          <button
            key={lg.id}
            className={`leagues-nav-item${currentId === lg.id ? ' leagues-nav-item--active' : ''}`}
            onClick={() => navigate(`/leagues/${lg.id}`)}
          >
            <span className="leagues-nav-name">{lg.name}</span>
          </button>
        ))}
      </div>
    </nav>
  )
}

const STATUS_TABS = ['open', 'active', 'lastweek', 'previous']
const STATUS_ORDER = { open: 0, active: 1, lastweek: 2, previous: 3 }

function tierValue(category) {
  const c = (category || '').toUpperCase()
  if (c.includes('SLAM') || c.includes('GRAND')) return 4
  if (c.includes('1000')) return 3
  if (c.includes('500')) return 2
  return 1
}

export function GlobalLeagueView() {
  const [statusFilter, setStatusFilter] = useState(null)
  const [selectedTournamentId, setSelectedTournamentId] = useState(null)

  const { data: tournaments = [] } = useQuery({
    queryKey: ['tournaments'],
    queryFn: listTournaments,
    refetchInterval: 60_000,
  })

  const categoryGroups = useMemo(() => {
    const cohortInfo = computeCohortInfo(tournaments)
    const groups = new Map()
    for (const t of tournaments) {
      const ds = getDisplayStatus(t, cohortInfo)
      if (ds === 'upcoming') continue
      if (!groups.has(ds)) groups.set(ds, { key: ds, label: DISPLAY_STATUS_LABELS[ds], order: STATUS_ORDER[ds] ?? 9, items: [] })
      groups.get(ds).items.push(t)
    }
    for (const g of groups.values()) {
      g.items.sort((a, b) => {
        const td = tierValue(b.category) - tierValue(a.category)
        if (td !== 0) return td
        return (b.start_date || '') > (a.start_date || '') ? 1 : -1
      })
    }
    return [...groups.values()].sort((a, b) => a.order - b.order)
  }, [tournaments])

  const countByStatus = Object.fromEntries(STATUS_TABS.map(s => [s, 0]))
  for (const g of categoryGroups) countByStatus[g.key] = g.items.length
  const firstNonEmpty = categoryGroups[0]?.key ?? 'open'
  const activeTab = statusFilter ?? firstNonEmpty
  const visibleGroup = categoryGroups.find(g => g.key === activeTab)

  return (
    <div className="league-detail">
      <div className="league-detail-header">
        <div>
          <h1>Global</h1>
          <p className="muted">All registered players · Classic scoring</p>
        </div>
      </div>

      <div className="card league-tournaments-section">
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
                    onClick={() => { setStatusFilter(s); setSelectedTournamentId(null) }}
                  >
                    {DISPLAY_STATUS_LABELS[s]} ({count})
                  </button>
                )
              })}
            </div>
          )}
        </div>
        {categoryGroups.length === 0 ? (
          <p className="muted">No draws available.</p>
        ) : !visibleGroup ? (
          <p className="muted">No draws for this status.</p>
        ) : (
          <div className="lt-category-group">
            {visibleGroup.items.map(t => (
              <RoundProgressChart
                key={t.id}
                tournament={t}
                leagueId={null}
                leagueMemberCount={null}
                selected={selectedTournamentId === t.id}
                onSelect={() => setSelectedTournamentId(t.id === selectedTournamentId ? null : t.id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
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
