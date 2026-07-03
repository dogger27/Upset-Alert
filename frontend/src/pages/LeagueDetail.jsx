import { useState, useMemo, useRef, useEffect } from 'react'
import { useParams, useNavigate, useOutletContext } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getLeague, getLeagueTournaments, getRoundScores, updateLeague, setMemberAdmin, removeMember, deleteLeague, shareLeagueByEmail, getGrandSlamTotals } from '../api/leagues'
import { getGlobalRoundScores, getGlobalDraws, getGlobalGSTotals, listTournaments } from '../api/tournaments'
import { getDrawCounts } from '../api/auth'
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
  // The "Global" pseudo-league is the index route (/leagues, no :id param) —
  // same page, same code, just backed by the global (all-users) endpoints
  // instead of a real league. See feedback_global_league_duplication memory.
  const isGlobal = id === undefined
  const { user } = useAuth()
  const navigate = useNavigate()
  const qc = useQueryClient()
  // Settings/Invite buttons live in the parent Leagues.jsx top bar now (next to
  // the league selector arrow); this page just owns the modals they open.
  const { editing, setEditing, showInvite, setShowInvite } = useOutletContext()

  const [statusFilter, setStatusFilter] = useState(null) // null = auto (first non-empty)
  const [memberSortCol, setMemberSortCol] = useState(null) // null | 'atp' | 'wta' | 'combined'
  const [memberSortDir, setMemberSortDir] = useState('desc')

  const { data: league, isLoading: leagueLoading } = useQuery({
    queryKey: ['league', id],
    queryFn: () => getLeague(Number(id)),
    enabled: !isGlobal,
  })

  const { data: leagueTournaments = [] } = useQuery({
    queryKey: isGlobal ? ['global-draws'] : ['league-tournaments', id],
    queryFn: () => isGlobal ? getGlobalDraws() : getLeagueTournaments(Number(id)),
    refetchInterval: 60_000,
  })

  const { data: gsData } = useQuery({
    queryKey: isGlobal ? ['global-gs-totals'] : ['gs-totals', id],
    queryFn: () => isGlobal ? getGlobalGSTotals() : getGrandSlamTotals(Number(id)),
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

  // Group non-upcoming tournaments by display status: Open → Active → Previous.
  // On this page only, "Last Week" is folded into "Previous" (no separate tab) —
  // Within each group sort by tier desc, then start_date desc, so the merged
  // Previous bucket still shows Last Week's more recent draws first.
  const STATUS_ORDER = { open: 0, active: 1, previous: 2 }
  const categoryGroups = useMemo(() => {
    const cohortInfo = computeCohortInfo(allTournaments)
    const groups = new Map()
    for (const lt of leagueTournaments) {
      const rawDs = getDisplayStatus(lt.tournament, cohortInfo)
      const ds = rawDs === 'lastweek' ? 'previous' : rawDs
      if (ds === 'upcoming') continue
      // Global shows solo-picker draws too; real leagues hide them (not
      // meaningful competition when only one member has picked).
      if (!isGlobal && lt.picker_count <= 1) continue
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
  }, [leagueTournaments, allTournaments, isGlobal])

  if (!isGlobal && leagueLoading) return <div className="page-loading">Loading…</div>
  if (!isGlobal && !league) return null

  // Site admins can manage any league's settings, not just the ones they own.
  const canManageSettings = !isGlobal && (user?.id === league.owner.id || user?.is_admin)
  const memberCount = isGlobal ? (gsData?.members?.length ?? 0) : league.member_count

  return (
    <div className="league-detail">
      {showInvite && (
        <InviteModal league={league} onClose={() => setShowInvite(false)} />
      )}

      {editing && canManageSettings && (
        <LeagueSettings league={league} onDone={() => { setEditing(false); qc.invalidateQueries(['league', id]) }} />
      )}

      <div className="league-body-row">
        {/* Draws */}
        <div className="card league-tournaments-section">
          {(() => {
            const STATUS_TABS = ['open', 'active', 'previous']
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
                    {(() => {
                      // Same name with both M and F present (Grand Slams, or any
                      // other event running men's + women's draws simultaneously)
                      // → disambiguate with "Men"/"Women" after the name.
                      const gendersByName = new Map()
                      for (const { tournament: t } of visibleGroup.items) {
                        if (!gendersByName.has(t.name)) gendersByName.set(t.name, new Set())
                        gendersByName.get(t.name).add(t.gender)
                      }
                      return visibleGroup.items.map(({ tournament: t, picker_count }) => (
                        <RoundProgressChart
                          key={t.id}
                          tournament={t}
                          pickerCount={picker_count}
                          leagueId={isGlobal ? null : Number(id)}
                          leagueMemberCount={isGlobal ? null : league.member_count}
                          showRealName={isGlobal ? false : league.show_real_name}
                          showGenderLabel={gendersByName.get(t.name)?.size > 1}
                        />
                      ))
                    })()}
                  </div>
                )}
              </>
            )
          })()}
        </div>

        {/* Members sidebar */}
        <div className="card league-members-section">
          <h2>Members ({memberCount})</h2>
          <p className="league-members-subtitle">{gsData?.year ?? new Date().getFullYear()} Grand Slam Point Tally</p>
          {(() => {
            const rawMembers = gsData?.members ?? (isGlobal ? [] : league.members.map(m => ({ user_id: m.id, username: m.username, full_name: m.full_name, atp_points: null, wta_points: null })))
            const withCombined = rawMembers.map(m => ({
              ...m,
              combined_points: (m.atp_points != null && m.wta_points != null) ? m.atp_points + m.wta_points : null,
            }))
            const sortKey = { atp: 'atp_points', wta: 'wta_points', combined: 'combined_points' }[memberSortCol]
            const members = sortKey
              ? [...withCombined].sort((a, b) => {
                  const av = a[sortKey] ?? -Infinity
                  const bv = b[sortKey] ?? -Infinity
                  return memberSortDir === 'desc' ? bv - av : av - bv
                })
              : withCombined

            function handleSort(col) {
              if (memberSortCol === col) {
                setMemberSortDir(d => d === 'desc' ? 'asc' : 'desc')
              } else {
                setMemberSortCol(col)
                setMemberSortDir('desc')
              }
            }

            function SortHeader({ col, label }) {
              const active = memberSortCol === col
              return (
                <th className="lmt-pts lmt-pts--sortable" onClick={() => handleSort(col)}>
                  {label}{active && <span className="lmt-sort-arrow">{memberSortDir === 'desc' ? ' ▼' : ' ▲'}</span>}
                </th>
              )
            }

            return (
              <table className="league-members-table">
                <thead>
                  <tr>
                    <th className="lmt-name-th" />
                    <SortHeader col="atp" label="ATP" />
                    <SortHeader col="wta" label="WTA" />
                    <SortHeader col="combined" label="Comb." />
                  </tr>
                </thead>
                <tbody>
                  {members.map(m => (
                    <tr key={m.user_id}>
                      <td className="lmt-name">
                        <a href={`/draw-history?user=${m.user_id}`} className="lmt-name-link username-hover" data-tooltip={`${m.full_name || m.username}:\nDraw History (${drawCountMap[m.user_id] ?? 0})`}>
                          <span className="lmt-name-text">{m.username}</span>
                        </a>
                        {m.is_admin && <span className="lmt-admin-badge" title="Admin">A</span>}
                      </td>
                      <td className="lmt-pts">{m.atp_points ?? '–'}</td>
                      <td className="lmt-pts">{m.wta_points ?? '–'}</td>
                      <td className="lmt-pts">{m.combined_points ?? '–'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          })()}
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

const ROW_SLOT = 41 // px per row slot (bar height 34px + gap 7px)

export function RoundProgressChart({ tournament: t, pickerCount, leagueId, leagueMemberCount, showRealName, showGenderLabel }) {
  const { user } = useAuth()
  const [toast, setToast] = useState(null)
  const toastKey = useRef(0)
  // null = always follow the latest match (auto-max); number = user-set position
  const [scrubPos, setScrubPos] = useState(null)
  const [flashMatch, setFlashMatch] = useState(null)
  const flashKey = useRef(0)
  const flashTimer = useRef(null)

  const { data: drawCountsRaw = [] } = useQuery({
    queryKey: ['draw-counts'],
    queryFn: getDrawCounts,
    staleTime: 5 * 60_000,
  })
  const drawCountMap = useMemo(() => Object.fromEntries(drawCountsRaw.map(r => [r.user_id, r.draw_count])), [drawCountsRaw])
  const { data: rawData } = useQuery({
    queryKey: leagueId != null ? ['round-scores', leagueId, t.id] : ['global-round-scores', t.id],
    queryFn: leagueId != null ? () => getRoundScores(leagueId, t.id) : () => getGlobalRoundScores(t.id),
    refetchInterval: 60_000,
  })

  const entries = rawData?.entries ?? []
  const completedMatchesCount = rawData?.completed_matches_count ?? 0
  const roundsWithMatches = rawData?.rounds_with_matches ?? []
  const completedRoundNumsFromServer = rawData?.completed_round_nums ?? null
  const matchesTimeline = rawData?.matches_timeline ?? []
  const userPredictions = rawData?.user_predictions ?? {}

  const effectiveMax = matchesTimeline.length
  const effectiveScrubPos = scrubPos ?? effectiveMax
  const isScrubbing = effectiveScrubPos < effectiveMax

  // Recompute entries/rounds at the current scrub position
  const displayData = useMemo(() => {
    if (!isScrubbing || matchesTimeline.length === 0) {
      return { entries, roundsWithMatches, completedMatchesCount }
    }
    const slice = matchesTimeline.slice(0, effectiveScrubPos)
    const sliceRounds = [...new Set(slice.map(m => m.round_number))].sort((a, b) => a - b)
    const currentEntries = entries.map(e => {
      const preds = userPredictions[String(e.user_id)] ?? {}
      let total = 0
      const byRound = {}
      let correct = 0
      for (const m of slice) {
        if (String(preds[String(m.id)]) === String(m.winner_id)) {
          byRound[m.round_number] = (byRound[m.round_number] ?? 0) + m.points
          total += m.points
          correct++
        }
      }
      const round_points = Array.from({ length: e.round_points.length }, (_, i) => byRound[i + 1] ?? 0)
      return { ...e, round_points, total, correct_count: correct }
    })
    currentEntries.sort((a, b) => {
      if (b.total !== a.total) return b.total - a.total
      for (let i = a.round_points.length - 1; i >= 0; i--) {
        const diff = (b.round_points[i] ?? 0) - (a.round_points[i] ?? 0)
        if (diff !== 0) return diff
      }
      return 0
    })
    return { entries: currentEntries, roundsWithMatches: sliceRounds, completedMatchesCount: slice.length }
  }, [isScrubbing, effectiveScrubPos, matchesTimeline, entries, roundsWithMatches, completedMatchesCount, userPredictions])

  const dispEntries = displayData.entries
  const dispRoundsWithMatches = displayData.roundsWithMatches
  const dispCompletedCount = displayData.completedMatchesCount

  // Fixed name column width based on longest username — shared across all absolute-positioned rows
  const nameColWidth = Math.max(70, ...entries.map(e => e.username.length * 8.5)) + 8

  const numRounds = entries.length > 0 ? entries[0].round_points.length : (t.num_rounds ?? ROUND_COLORS.length)
  // Scale and column structure always reflect the full (server) state so bars grow as you scrub right
  const finalPlayed = roundsWithMatches.includes(numRounds)
  const PLACE_ICONS = ['🏆', '🥈', '🥉']

  const activeRounds = roundsWithMatches.length > 0
    ? roundsWithMatches.map(r => r - 1)
    : Array.from({ length: numRounds }, (_, i) => i).filter(i => entries.some(e => e.round_points[i] > 0))
  const perRoundMax = activeRounds.map(i => {
    const vals = entries.map(e => e.round_points[i] ?? 0)
    return Math.max(...vals.map(v => v ?? 0), 1)
  })

  // Prefer the server's authoritative "every non-bye match in this round is done"
  // list; fall back to the old "not the latest round" heuristic if it's missing
  // (e.g. briefly during a frontend/backend deploy gap).
  const completedRoundNums = new Set(
    completedRoundNumsFromServer ?? roundsWithMatches.filter((r, i) => i < roundsWithMatches.length - 1 || finalPlayed)
  )
  const roundWinnerSets = activeRounds.map((roundIdx) => {
    if (!completedRoundNums.has(roundIdx + 1)) return null
    const maxPts = Math.max(...dispEntries.map(e => e.round_points[roundIdx] ?? 0))
    if (maxPts <= 0) return null
    return new Set(dispEntries.filter(e => (e.round_points[roundIdx] ?? 0) === maxPts).map(e => e.user_id))
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

  const lastMatch = effectiveScrubPos > 0 ? matchesTimeline[effectiveScrubPos - 1] : null
  const scrubLabel = effectiveScrubPos === 0
    ? 'Before first match'
    : effectiveScrubPos >= effectiveMax
    ? `All ${effectiveMax} match${effectiveMax !== 1 ? 'es' : ''}`
    : `${effectiveScrubPos} / ${effectiveMax} matches (through ${lastMatch ? getRoundLabel(lastMatch.round_number - 1, numRounds) : ''})`

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
        <span className="lt-progress-title">{t.name}{showGenderLabel ? ` ${t.gender === 'M' ? 'Men' : 'Women'}` : ''} {t.year}</span>
        {t.surface && <span className="lt-progress-meta">{t.surface}</span>}
      </div>

      {toast && <LgToast key={toast.key} message={toast.msg} onDone={() => setToast(null)} />}
      {entries.length === 0 ? (
        <p className="lt-progress-empty">No picks submitted yet.</p>
      ) : t.status === 'open' ? (
        <>
          <div className="lt-competitors-label">Competitors</div>
          <div className="lt-open-content">
            <div className="lt-progress-rows">
              {entries.map((entry, entryIndex) => (
                <div key={entry.user_id} className={`lt-progress-row lt-progress-row--open${entry.user_id === user?.id ? ' lt-progress-row--me' : ''}`}>
                  <span className="lt-pos-num">{entryIndex + 1}.</span>
                  <a href={`/draw-history?user=${entry.user_id}`} className={`lt-progress-name lt-progress-name--link username-hover${entry.user_id === user?.id ? ' lt-progress-name--me' : ''}`} data-tooltip={`${entry.full_name || entry.username}:\nDraw History (${drawCountMap[entry.user_id] ?? 0})`}>
                    <span className="lt-progress-name-text">{entry.username}</span>
                  </a>
                </div>
              ))}
            </div>
            <div className="lt-open-notice">
              <p className="lt-open-notice-main">Match Predictions are In Progress.</p>
              {t.closing_time && (
                <p className="lt-open-notice-lock">Prediction Lock time: <strong>{fmtLockTime(t.closing_time)}</strong></p>
              )}
            </div>
          </div>
        </>
      ) : (
        <>
          <div className="lt-competitors-label">Competitors</div>
          <div className="lt-progress-row lt-progress-header-row" style={{ '--name-col-width': `${nameColWidth}px` }}>
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
          <div
            className="lt-progress-rows lt-progress-rows--race"
            style={{ height: `${Math.max(dispEntries.length * ROW_SLOT - 7, 0)}px`, '--name-col-width': `${nameColWidth}px` }}
          >
            {dispEntries.map((entry, rank) => (
              <div
                key={entry.user_id}
                className={`lt-progress-row lt-progress-row--abs${entry.user_id === user?.id ? ' lt-progress-row--me' : ''}`}
                style={{ transform: `translateY(${rank * ROW_SLOT}px)` }}
              >
                <span className="lt-pos-num">{rank + 1}.</span>
                <a href={`/draw-history?user=${entry.user_id}`} className={`lt-progress-name lt-progress-name--link username-hover${entry.user_id === user?.id ? ' lt-progress-name--me' : ''}`} data-tooltip={`${entry.full_name || entry.username}:\nDraw History (${drawCountMap[entry.user_id] ?? 0})`}>
                  {finalPlayed && rank < 3 && <span className="lt-place-icon">{PLACE_ICONS[rank]}</span>}
                  <span className="lt-progress-name-text">{entry.username}</span>
                </a>
                <button
                  className="lt-bracket-btn"
                  title={`View ${entry.username}'s bracket`}
                  onClick={e => {
                    e.stopPropagation()
                    window.open(`/tournaments/${t.id}?user=${entry.user_id}${leagueId != null ? `&league=${leagueId}` : ''}`, '_blank')
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
                    {entry.correct_count}/{dispCompletedCount}
                  </span>
                )}
              </div>
            ))}
          </div>
          {effectiveMax > 0 && (
            <div className="lt-scrubber">
              <input
                type="range"
                min={0}
                max={effectiveMax}
                value={effectiveScrubPos}
                onChange={e => {
                  const v = Number(e.target.value)
                  setScrubPos(v >= effectiveMax ? null : v)
                  const m = matchesTimeline[Math.min(v, effectiveMax) - 1]
                  if (m) {
                    if (flashTimer.current) clearTimeout(flashTimer.current)
                    flashKey.current += 1
                    setFlashMatch({ ...m, _key: flashKey.current })
                    flashTimer.current = setTimeout(() => setFlashMatch(null), 2500)
                  } else {
                    setFlashMatch(null)
                  }
                }}
                className="lt-scrubber-range"
                style={{ '--fill-pct': `${(effectiveScrubPos / effectiveMax) * 100}%` }}
              />
              <div className="lt-scrubber-bottom">
                <span className={`lt-scrubber-label${isScrubbing ? ' lt-scrubber-label--active' : ''}`}>
                  {scrubLabel}
                </span>
                {flashMatch && (
                  <span key={flashMatch._key} className="lt-scrubber-flash">
                    {getRoundLabel(flashMatch.round_number - 1, numRounds)}
                    {': '}
                    {flashMatch.winner_name ?? '?'} def. {flashMatch.loser_name ?? '?'}
                    {flashMatch.completed_at && (
                      <>, {new Date(flashMatch.completed_at).toLocaleString('en-US', { month: 'short', day: '2-digit', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })}</>
                    )}
                  </span>
                )}
              </div>
            </div>
          )}
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
