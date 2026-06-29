import { useState, useMemo } from 'react'
import { useParams, useNavigate, Outlet } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { listLeagues } from '../api/leagues'
import { getGlobalDraws, getGlobalGSTotals, listTournaments } from '../api/tournaments'
import { getDrawCounts } from '../api/auth'
import { useAuth } from '../store/auth'
import { computeCohortInfo, getDisplayStatus, DISPLAY_STATUS_LABELS } from '../utils/drawStatus.js'
import { RoundProgressChart } from './LeagueDetail'
import { CreateLeagueModal, JoinLeagueModal } from './Home'
import './Home.css'
import './Leagues.css'

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

  const { data: globalDraws = [] } = useQuery({
    queryKey: ['global-draws'],
    queryFn: getGlobalDraws,
    refetchInterval: 60_000,
  })

  const { data: gsData } = useQuery({
    queryKey: ['global-gs-totals'],
    queryFn: getGlobalGSTotals,
  })

  const { data: allTournaments = [] } = useQuery({
    queryKey: ['tournaments'],
    queryFn: listTournaments,
    refetchInterval: 60_000,
  })

  const { data: drawCountsRaw = [] } = useQuery({
    queryKey: ['draw-counts'],
    queryFn: getDrawCounts,
    staleTime: 5 * 60_000,
  })
  const drawCountMap = useMemo(() => Object.fromEntries(drawCountsRaw.map(r => [r.user_id, r.draw_count])), [drawCountsRaw])

  const categoryGroups = useMemo(() => {
    const cohortInfo = computeCohortInfo(allTournaments)
    const groups = new Map()
    for (const lt of globalDraws) {
      const ds = getDisplayStatus(lt.tournament, cohortInfo)
      if (ds === 'upcoming') continue
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
  }, [globalDraws, allTournaments])

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
          <p className="muted">{gsData?.members?.length ?? '…'} member{gsData?.members?.length !== 1 ? 's' : ''}</p>
        </div>
      </div>

      <div className="league-body-row">
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
            <p className="muted">No picks have been submitted yet.</p>
          ) : !visibleGroup ? (
            <p className="muted">No draws for this status.</p>
          ) : (
            <div className="lt-category-group">
              {visibleGroup.items.map(({ tournament: t, picker_count }) => (
                <RoundProgressChart
                  key={t.id}
                  tournament={t}
                  pickerCount={picker_count}
                  leagueId={null}
                  leagueMemberCount={null}
                />
              ))}
            </div>
          )}
        </div>

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
              {(gsData?.members ?? []).map(m => (
                <tr key={m.user_id}>
                  <td className="lmt-name">
                    <a href={`/draw-history?user=${m.user_id}`} target="_blank" rel="noopener noreferrer" className="lmt-name-link username-hover" data-tooltip={`${m.full_name || m.username}: Show Draw History (${drawCountMap[m.user_id] ?? 0} draws competed)`}>
                      <span className="lmt-name-text">{m.username}</span>
                    </a>
                    {m.is_admin && <span className="lmt-admin-badge">Admin</span>}
                  </td>
                  <td className="lmt-pts">{m.atp_points}</td>
                  <td className="lmt-pts">{m.wta_points}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

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
