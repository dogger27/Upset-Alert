import { useState, useMemo, useRef, useEffect, useCallback } from 'react'
import { useParams, useNavigate, useOutletContext } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getLeague, getLeagueTournaments, getRoundScores, updateLeague, setMemberAdmin, removeMember, deleteLeague, shareLeagueByEmail, getGrandSlamTotals } from '../api/leagues'
import { getGlobalRoundScores, getGlobalDraws, getGlobalGSTotals, listTournaments } from '../api/tournaments'
import ComparePicksTable from '../components/ComparePicksTable'
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

  // The draw whose standings are open, or null. Held HERE rather than in the
  // card: the modal must not live inside the scrolling list it was opened
  // from, or it inherits that list's stacking and clipping.
  const [openDraw, setOpenDraw] = useState(null)

  const [statusFilter, setStatusFilter] = useState(null) // null = auto (first non-empty)
  const [showMembers, setShowMembers] = useState(false) // "All Members" view instead of draws
  const [memberSortCol, setMemberSortCol] = useState(null) // null | 'atp' | 'wta' | 'combined'
  const [memberSortDir, setMemberSortDir] = useState('desc')

  // Previous-tab lazy loading: only 5 draws render up front, more append as
  // the user scrolls near the bottom. Callback ref (not useEffect) so the
  // observer attaches the instant the sentinel div mounts, regardless of
  // whether previousVisibleCount itself changed.
  const [previousVisibleCount, setPreviousVisibleCount] = useState(5)
  const previousObserverRef = useRef(null)
  const previousLoadMoreRef = useCallback((node) => {
    previousObserverRef.current?.disconnect()
    if (!node) return
    previousObserverRef.current = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) setPreviousVisibleCount(c => c + 5)
    }, { rootMargin: '300px' })
    previousObserverRef.current.observe(node)
  }, [])

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

  // Group non-upcoming tournaments by display status: Open → Active → Previous.
  // On this page only, "Last Week" is folded into "Previous" (no separate tab),
  // so the merged Previous bucket is sorted most-recent-first to keep Last
  // Week's draws at the top of it. Open/Active sorts by tier instead — see the
  // comparator below.
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
      // Previous is a history list, so recency leads there and tier only breaks
      // ties between draws of the same week. Sorting tier-first put Wimbledon at
      // the head of a list whose 3rd entry (French Open, May 25) was two months
      // older than draws that had just finished, and since Previous reveals only
      // 5 at a time, everything after Wimbledon was hidden behind "Show more".
      // Open/Active keeps tier first: nothing is truncated there, so the biggest
      // live event leading is a help rather than a filter.
      const recencyFirst = g.key === 'previous'
      g.items.sort((a, b) => {
        const ad = a.tournament.start_date || ''
        const bd = b.tournament.start_date || ''
        const byTier = tierValue(b.tournament.category) - tierValue(a.tournament.category)
        const byDate = bd > ad ? 1 : bd < ad ? -1 : 0
        return recencyFirst ? (byDate || byTier) : (byTier || byDate)
      })
    }
    return [...groups.values()].sort((a, b) => a.order - b.order)
  }, [leagueTournaments, allTournaments, isGlobal])

  if (!isGlobal && leagueLoading) return <div className="page-loading">Loading…</div>
  if (!isGlobal && !league) return null

  // Owner, league-admin member, or site admin — mirrors the server's
  // _can_manage, which gates both update and delete.
  const canManageSettings = !isGlobal && (
    user?.id === league.owner.id
    || (league.members ?? []).some(m => m.id === user?.id && m.is_admin)
    || user?.is_admin)
  const memberCount = isGlobal ? (gsData?.members?.length ?? 0) : league.member_count

  return (
    <div className="league-detail">
      {showInvite && (
        <InviteModal league={league} onClose={() => setShowInvite(false)} />
      )}

      {editing && canManageSettings && (
        <LeagueSettings league={league} onDone={() => { setEditing(false); qc.invalidateQueries({ queryKey: ['league', id] }) }} />
      )}

      {(() => {
        // "Open" and "Active" share a single tab (their draws render in their
        // own stacked white boxes below, see .lt-status-sections) — only
        // "Previous" gets a distinct tab. Counts are only meaningful (and
        // shown) for Previous; Open/Active is a merged bucket so a single
        // number there wouldn't map to either sub-list cleanly.
        const STATUS_TABS = [
          { key: 'open_active', label: 'Open / Active', statuses: ['open', 'active'] },
          { key: 'previous', label: 'Prev.', statuses: ['previous'] },
        ]
        const countByTab = Object.fromEntries(STATUS_TABS.map(t => [t.key, 0]))
        for (const g of categoryGroups) {
          const tab = STATUS_TABS.find(t => t.statuses.includes(g.key))
          if (tab) countByTab[tab.key] += g.items.length
        }
        const firstNonEmptyTab = STATUS_TABS.find(t => countByTab[t.key] > 0)?.key ?? STATUS_TABS[0].key
        const activeTab = statusFilter ?? firstNonEmptyTab
        const activeStatuses = STATUS_TABS.find(t => t.key === activeTab)?.statuses ?? []
        const visibleGroups = activeStatuses.map(s => categoryGroups.find(g => g.key === s)).filter(Boolean)
        return (
          <>
            <div className="lt-controls-row">
              <button
                className={['lt-members-btn', showMembers && 'lt-members-btn--active'].filter(Boolean).join(' ')}
                onClick={() => setShowMembers(true)}
              >
                Members
              </button>
              {categoryGroups.length > 0 && (
                <div className="lt-status-tabs">
                  {STATUS_TABS.map(t => {
                    const count = countByTab[t.key]
                    const empty = count === 0
                    return (
                      <button
                        key={t.key}
                        className={['lt-status-tab', (!showMembers && activeTab === t.key) && 'lt-status-tab--active', empty && 'lt-status-tab--empty'].filter(Boolean).join(' ')}
                        disabled={empty}
                        onClick={() => { setShowMembers(false); setStatusFilter(t.key); if (t.key === 'previous') setPreviousVisibleCount(5) }}
                      >
                        {t.label}{t.key === 'previous' ? ` (${count})` : ''}
                      </button>
                    )
                  })}
                </div>
              )}
            </div>

            {showMembers ? (
              <div className="card league-tournaments-section lt-members-view">
                <h2 className="league-members-heading">Members ({memberCount})</h2>
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
                              <a href={`/draw-history?user=${m.user_id}`} className="lt-history-btn" title={`${m.username}'s Draw History`} aria-label={`${m.username}'s Draw History`}>
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                                  <circle cx="12" cy="7" r="4" />
                                </svg>
                              </a>
                              <span className="lmt-name-link">
                                <UserName className="lmt-name-text" user={{ username: m.username, full_name: (!isGlobal && league.show_real_name) ? m.full_name : null }} />
                              </span>
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
            ) : categoryGroups.length === 0 ? (
              <div className="card league-tournaments-section">
                <p className="muted">No picks have been submitted yet. Members can make picks from the Tournaments page.</p>
              </div>
            ) : visibleGroups.length === 0 ? (
              <div className="card league-tournaments-section">
                <p className="muted">No draws for this status.</p>
              </div>
            ) : (
              <div className="lt-status-sections">
                {visibleGroups.map(g => {
                  // "Previous" lazy-loads 5 at a time; Open/Active always render in full.
                  const isPrevious = g.key === 'previous'
                  const visibleItems = isPrevious ? g.items.slice(0, previousVisibleCount) : g.items
                  const hasMore = isPrevious && previousVisibleCount < g.items.length
                  return (
                    <div key={g.key}
                         className={`card league-tournaments-section${isPrevious ? '' : ' lt-section--cards'}`}>
                      {(() => {
                        // Same name with both M and F present (Grand Slams, or any
                        // other event running men's + women's draws simultaneously)
                        // → disambiguate with "Men"/"Women" after the name.
                        const gendersByName = new Map()
                        for (const { tournament: t } of visibleItems) {
                          if (!gendersByName.has(t.name)) gendersByName.set(t.name, new Set())
                          gendersByName.get(t.name).add(t.gender)
                        }
                        const open = ({ tournament: t, picker_count }) => () => setOpenDraw({
                          tournament: t,
                          pickerCount: picker_count,
                          showGenderLabel: gendersByName.get(t.name)?.size > 1,
                        })

                        /* TWO SHAPES, BECAUSE THE QUESTION CHANGES.
                           A live draw is asking "how am I doing" — one or two
                           of them, each worth a card with room for a standing
                           and a progress bar. A finished draw is asking "where
                           did I come" across 34 of them, and 34 cards is a
                           wall to scan: the eye has to re-find the rank in a
                           different place on every tile. Rows put every finish
                           in one column, which is what comparing them needs. */
                        if (isPrevious) {
                          return (
                            <div className="dt-wrap">
                              <table className="dt-table">
                                <thead>
                                  <tr>
                                    <th className="dt-h-draw">Draw</th>
                                    <th className="dt-h-dates">Dates</th>
                                    <th className="dt-h-surface">Surface</th>
                                    <th className="dt-h-num">Finish</th>
                                    <th className="dt-h-num" title="Correct picks">✓</th>
                                    <th className="dt-h-num">Score</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {visibleItems.map(item => (
                                    <DrawRow
                                      key={item.tournament.id}
                                      tournament={item.tournament}
                                      leagueId={isGlobal ? null : Number(id)}
                                      showGenderLabel={gendersByName.get(item.tournament.name)?.size > 1}
                                      onOpen={open(item)}
                                    />
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )
                        }
                        return (
                          <div className="lt-category-group">
                            {visibleItems.map(item => (
                              <DrawCard
                                key={item.tournament.id}
                                tournament={item.tournament}
                                pickerCount={item.picker_count}
                                leagueId={isGlobal ? null : Number(id)}
                                showGenderLabel={gendersByName.get(item.tournament.name)?.size > 1}
                                onOpen={open(item)}
                              />
                            ))}
                          </div>
                        )
                      })()}
                      {hasMore && (
                        <div ref={previousLoadMoreRef} className="lt-load-more-sentinel">
                          Loading more…
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </>
        )
      })()}

      {openDraw && (
        <DrawModal
          tournament={openDraw.tournament}
          pickerCount={openDraw.pickerCount}
          leagueId={isGlobal ? null : Number(id)}
          leagueMemberCount={isGlobal ? null : league?.member_count}
          showRealName={isGlobal ? false : league?.show_real_name}
          showGenderLabel={openDraw.showGenderLabel}
          onClose={() => setOpenDraw(null)}
        />
      )}
    </div>
  )
}

// R1=Red R2=Orange R3=Yellow R4=Green R5=Blue R6=Purple R7=Violet
// Resolved from the theme rather than held as literals: the bar fill reads the
// same on either background, but its label ink has to flip. See --round-* in
// index.css.
const ROUND_COLORS      = [1, 2, 3, 4, 5, 6, 7].map(i => `var(--round-${i})`)
const ROUND_DARK_COLORS = [1, 2, 3, 4, 5, 6, 7].map(i => `var(--round-${i}-ink)`)
function getRoundLabel(index, numRounds) {
  const fromEnd = numRounds - 1 - index
  if (fromEnd === 0) return 'F'
  if (fromEnd === 1) return 'SF'
  if (fromEnd === 2) return 'QF'
  return `R${index + 1}`
}

const ROW_SLOT = 41 // px per row slot (bar height 34px + gap 7px)

/* ONE DRAW AS A CARD, and the full standings behind it.

   The Leagues page used to stack a whole RoundProgressChart per draw. Every
   competitor of every draw was in the document at once, so the page grew with
   the field — 29 rows a draw today, and the whole point of the site is that
   the field keeps growing. Nothing was scrollable in its own right either: the
   scrubber for a draw sat wherever that draw's rows happened to end, so
   reaching it meant scrolling the page past everyone.

   A card is a fixed height whatever the field does. The standings open in a
   layer of their own, where the list scrolls and the scrubber stays put.

   Card and modal deliberately run the SAME query key as the chart, so opening
   one costs no request — React Query serves it from cache and both stay on the
   same 60s refetch. */
function DrawCard({ tournament: t, pickerCount, leagueId, showGenderLabel, onOpen }) {
  const { user } = useAuth()
  const { data } = useQuery({
    queryKey: leagueId != null ? ['round-scores', leagueId, t.id] : ['global-round-scores', t.id],
    queryFn: leagueId != null ? () => getRoundScores(leagueId, t.id) : () => getGlobalRoundScores(t.id),
    refetchInterval: 60_000,
  })

  const entries = data?.entries ?? []
  const timeline = data?.matches_timeline ?? []
  const numRounds = entries.length > 0
    ? entries[0].round_points.length
    : (t.num_rounds ?? ROUND_COLORS.length)

  /* WHERE THE VIEWER STANDS. Plain index+1, the same arithmetic the standings
     row uses — a card that ranked ties differently from the list it opens
     would read as one of the two being wrong. */
  const mine = user ? entries.findIndex(e => e.user_id === user.id) : -1
  /* HOW FAR THE DRAW HAS GOT. The timeline holds the matches that have been
     played AND scored, in order — it is what the scrubber scrubs — so its
     length is the numerator. The denominator is not on the payload, but it
     does not need to be: a single-elimination draw of N entrants plays exactly
     N-1 matches, and that stays right when there are byes (a 96-draw plays 95)
     because a bye is not a match. */
  const played = timeline.length
  const total = t.draw_size > 1 ? t.draw_size - 1 : played
  const last = played > 0 ? timeline[played - 1] : null
  const through = last ? getRoundLabel(last.round_number - 1, numRounds) : null
  const pct = total > 0 ? Math.min(100, (played / total) * 100) : 0

  return (
    <button type="button" className="dc-card" onClick={() => onOpen(t)}>
      <div className="dc-top">
        <span className={`lt-gender-badge lt-gender-badge--${t.gender === 'M' ? 'm' : 'f'}`}>
          {t.gender === 'M' ? 'ATP' : 'WTA'} {tierLabel(t.category)}
        </span>
        {(t.start_date || t.end_date) && (
          <span className="dc-dates">
            {fmtDrawDate(t.start_date)}{t.end_date ? ` – ${fmtDrawDate(t.end_date)}` : ''}
          </span>
        )}
        {t.surface && <span className="dc-surface">{t.surface}</span>}
      </div>

      <span className="dc-title">
        {t.name}{showGenderLabel ? ` ${t.gender === 'M' ? 'Men' : 'Women'}` : ''} {t.year}
      </span>

      {/* THE VIEWER'S OWN LINE FIRST, because it is the reason to open the
          card. Someone not in this draw gets the size of the field instead —
          a rank of nothing would be a lie, and an empty slot reads as broken. */}
      {t.status === 'open' ? (
        /* NOBODY HAS A RANK BEFORE PLAY. An open draw's entries are in no
           meaningful order — the chart draws them as a plain list for exactly
           that reason — so a position here would be an invented standing. Say
           what the draw is waiting for instead. */
        <div className="dc-rank dc-rank--out">
          <span className="dc-rank-of dc-rank-open">Predictions open</span>
        </div>
      ) : mine >= 0 ? (
        <div className="dc-rank">
          <span className="dc-rank-num">{mine + 1}</span>
          <span className="dc-rank-of">
            of {entries.length} · {entries[mine].total} pts
          </span>
        </div>
      ) : (
        <div className="dc-rank dc-rank--out">
          <span className="dc-rank-of">
            {entries.length > 0
              ? `${entries.length} competitor${entries.length !== 1 ? 's' : ''}`
              : (pickerCount ? `${pickerCount} picking` : 'No picks yet')}
          </span>
        </div>
      )}

      <div className="dc-bar" aria-hidden="true">
        <div className="dc-bar-fill" style={{ width: `${pct}%` }} />
      </div>

      <span className="dc-foot">
        {t.status === 'open'
          ? (entries.length > 0
              ? `${entries.length} entered`
              : (pickerCount ? `${pickerCount} picking` : 'No picks yet'))
          : total > 0
            ? `${played} / ${total} matches${through ? ` · through ${through}` : ''}`
            : 'Not started'}
      </span>
    </button>
  )
}

/* ONE FINISHED DRAW, AS A ROW.

   Same data and same query key as DrawCard — a completed draw just answers a
   different question, so it is written as a line to be compared with the lines
   above and below it rather than as a tile to be read on its own.

   No progress bar: every draw in this table played to a final, so a bar that is
   always full says nothing. The finish and the score are what differ. */
function DrawRow({ tournament: t, leagueId, showGenderLabel, onOpen }) {
  const { user } = useAuth()
  const { data } = useQuery({
    queryKey: leagueId != null ? ['round-scores', leagueId, t.id] : ['global-round-scores', t.id],
    queryFn: leagueId != null ? () => getRoundScores(leagueId, t.id) : () => getGlobalRoundScores(t.id),
    refetchInterval: 60_000,
  })

  const entries = data?.entries ?? []
  const mine = user ? entries.findIndex(e => e.user_id === user.id) : -1
  const me = mine >= 0 ? entries[mine] : null

  return (
    <tr className="dt-row" onClick={onOpen} tabIndex={0} role="button"
        onKeyDown={e => {
          // A row is not natively focusable or activatable; without this the
          // table is reachable by keyboard and then does nothing.
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen() }
        }}>
      <td className="dt-draw">
        <span className={`lt-gender-badge lt-gender-badge--${t.gender === 'M' ? 'm' : 'f'}`}>
          {t.gender === 'M' ? 'ATP' : 'WTA'} {tierLabel(t.category)}
        </span>
        <span className="dt-name">
          {t.name}{showGenderLabel ? ` ${t.gender === 'M' ? 'Men' : 'Women'}` : ''} {t.year}
        </span>
      </td>
      <td className="dt-dates">
        {(t.start_date || t.end_date)
          ? `${fmtDrawDate(t.start_date)}${t.end_date ? ` – ${fmtDrawDate(t.end_date)}` : ''}`
          : '–'}
      </td>
      <td className="dt-surface">{t.surface || '–'}</td>
      {me ? (
        <>
          {/* The finish reads as one fact, so the rank and the field size are
              one cell — splitting them into two columns invited the eye to
              compare 3 with 22 down the page, which means nothing. */}
          <td className="dt-num dt-finish">
            <span className="dt-finish-num">{mine + 1}</span>
            <span className="dt-finish-of">of {entries.length}</span>
          </td>
          <td className="dt-num dt-correct">{me.correct_count ?? 0}</td>
          <td className="dt-num dt-score">{me.total} pts</td>
        </>
      ) : (
        /* Not in this draw. One spanning cell rather than three dashes: three
           empty columns read as missing data, and this is not missing — the
           person simply did not enter. */
        <td className="dt-num dt-absent" colSpan={3}>
          {entries.length > 0 ? `${entries.length} competed` : 'No picks'}
        </td>
      )}
    </tr>
  )
}

/* THE STANDINGS, IN A LAYER OF THEIR OWN.

   The chart is rendered unchanged — this only gives it somewhere to live where
   the list can scroll without the page scrolling with it. Escape and the
   backdrop close it, and the body is frozen underneath: a wheel over a modal
   that scrolls the page behind it is how the layer stops feeling like a layer.
   Same conventions as InviteModal below. */
function DrawModal({ tournament, pickerCount, leagueId, leagueMemberCount,
                     showRealName, showGenderLabel, onClose }) {
  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [onClose])

  return (
    <div className="dm-backdrop" onClick={onClose} role="presentation">
      <div className="dm-panel" role="dialog" aria-modal="true"
           aria-label={`${tournament.name} standings`}
           onClick={e => e.stopPropagation()}>
        <button type="button" className="dm-close" onClick={onClose} aria-label="Close">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               strokeWidth="2" strokeLinecap="round">
            <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
        <div className="dm-body">
          <RoundProgressChart
            tournament={tournament}
            pickerCount={pickerCount}
            leagueId={leagueId}
            leagueMemberCount={leagueMemberCount}
            showRealName={showRealName}
            showGenderLabel={showGenderLabel}
          />
        </div>
      </div>
    </div>
  )
}

export function RoundProgressChart({ tournament: t, pickerCount, leagueId, leagueMemberCount, showRealName, showGenderLabel }) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [toast, setToast] = useState(null)
  const toastKey = useRef(0)
  // null = always follow the latest match (auto-max); number = user-set position
  const [scrubPos, setScrubPos] = useState(null)
  const [tab, setTab] = useState('standings')
  const [flashMatch, setFlashMatch] = useState(null)
  const flashKey = useRef(0)
  const flashTimer = useRef(null)

  const { data: rawData } = useQuery({
    queryKey: leagueId != null ? ['round-scores', leagueId, t.id] : ['global-round-scores', t.id],
    queryFn: leagueId != null ? () => getRoundScores(leagueId, t.id) : () => getGlobalRoundScores(t.id),
    refetchInterval: 60_000,
  })

  const entries = rawData?.entries ?? []
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
      return { entries, roundsWithMatches }
    }
    const slice = matchesTimeline.slice(0, effectiveScrubPos)
    const sliceRounds = [...new Set(slice.map(m => m.round_number))].sort((a, b) => a - b)
    const currentEntries = entries.map(e => {
      const preds = userPredictions[String(e.user_id)] ?? {}
      let total = 0
      // COUNTED HERE, not carried over from `e`. The spread below would keep
      // the server's finished-tournament correct_count on a row whose points
      // have been rewound to an earlier match, so a scrubbed board would have
      // shown "3 pts · 14 correct".
      let correct_count = 0
      const byRound = {}
      for (const m of slice) {
        if (String(preds[String(m.id)]) === String(m.winner_id)) {
          byRound[m.round_number] = (byRound[m.round_number] ?? 0) + m.points
          total += m.points
          correct_count += 1
        }
      }
      const round_points = Array.from({ length: e.round_points.length }, (_, i) => byRound[i + 1] ?? 0)
      return { ...e, round_points, total, correct_count }
    })
    currentEntries.sort((a, b) => {
      if (b.total !== a.total) return b.total - a.total
      for (let i = a.round_points.length - 1; i >= 0; i--) {
        const diff = (b.round_points[i] ?? 0) - (a.round_points[i] ?? 0)
        if (diff !== 0) return diff
      }
      return 0
    })
    return { entries: currentEntries, roundsWithMatches: sliceRounds }
  }, [isScrubbing, effectiveScrubPos, matchesTimeline, entries, roundsWithMatches, userPredictions])

  const dispEntries = displayData.entries
  const dispRoundsWithMatches = displayData.roundsWithMatches

  const numRounds = entries.length > 0 ? entries[0].round_points.length : (t.num_rounds ?? ROUND_COLORS.length)
  // Scale and column structure always reflect the full (server) state so bars grow as you scrub right
  const finalPlayed = roundsWithMatches.includes(numRounds)

  // Fixed name column width based on longest username — shared across all absolute-positioned rows.
  // When the top 3 get a place icon (🏆/🥈/🥉) it shares this same cell, so reserve extra room for
  // it too — otherwise a draw with only short usernames sizes the column just for the text, and the
  // icon on top of that pushes the name into ellipsis truncation.
  const nameColWidth = Math.max(70, ...entries.map(e => e.username.length * 8.5)) + 8 + (finalPlayed ? 24 : 0)
  const PLACE_ICONS = ['🏆', '🥈', '🥉']

  const activeRounds = roundsWithMatches.length > 0
    ? roundsWithMatches.map(r => r - 1)
    : Array.from({ length: numRounds }, (_, i) => i).filter(i => entries.some(e => e.round_points[i] > 0))
  const perRoundMax = activeRounds.map(i => {
    const vals = entries.map(e => e.round_points[i] ?? 0)
    return Math.max(...vals.map(v => v ?? 0), 1)
  })
  // Columns are sized proportionally to points scored (flex-grow), which
  // squashes a round where nobody scored down to a sliver next to a round
  // with real points. Give those all-zero columns a fixed minimum width
  // instead, just enough to fit the round label and the "0".
  const colFlex = activeRounds.map((i, col) => {
    const hasPoints = entries.some(e => (e.round_points[i] ?? 0) > 0)
    return hasPoints ? perRoundMax[col] : '0 0 42px'
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
      {/* THE IDENTITY AND THE TABS ARE ONE PIECE OF FURNITURE. Wrapped so the
          modal can pin them with a single sticky element: two adjacent sticky
          siblings would each need to know the other's height, and this header
          changes height when the title wraps. Outside the modal the wrapper is
          an ordinary block and changes nothing — both children were already
          block-level siblings in this order. */}
      <div className="lt-progress-top">
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

      {/* The identity line above never moves; these switch only the body. */}
      <div className="lt-tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === 'standings'}
          className={`lt-tab${tab === 'standings' ? ' lt-tab--active' : ''}`}
          onClick={() => setTab('standings')}>Standings</button>
        <button type="button" role="tab" aria-selected={tab === 'compare'}
          className={`lt-tab${tab === 'compare' ? ' lt-tab--active' : ''}`}
          onClick={() => setTab('compare')}>Compare Picks</button>
      </div>
      </div>

      {toast && <LgToast key={toast.key} message={toast.msg} onDone={() => setToast(null)} />}
      {tab === 'compare' ? (
        <ComparePicksTable drawId={t.id} leagueId={leagueId} />
      ) : entries.length === 0 ? (
        <p className="lt-progress-empty">No picks submitted yet.</p>
      ) : t.status === 'open' ? (
        <>
          <div className="lt-open-content">
            <div className="lt-open-notice">
              <p className="lt-open-notice-main">Match predictions are OPEN</p>
              {t.pick_lock_mode === 'r1_progressive' ? (
                <p className="lt-open-notice-lock">Locks <strong>when round one is complete</strong></p>
              ) : t.closing_time && (
                <p className="lt-open-notice-lock">Lock time: <strong>{fmtLockTime(t.closing_time)}</strong></p>
              )}
            </div>
            <div className="lt-competitors-label">User</div>
            <div className="lt-progress-rows">
              {entries.map((entry, entryIndex) => (
                <div key={entry.user_id} className={`lt-progress-row lt-progress-row--open${entry.user_id === user?.id ? ' lt-progress-row--me' : ''}`}>
                  <a href={`/draw-history?user=${entry.user_id}`} className="lt-history-btn" title={`${entry.username}'s Draw History`} aria-label={`${entry.username}'s Draw History`}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                      <circle cx="12" cy="7" r="4" />
                    </svg>
                  </a>
                  <span className="lt-pos-num">{entryIndex + 1}.</span>
                  <span className={`lt-progress-name${entry.user_id === user?.id ? ' lt-progress-name--me' : ''}`}>
                    <UserName className="lt-progress-name-text" user={{ username: entry.username, full_name: showRealName ? entry.full_name : null }} />
                  </span>
                </div>
              ))}
            </div>
          </div>
        </>
      ) : (
        <>
          <div className="lt-progress-row lt-progress-header-row" style={{ '--name-col-width': `${nameColWidth}px` }}>
            {/* Both buttons first, then the rank, then the name — the two
                controls belong together as one group of tools rather than
                being split by a number. These spacers only hold the columns
                open, but they have to be in the SAME order as the cells below
                or the header stops describing the row. */}
            <span className="lt-hcol-bracket" />
            <span className="lt-hcol-history" />
            <span className="lt-hcol-pos" />
            <span className="lt-competitors-label lt-competitors-label--inline">User</span>
            {/* THE TOTALS SIT BESIDE THE NAME, not past the bars. They are what
                the row is being read for, and the bar track is a 1fr column
                that grows with the panel — so parked on its far side they
                drifted further from the person they belong to the wider the
                window got. */}
            {/* Correct out of WHAT — the count means nothing without its
                denominator, and the denominator moves: it is the number of
                matches on the board right now, which the scrubber changes.
                effectiveScrubPos, not the timeline length, so the header
                agrees with the rows under it at every position. */}
            <span className="lt-progress-correct lt-progress-col-header"
                  title={`Correct picks, of ${effectiveScrubPos} match${effectiveScrubPos !== 1 ? 'es' : ''} counted`}>
              ✓ / {effectiveScrubPos}
            </span>
            <span className="lt-progress-total lt-progress-col-header">Score</span>
            <div className="lt-bar-track">
              {activeRounds.map((i, col) => (
                <div key={i} className="lt-bar-col lt-bar-col--label" style={{ flex: colFlex[col] }} title={roundWinnerLabels[col] ?? undefined}>
                  {getRoundLabel(i, numRounds)}
                </div>
              ))}
            </div>
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
                <button
                  className="lt-bracket-btn"
                  title={`View ${entry.username}'s bracket`}
                  onClick={e => {
                    e.stopPropagation()
                    navigate(`/tournaments/${t.id}?user=${entry.user_id}${leagueId != null ? `&league=${leagueId}` : ''}`)
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
                <a href={`/draw-history?user=${entry.user_id}`} className="lt-history-btn" title={`${entry.username}'s Draw History`} aria-label={`${entry.username}'s Draw History`} onClick={e => e.stopPropagation()}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                    <circle cx="12" cy="7" r="4" />
                  </svg>
                </a>
                <span className="lt-pos-num">{rank + 1}.</span>
                <span className={`lt-progress-name${entry.user_id === user?.id ? ' lt-progress-name--me' : ''}`}>
                  {finalPlayed && rank < 3 && <span className="lt-place-icon">{PLACE_ICONS[rank]}</span>}
                  <UserName className="lt-progress-name-text" user={{ username: entry.username, full_name: showRealName ? entry.full_name : null }} />
                </span>
                {/* Correct picks, beside the points they earned. The two are
                    not the same fact: a round is worth more than the one
                    before it, so 8 correct in R1 and 4 in the quarters can
                    reach the same score by different routes. */}
                <span className="lt-progress-correct"
                      title={`${entry.correct_count ?? 0} correct pick${(entry.correct_count ?? 0) !== 1 ? 's' : ''}`}>
                  {entry.correct_count ?? 0}
                </span>
                <span className="lt-progress-total">{entry.total} pts</span>
                <div className="lt-bar-track">
                  {activeRounds.map((i, col) => {
                    const pts = entry.round_points[i]
                    const fillPct = (pts / perRoundMax[col]) * 100
                    const isWinner = roundWinnerSets[col]?.has(entry.user_id) ?? false
                    return (
                      <div key={i} className="lt-bar-col" style={{ flex: colFlex[col] }} title={roundWinnerLabels[col] ?? undefined}>
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
                      <span className="lt-scrubber-when">
                        {new Date(flashMatch.completed_at).toLocaleString('en-US', { month: 'short', day: '2-digit', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })}
                      </span>
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
  const [showRealName, setShowRealName] = useState(league.show_real_name)
  const [allowMemberInvites, setAllowMemberInvites] = useState(league.allow_member_invites)
  const [error, setError] = useState('')
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [deleteConfirmText, setDeleteConfirmText] = useState('')

  const mutation = useMutation({
    mutationFn: (data) => updateLeague(league.id, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['league', String(league.id)] }); onDone() },
    onError: (e) => setError(e.response?.data?.detail || 'Failed'),
  })

  const adminMutation = useMutation({
    mutationFn: ({ userId, isAdmin }) => setMemberAdmin(league.id, userId, isAdmin),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['league', String(league.id)] }),
  })

  const removeMutation = useMutation({
    mutationFn: (userId) => removeMember(league.id, userId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['league', String(league.id)] }),
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteLeague(league.id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['leagues'] }); navigate('/') },
  })

  return (
    <div className="card settings-panel">
      <h3>League Settings</h3>
      <div className="form-row">
        <label>Name</label>
        <input value={name} onChange={e => setName(e.target.value)} />
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
        onClick={() => mutation.mutate({ name, show_real_name: showRealName, allow_member_invites: allowMemberInvites })}
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
                @<UserName user={{ username: m.username, full_name: league.show_real_name ? m.full_name : null }} />
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
