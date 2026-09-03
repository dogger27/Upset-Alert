import { useState, useMemo, useRef, useEffect } from 'react'
import { useParams, useNavigate, useOutletContext } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getLeague, getLeagueTournaments, getRoundScores, updateLeague, setMemberAdmin, removeMember, deleteLeague, shareLeagueByEmail, getGrandSlamTotals, getCashPools, setCashPool } from '../api/leagues'
import { getGlobalRoundScores, getGlobalDraws, getGlobalGSTotals, listTournaments } from '../api/tournaments'
import { PickChip, ROUND_SLOTS, ROUND_TITLES, DEPTH_ROUNDS } from '../components/ComparePicksTable'
import { getComparePicks } from '../api/tournaments'
import { useAuth } from '../store/auth'
import UserName from '../components/UserName'
import { computeCohortInfo, getDisplayStatus, DISPLAY_STATUS_LABELS } from '../utils/drawStatus.js'
import { rootFontPx, textWidth } from '../utils/text'
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
  // The draw(s) whose cash pool an admin is editing, or null.
  const [poolDraw, setPoolDraw] = useState(null)

  const [statusFilter, setStatusFilter] = useState(null) // null = auto (first non-empty)
  const [showMembers, setShowMembers] = useState(false) // "All Members" view instead of draws
  const [memberSortCol, setMemberSortCol] = useState(null) // null | 'atp' | 'wta' | 'combined'
  const [memberSortDir, setMemberSortDir] = useState('desc')

  // Previous-tab lazy loading: only 5 draws render up front, more append as
  // the user scrolls near the bottom. Callback ref (not useEffect) so the
  // observer attaches the instant the sentinel div mounts, regardless of
  // whether previousVisibleCount itself changed.
  const [previousVisibleCount, setPreviousVisibleCount] = useState(5)

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

  /* THE LEAGUE'S CASH POOLS, one per draw it has ever switched one on for.
     Fetched once for the page: every tile's switch reads from this map, and
     saving from the popup invalidates it. The global pseudo-league has none. */
  const { data: cashPoolList = [] } = useQuery({
    queryKey: ['cash-pools', id],
    queryFn: () => getCashPools(Number(id)),
    enabled: !isGlobal,
  })
  const cashPools = useMemo(() => {
    const m = new Map()
    for (const p of cashPoolList) m.set(p.draw_id, p)
    return m
  }, [cashPoolList])

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
                         className="card league-tournaments-section lt-section--fit">
                      {(() => {
                        // Same name with both M and F present (Grand Slams, or any
                        // other event running men's + women's draws simultaneously)
                        // → disambiguate with "Men"/"Women" after the name.
                        const gendersByName = new Map()
                        for (const { tournament: t } of visibleItems) {
                          if (!gendersByName.has(t.name)) gendersByName.set(t.name, new Set())
                          gendersByName.get(t.name).add(t.gender)
                        }
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
                                      onOpen={() => setOpenDraw({
                                        items: [item],
                                        showGenderLabel: gendersByName.get(item.tournament.name)?.size > 1,
                                      })}
                                    />
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )
                        }
                        /* ONE CARD PER EVENT. Two draws of the same
                           tournament are its men's and women's halves, not two
                           tournaments — grouped on the draws' shared
                           tournament_id where there is one, and on name+year
                           where there is not. Men first, so the pair always
                           opens on the same side and the card's two lines do
                           not swap order between events. */
                        const events = []
                        const byEvent = new Map()
                        for (const item of visibleItems) {
                          const t = item.tournament
                          const key = t.tournament_id ?? `${t.name}|${t.year}`
                          if (!byEvent.has(key)) {
                            const g = { key, items: [] }
                            byEvent.set(key, g)
                            events.push(g)
                          }
                          byEvent.get(key).items.push(item)
                        }
                        for (const g of events) {
                          g.items.sort((x, y) =>
                            (x.tournament.gender === 'M' ? 0 : 1) - (y.tournament.gender === 'M' ? 0 : 1))
                        }
                        return (
                          <div className="lt-category-group">
                            {events.map(g => (
                              <DrawCard
                                key={g.key}
                                items={g.items}
                                leagueId={isGlobal ? null : Number(id)}
                                showGenderLabel={gendersByName.get(g.items[0].tournament.name)?.size > 1}
                                cashPools={isGlobal ? null : cashPools}
                                canManagePool={canManageSettings}
                                onCashPool={items => setPoolDraw(items)}
                                onOpen={items => setOpenDraw({
                                  items,
                                  showGenderLabel: gendersByName.get(items[0].tournament.name)?.size > 1,
                                })}
                              />
                            ))}
                          </div>
                        )
                      })()}
                      {hasMore && (
                        /* A BUTTON, NOT A SENTINEL. This was an
                           IntersectionObserver watching a "Loading more…" div,
                           and an IntersectionObserver only fires when
                           intersection CHANGES — the sentinel came into view,
                           loaded five more, and then stayed in view, so it
                           never fired again. The list sat at ten rows under a
                           message promising more forever.
                           Clicking is also the honest interaction here: these
                           are finished draws being browsed, not a feed. */
                        <button type="button" className="lt-load-more"
                                onClick={() => setPreviousVisibleCount(c => c + 20)}>
                          Show more ({g.items.length - visibleItems.length} left)
                        </button>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </>
        )
      })()}

      {poolDraw && !isGlobal && (
        <CashPoolModal
          league={league}
          items={poolDraw}
          cashPools={cashPools}
          onClose={() => setPoolDraw(null)}
        />
      )}
      {openDraw && (
        <DrawModal
          items={openDraw.items}
          leagueId={isGlobal ? null : Number(id)}
          /* With a cash pool on, "entered" is measured against the people in
             it: the others are not in this draw as far as the league is
             concerned. A combined card reads the first tour's pool. */
          leagueMemberCount={isGlobal ? null : (() => {
            const p = cashPools.get(openDraw.items[0]?.tournament?.id)
            return p?.enabled ? p.paid_user_ids.length : league?.member_count
          })()}
          showRealName={isGlobal ? false : league?.show_real_name}
          showGenderLabel={openDraw.showGenderLabel}
          /* "Global" is the name of the all-users pseudo-league, and the one
             the page's own selector shows — so the title says the same thing
             the page does rather than going blank there. */
          leagueName={isGlobal ? 'Global' : league?.name}
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
/* TIED IS TIED, AND THE BOARD SHOULD SAY SO.
   The order already applies the league's tiebreak — total first, then round by
   round from the Final backwards, so a competitor who did better late outranks
   one who did better early. But the NUMBER beside each row was its position in
   that order, which turned three genuinely level competitors into a 1st, a 2nd
   and a 3rd on the strength of nothing at all. Once the tiebreak has run out
   of rounds to compare, there is no more evidence, and inventing an order is
   worse than admitting the tie.

   Standard competition ranking: 1, 1, 1, 4, 4, 6 — tied rows share the first
   position they occupy, and the next distinct row takes its own index back, so
   the numbers still say how many people are ahead of you. */
function sameStanding(a, b) {
  if (!a || !b || a.total !== b.total) return false
  const ra = a.round_points || [], rb = b.round_points || []
  if (ra.length !== rb.length) return false
  // Equality is order-independent, so this needs no Final-backwards walk —
  // it is only the SORT that cares which round is compared first.
  return ra.every((p, i) => (p ?? 0) === (rb[i] ?? 0))
}

/** The competition rank of the entry at `i` in an already-sorted list. */
function standingRankAt(entries, i) {
  let rank = 1
  for (let k = 1; k <= i; k++) {
    if (!sameStanding(entries[k - 1], entries[k])) rank = k + 1
  }
  return rank
}

/* WHAT ONE DRAW CONTRIBUTES TO ITS CARD. Its own query — the same key the
   modal uses, so opening the card costs no request — reduced to the two facts
   a card shows: where the viewer stands, and how far the draw has got. */
function useDrawStanding(t, leagueId, enabled = true) {
  const { user } = useAuth()
  const { data } = useQuery({
    queryKey: leagueId != null ? ['round-scores', leagueId, t?.id] : ['global-round-scores', t?.id],
    queryFn: leagueId != null ? () => getRoundScores(leagueId, t.id) : () => getGlobalRoundScores(t.id),
    refetchInterval: 60_000,
    enabled: enabled && !!t,
  })
  const entries = data?.entries ?? []
  const timeline = data?.matches_timeline ?? []
  const numRounds = entries.length > 0
    ? entries[0].round_points.length
    : (t?.num_rounds ?? ROUND_COLORS.length)
  /* Plain index+1, the same arithmetic the standings row uses — a card that
     ranked ties differently from the list it opens would read as one of the
     two being wrong. */
  const mine = user ? entries.findIndex(e => e.user_id === user.id) : -1
  const last = timeline.length > 0 ? timeline[timeline.length - 1] : null
  return {
    entries,
    mine,
    rank: mine >= 0 ? standingRankAt(entries, mine) : null,
    me: mine >= 0 ? entries[mine] : null,
    played: timeline.length,
    /* The denominator is not on the payload and does not need to be: a
       single-elimination draw of N entrants plays exactly N-1 matches, and
       that stays right with byes because a bye is not a match. */
    total: t && t.draw_size > 1 ? t.draw_size - 1 : timeline.length,
    through: last ? getRoundLabel(last.round_number - 1, numRounds) : null,
  }
}

/** One tour's line on a card: which tour, where you came, what you scored. */
function DcStanding({ t, stand, pickerCount }) {
  if (t.status === 'open') {
    return (
      <div className="dc-rank dc-rank--out">
        <span className="dc-rank-of dc-rank-open">Predictions open</span>
      </div>
    )
  }
  return (
    <div className={`dc-rank${stand.me ? '' : ' dc-rank--out'}`}>
      {stand.me ? (
        <>
          <span className="dc-rank-num">{stand.rank}</span>
          <span className="dc-rank-of">of {stand.entries.length} · {stand.me.total} pts</span>
        </>
      ) : (
        <span className="dc-rank-of">
          {stand.entries.length > 0
            ? `${stand.entries.length} competitor${stand.entries.length !== 1 ? 's' : ''}`
            : (pickerCount ? `${pickerCount} picking` : 'No picks yet')}
        </span>
      )}
    </div>
  )
}

/* ONE CARD PER EVENT, not per draw.

   A combined tournament runs a men's and a women's draw on the same courts in
   the same fortnight, and they were two cards saying the same dates, the same
   surface and the same name — the only difference being a word in the title
   and which half of the event you were looking at. That is one thing in the
   world, so it is one card, and the tour becomes something you switch between
   inside it rather than something you pick from the grid.

   Exactly two queries either way, both declared unconditionally: hook order
   cannot depend on how many draws an event happens to run. */
/* THE CASH POOL SWITCH, top-right of a draw tile. It states one fact — this
   league runs a pool on this draw — and, for whoever runs the league, opens
   the popup that sets it. It sits inside the tile's button, so it is a span
   with a role, and its own click never reaches the tile. Members who cannot
   manage the league see the state and nothing happens when they press it. */
function CashPoolSwitch({ on, manage, onOpen }) {
  const act = (e) => {
    e.preventDefault()
    e.stopPropagation()
    if (manage) onOpen()
  }
  return (
    <span
      className={`dc-pool${on ? ' dc-pool--on' : ''}${manage ? ' dc-pool--manage' : ' dc-pool--static'}`}
      role="switch"
      aria-checked={on}
      aria-label={on ? 'Cash pool on' : 'Cash pool off'}
      tabIndex={manage ? 0 : -1}
      onClick={act}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') act(e) }}
    >
      <span className="dc-pool-emoji" aria-hidden="true">💰</span>
      <span className="dc-pool-track"><span className="dc-pool-knob" /></span>
    </span>
  )
}

/* THE CASH POOL POPUP. Switch the pool on or off for the draw, and tick who
   has paid in. Everyone unticked is invisible in this draw for this league —
   the standings, the picks, the "who picked whom" panel — and only here.
   A combined card carries two draws, each with its own pool, so it gets the
   same tour switch the standings popup uses. */
function CashPoolModal({ league, items, cashPools, onClose }) {
  const qc = useQueryClient()
  const [which, setWhich] = useState(0)
  const t = items[which]?.tournament
  const saved = cashPools.get(t?.id)
  const [enabled, setEnabled] = useState(!!saved?.enabled)
  const [paid, setPaid] = useState(() => new Set(saved?.paid_user_ids ?? []))
  const [err, setErr] = useState(null)

  // Switching tour swaps the whole form for that draw's saved state.
  useEffect(() => {
    const s = cashPools.get(items[which]?.tournament?.id)
    setEnabled(!!s?.enabled)
    setPaid(new Set(s?.paid_user_ids ?? []))
    setErr(null)
  }, [which, items, cashPools])

  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const mutation = useMutation({
    mutationFn: () => setCashPool(league.id, t.id, { enabled, paid_user_ids: [...paid] }),
    onSuccess: () => {
      const id = String(league.id)
      qc.invalidateQueries({ queryKey: ['cash-pools', id] })
      qc.invalidateQueries({ queryKey: ['league-tournaments', id] })
      qc.invalidateQueries({ queryKey: ['round-scores', league.id] })
      qc.invalidateQueries({ queryKey: ['gs-totals', id] })
      onClose()
    },
    onError: (e) => setErr(e?.response?.data?.detail || 'Could not save the cash pool'),
  })

  const members = league.members ?? []
  const toggle = (uid) => setPaid(prev => {
    const next = new Set(prev)
    next.has(uid) ? next.delete(uid) : next.add(uid)
    return next
  })
  const all = () => setPaid(new Set(members.map(m => m.id)))
  const none = () => setPaid(new Set())

  return (
    <div className="dm-backdrop" onClick={onClose} role="presentation">
      <div className="dm-panel cp-panel" role="dialog" aria-modal="true" aria-label="Cash pool"
           onClick={e => e.stopPropagation()}>
        <button type="button" className="dm-close" onClick={onClose} aria-label="Close">×</button>
        <div className="dm-body">
          <h3 className="cp-title">
            <span aria-hidden="true">💰</span> Cash pool
            <span className="cp-title-sub">{league.name} · {t?.name} {t?.year}</span>
          </h3>
          {items.length > 1 && (
            <span className="lt-tour" role="group" aria-label="Tour">
              {items.map((it, i) => (
                <button key={it.tournament.id} type="button"
                        className={`lt-tour-btn lt-tour-btn--${it.tournament.gender === 'M' ? 'm' : 'f'}${which === i ? ' lt-tour-btn--on' : ''}`}
                        onClick={() => setWhich(i)}>
                  {it.tournament.gender === 'M' ? 'ATP' : 'WTA'}
                </button>
              ))}
            </span>
          )}
          <label className="cp-toggle-row">
            <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} />
            <span>Cash pool enabled for this draw</span>
          </label>
          <p className="cp-help">
            Tick everyone who has paid in. While the pool is on, only they appear in
            this league's standings and picks for this draw.
          </p>
          <div className="cp-list-head">
            <span>{paid.size} of {members.length} paid</span>
            <span className="cp-list-actions">
              <button type="button" className="cp-link" onClick={all}>All</button>
              <button type="button" className="cp-link" onClick={none}>None</button>
            </span>
          </div>
          <div className="cp-list">
            {members.map(m => (
              <label key={m.id} className="cp-row">
                <input type="checkbox" checked={paid.has(m.id)} onChange={() => toggle(m.id)} />
                <UserName className="cp-name" user={{ username: m.username, full_name: league.show_real_name ? m.full_name : null }} />
                {m.id === league.owner?.id && <span className="settings-member-badge owner">Owner</span>}
                {m.id !== league.owner?.id && m.is_admin && <span className="settings-member-badge admin">Admin</span>}
              </label>
            ))}
          </div>
          {err && <p className="cp-error">{err}</p>}
          <div className="cp-actions">
            <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
            <button type="button" className="btn-primary" disabled={mutation.isPending}
                    onClick={() => mutation.mutate()}>
              {mutation.isPending ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function DrawCard({ items, leagueId, showGenderLabel, onOpen,
                    cashPools = null, canManagePool = false, onCashPool }) {
  const a = items[0]?.tournament
  const b = items[1]?.tournament
  const paired = !!b
  // On if either tour of a combined card has a pool switched on.
  const poolOn = !!cashPools && items.some(it => cashPools.get(it.tournament.id)?.enabled)
  const sa = useDrawStanding(a, leagueId)
  const sb = useDrawStanding(b, leagueId, paired)

  const played = sa.played + (paired ? sb.played : 0)
  const total = sa.total + (paired ? sb.total : 0)
  const through = sa.through ?? (paired ? sb.through : null)
  const pct = total > 0 ? Math.min(100, (played / total) * 100) : 0
  const anyOpen = a?.status === 'open' && (!paired || b?.status === 'open')

  return (
    <button type="button"
            className={`dc-card dc-card--${paired ? 'both' : a.gender === 'M' ? 'atp' : 'wta'}${paired ? ' dc-card--pair' : ''}`}
            onClick={() => onOpen(items)}>
      {cashPools && (
        <CashPoolSwitch on={poolOn} manage={canManagePool}
                        onOpen={() => onCashPool?.(items)} />
      )}
      <div className="dc-top">
        {paired ? (
          /* Both tours named, then the tier once — it is the same tier for
             both halves, and repeating it would be the loudest thing on the
             card. */
          <span className="dc-badges">
            <span className="lt-gender-badge lt-gender-badge--m">ATP</span>
            <span className="lt-gender-badge lt-gender-badge--f">WTA</span>
            <span className="dc-tier">{tierLabel(a.category)}</span>
          </span>
        ) : (
          <span className={`lt-gender-badge lt-gender-badge--${a.gender === 'M' ? 'm' : 'f'}`}>
            {a.gender === 'M' ? 'ATP' : 'WTA'} {tierLabel(a.category)}
          </span>
        )}
      </div>

      {/* A LINE OF ITS OWN, so the dates start at the card's left edge instead
          of trailing whatever the badges happened to leave. Where they shared
          a row with the badges the line wrapped on a combined event and the
          dates ended up in the middle of nowhere; two rows put each thing
          where it can be found. */}
      <div className="dc-meta">
        {(a.start_date || a.end_date) && (
          <span className="dc-dates">
            {fmtDrawDate(a.start_date)}{a.end_date ? ` – ${fmtDrawDate(a.end_date)}` : ''}
          </span>
        )}
        {a.surface && <span className="dc-surface">{a.surface}</span>}
      </div>

      <span className="dc-title">
        {a.name}{!paired && showGenderLabel ? ` ${a.gender === 'M' ? 'Men' : 'Women'}` : ''} {a.year}
      </span>

      {/* NO STANDING ON A COMBINED CARD. Two of them ask the reader to hold
          two ranks in two draws before they have decided which one they came
          for — and whichever they pick, the modal says it again a moment
          later. The card's job here is to name the event and say how far it
          has got; the standing belongs to a tour, and the tour is chosen
          inside. */}
      {!paired && (
        <DcStanding t={a} stand={sa} pickerCount={items[0]?.picker_count} />
      )}

      <div className="dc-bar" aria-hidden="true">
        <div className="dc-bar-fill" style={{ width: `${pct}%` }} />
      </div>

      {/* The match count goes with the standing on a combined card. It reads
          as one draw's progress but is the sum of two, and a number that has
          to be explained is worse on a card than no number at all — the bar
          above already says how far through the fortnight the event is. */}
      {!paired && (
        <span className="dc-foot">
          {anyOpen
            ? (sa.entries.length > 0 ? `${sa.entries.length} entered` : 'No picks yet')
            : total > 0
              ? `${played} / ${total} matches${through ? ` · through ${through}` : ''}`
              : 'Not started'}
        </span>
      )}
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
  /* N-1 for a draw of N entrants, byes included — a bye is not a match. */
  const matchCount = t.draw_size > 1 ? t.draw_size - 1 : 0

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
            <span className="dt-finish-num">{standingRankAt(entries, mine)}</span>
            <span className="dt-finish-of">of {entries.length}</span>
          </td>
          {/* WITH ITS DENOMINATOR. Every row here is a different draw, so
              unlike the standings — where one header can say "of 17" for the
              whole column — the total belongs in the cell. A 250 and a slam
              are not comparable on correct picks alone. */}
          <td className="dt-num dt-correct">
            {me.correct_count ?? 0}<span className="dt-of"> / {matchCount}</span>
          </td>
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
function DrawModal({ items, leagueId, leagueMemberCount,
                     showRealName, showGenderLabel, leagueName, onClose }) {
  /* Which half of a combined event is showing. Index, not gender, so an event
     that somehow runs two draws of the same tour still works. */
  const [which, setWhich] = useState(0)
  const pair = items.length > 1
  const active = items[Math.min(which, items.length - 1)]
  const tournament = active.tournament
  const pickerCount = active.picker_count
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
            leagueName={leagueName}
            /* THE SURFACE GIVES UP ITS CORNER. It is the same surface for both
               halves of a combined event, and it is already on the card that
               opened this — where the switch is, there is something to decide;
               where the surface was, there was only something to read. */
            headerRight={pair ? (
              <span className="lt-tour" role="group" aria-label="Tour">
                {items.map((it, i) => (
                  <button key={it.tournament.id} type="button"
                          className={`lt-tour-btn lt-tour-btn--${it.tournament.gender === 'M' ? 'm' : 'f'}${which === i ? ' lt-tour-btn--on' : ''}`}
                          aria-pressed={which === i}
                          onClick={() => setWhich(i)}>
                    {it.tournament.gender === 'M' ? 'ATP' : 'WTA'}
                  </button>
                ))}
              </span>
            ) : null}
          />
        </div>
      </div>
    </div>
  )
}

export function RoundProgressChart({ tournament: t, pickerCount, leagueId, leagueMemberCount, showRealName, showGenderLabel, leagueName, headerRight }) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [toast, setToast] = useState(null)
  const toastKey = useRef(0)
  // null = always follow the latest match (auto-max); number = user-set position
  const [scrubPos, setScrubPos] = useState(null)
  const [tab, setTab] = useState('standings')
  /* COMPARE PICKS IS DESKTOP-ONLY. Its layout is a grid of one column per
     bracket slot — seven rounds of them — which needs width it will never have
     on a phone, and no amount of shrinking makes a 127-slot table legible
     there. The tab is hidden below 640px in CSS.
     This effect is the other half: hiding a control does not move someone who
     is already using it, so rotating a tablet or narrowing a desktop window
     would otherwise strand them in a view with no way out. */
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 640px)')
    const apply = () => { if (mq.matches) setTab(t => (t === 'compare' ? 'standings' : t)) }
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [])
  /* Which pick column the compare view is grouped by, or null for the
     standings order. Cleared whenever Standings is entered — that view is
     defined by total points, so it must never inherit an ordering chosen on
     the other tab. */
  const [cmpSort, setCmpSort] = useState(null)
  /* How deep the compare view reaches. 'finals' is the default because it is
     the whole back end of the draw in seven columns; 'quarters' trades that
     for the eight names a round earlier. */
  const [cmpDepth, setCmpDepth] = useState('finals')
  const [flashMatch, setFlashMatch] = useState(null)
  const flashKey = useRef(0)


  const { data: rawData } = useQuery({
    queryKey: leagueId != null ? ['round-scores', leagueId, t.id] : ['global-round-scores', t.id],
    queryFn: leagueId != null ? () => getRoundScores(leagueId, t.id) : () => getGlobalRoundScores(t.id),
    refetchInterval: 60_000,
  })

  /* THE PICKS, FOR THE SAME ROWS. Compare is no longer a separate table — it
     is this table with the bar track swapped out — so the picks have to arrive
     here and be joined to the standings entries by user id. Fetched only when
     the tab is showing, but the hook itself is unconditional: hooks run before
     any branch, always. */
  const { data: cmp } = useQuery({
    queryKey: ['compare-picks', t.id, leagueId ?? 'global'],
    queryFn: () => getComparePicks(t.id, leagueId),
    staleTime: 60_000,
    enabled: tab === 'compare',
  })
  const comparing = tab === 'compare'
  const allRounds = cmp?.rounds ?? []
  const hasQuarters = allRounds.includes('QF')
  /* The server sends every tier it has; the switch decides which are drawn.
     One fetch serves both settings, so flipping it costs nothing. */
  const cmpRounds = allRounds.filter(DEPTH_ROUNDS[cmpDepth] ?? (() => true))
  const cmpSlots = cmpRounds.map(r => Math.max(
    ROUND_SLOTS[r] ?? 1,
    ...(cmp?.users ?? []).map(u => (u.picks[r] ?? []).length),
  ))
  /* A slot the switch has moved away from cannot stay the sort key — it is no
     longer on screen to click off. */
  const activeSort = cmpSort && cmpRounds.includes(cmpSort.round) ? cmpSort : null
  const cmpTotalSlots = cmpSlots.reduce((a, b) => a + b, 0)
  const cmpByUser = Object.fromEntries((cmp?.users ?? []).map(u => [u.user_id, u.picks]))

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

  const pointsOrder = displayData.entries

  /* A PERSON'S RANK IS THEIR RANK, whatever the rows are sorted by.
     Stamped here, off the points order, so re-grouping the table by a pick
     re-orders the ROWS without renumbering the people in them — and so the
     number keeps saying where someone stands rather than where they happen to
     appear. It doubles as the points tiebreak below: equal by rank is equal by
     points, by construction. */
  const ranked = (() => {
    let rank = 1
    return pointsOrder.map((e, i) => {
      if (i > 0 && !sameStanding(pointsOrder[i - 1], e)) rank = i + 1
      return { ...e, standingsRank: rank }
    })
  })()

  /* GROUPED BY WHO AGREED, when a position header is clicked.
     Biggest group first, its members together, and inside a group the higher
     standing first. The group's SIZE leads because the question the header
     asks is "who did people put here", and the answer is a ranking of
     consensus — thirteen for Djokovic before six for Tiafoe. Names order
     groups that tie, so a redraw cannot shuffle two equal blocks past each
     other. Anyone with no pick in that slot sorts last: nothing to agree
     with. */
  const dispEntries = (() => {
    if (!comparing || !activeSort) return ranked
    const { round, slot } = activeSort
    const nameAt = e => cmpByUser[e.user_id]?.[round]?.[slot]?.name ?? null
    const counts = new Map()
    for (const e of ranked) {
      const n = nameAt(e)
      if (n) counts.set(n, (counts.get(n) ?? 0) + 1)
    }
    return [...ranked].sort((a, b) => {
      const na = nameAt(a), nb = nameAt(b)
      const ca = na ? counts.get(na) : -1
      const cb = nb ? counts.get(nb) : -1
      if (ca !== cb) return cb - ca
      if (na !== nb) return (na ?? '').localeCompare(nb ?? '')
      return a.standingsRank - b.standingsRank
    })
  })()
  const dispRoundsWithMatches = displayData.roundsWithMatches

  const numRounds = entries.length > 0 ? entries[0].round_points.length : (t.num_rounds ?? ROUND_COLORS.length)
  // Scale and column structure always reflect the full (server) state so bars grow as you scrub right
  const finalPlayed = roundsWithMatches.includes(numRounds)

  // Fixed name column width based on longest username — shared across all absolute-positioned rows.
  // When the top 3 get a place icon (🏆/🥈/🥉) it shares this same cell, so reserve extra room for
  // it too — otherwise a draw with only short usernames sizes the column just for the text, and the
  // icon on top of that pushes the name into ellipsis truncation.
  /* MEASURE THE NAMES, DO NOT COUNT THEIR LETTERS.
     8.5px a character is the same estimate the schedule's name fitter was
     built on and had to abandon: "iamjaycheung" and "WWWWWWWWWWWW" are the
     same length and nothing like the same width, so the column was sized for a
     string nobody had — too wide for this league, and one bad name away from
     being too narrow for another. A canvas measures the real strings in the
     real font with no layout and no reflow.
     0.85rem/600 is what .lt-progress-name draws in; the extras are what shares
     the cell with the text — the place medal on a finished draw, and a couple
     of pixels so the longest name does not finish flush against the next
     column. */
  const nameFontPx = rootFontPx() * 0.85
  const nameColWidth = Math.max(
    70,
    ...entries.map(e => textWidth(e.username, nameFontPx, 600)),
  ) + 6 + (finalPlayed ? 24 : 0)
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
          {/* The badge and the switch say the same thing, and the switch says
              it louder and lets you act on it. Only the single-draw header,
              which has no switch, still needs naming its tour. */}
          {!headerRight && (
            <span className={`lt-gender-badge lt-gender-badge--${t.gender === 'M' ? 'm' : 'f'}`}>
              {t.gender === 'M' ? 'ATP' : 'WTA'} {tierLabel(t.category)}
            </span>
          )}
          {(t.start_date || t.end_date) && (
            <span className="lt-progress-date">
              {fmtDrawDate(t.start_date)}{t.end_date ? ` – ${fmtDrawDate(t.end_date)}` : ''}
            </span>
          )}
        </div>
        {/* WHOSE TABLE, AND WHICH DRAW. The panel can be opened from any
            league and from Global, and the standings inside are scoped to that
            league — so the name it is scoped to belongs in the title rather
            than only in the page behind the layer.
            The gender word is tinted in the tour's own colour, the same pair
            the badge beside it uses, so a glance at the title says which half
            of a combined event this is. */}
        <span className="lt-progress-title">
          {leagueName && <span className="lt-title-league">{leagueName}</span>}
          {leagueName && <span className="lt-title-sep">: </span>}
          {t.name}
          {showGenderLabel && (
            <span className={`lt-title-gender lt-title-gender--${t.gender === 'M' ? 'm' : 'f'}`}>
              {' '}{t.gender === 'M' ? 'Men' : 'Women'}
            </span>
          )}
          {' '}{t.year}
        </span>
        {headerRight ?? (t.surface && <span className="lt-progress-meta">{t.surface}</span>)}
      </div>

      {/* The identity line above never moves; these switch only the body. */}
      <div className="lt-tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === 'standings'}
          className={`lt-tab${tab === 'standings' ? ' lt-tab--active' : ''}`}
          onClick={() => { setCmpSort(null); setTab('standings') }}>Standings</button>
        <button type="button" role="tab" aria-selected={tab === 'compare'}
          className={`lt-tab lt-tab--compare${tab === 'compare' ? ' lt-tab--active' : ''}`}
          onClick={() => setTab('compare')}>Compare Picks</button>

        {/* HOW FAR BACK TO LOOK. Only on the tab it governs, and pushed to the
            far end of the line so it reads as a setting for the view rather
            than as a third thing to open. Hidden when the draw has no
            quarter-final tier to offer — a switch with one working side is
            worse than no switch. */}
        {comparing && hasQuarters && (
          <div className="lt-depth" role="group" aria-label="Rounds shown">
            {['quarters', 'finals'].map(d => (
              <button key={d} type="button"
                      className={`lt-depth-btn${cmpDepth === d ? ' lt-depth-btn--on' : ''}`}
                      aria-pressed={cmpDepth === d}
                      onClick={() => setCmpDepth(d)}>
                {d === 'quarters' ? 'Quarters' : 'Finals'}
              </button>
            ))}
          </div>
        )}
      </div>
      </div>

      {toast && <LgToast key={toast.key} message={toast.msg} onDone={() => setToast(null)} />}
      {comparing && cmp?.hidden ? (
        <p className="lt-progress-empty">Picks are hidden until the draw locks.</p>
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
            {comparing ? (
              /* The same column, two lines: the round that owns a group, and
                 the bracket position of each slot inside it. Both are grids of
                 cmpTotalSlots equal columns, so they line up with each other
                 AND with every row below — one shared column count is what
                 keeps the header honest. */
              <div className="lt-picks-track lt-picks-track--head"
                   style={{ '--slots': cmpTotalSlots }}>
                <div className="lt-picks-rounds">
                  {cmpRounds.map((r, i) => (
                    /* The divider belongs on this line as well. Without it the
                       rule started below the round names, so the thing it was
                       separating was the only part of the column it did not
                       reach. */
                    <div key={r}
                         className="lt-picks-round lt-picks-group"
                         style={{ gridColumn: `span ${cmpSlots[i]}` }}>
                      {ROUND_TITLES[r] ?? r}
                    </div>
                  ))}
                </div>
                <div className="lt-picks-positions">
                  {cmpRounds.flatMap((r, i) =>
                    Array.from({ length: cmpSlots[i] }, (_, k) => {
                      const on = activeSort?.round === r && activeSort?.slot === k
                      return (
                        <button key={`${r}-${k}`} type="button"
                                className={`lt-picks-pos${k === 0 ? ' lt-picks-group' : ''}${on ? ' lt-picks-pos--on' : ''}`}
                                title={on
                                  ? 'Sorted by this pick — click to return to the standings order'
                                  : 'Sort by who picked here, most-agreed first'}
                                onClick={() => setCmpSort(on ? null : { round: r, slot: k })}>
                          {k + 1}
                        </button>
                      )
                    }))}
                </div>
              </div>
            ) : (
              <div className="lt-bar-track">
                {activeRounds.map((i, col) => (
                  <div key={i} className="lt-bar-col lt-bar-col--label" style={{ flex: colFlex[col] }} title={roundWinnerLabels[col] ?? undefined}>
                    {getRoundLabel(i, numRounds)}
                  </div>
                ))}
              </div>
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
                <span className="lt-pos-num">{entry.standingsRank ?? rank + 1}.</span>
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
                {comparing ? (
                  /* THE TRACK, WITH NAMES IN IT. Same cell, same column count
                     as the header above — an unfilled slot still renders, so a
                     part-finished bracket and a complete one keep their picks
                     under the same headings. */
                  <div className="lt-picks-track" style={{ '--slots': cmpTotalSlots }}>
                    {cmpRounds.flatMap((r, i) => {
                      const picks = cmpByUser[entry.user_id]?.[r] ?? []
                      return Array.from({ length: cmpSlots[i] }, (_, k) => (
                        <div key={`${r}-${k}`}
                             className={`lt-picks-cell${k === 0 ? ' lt-picks-group' : ''}`}>
                          {picks[k] ? <PickChip pk={picks[k]} /> : null}
                        </div>
                      ))
                    })}
                  </div>
                ) : (
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
                )}
              </div>
            ))}
          </div>
          {/* THE SCRUBBER BELONGS TO THE BARS. It rewinds a SCORE through the
              matches that produced it; a bracket of predicted names has no
              such history to walk, so on this tab there is nothing for it to
              do and it goes. */}
          {!comparing && effectiveMax > 0 && (
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
                    /* IT STAYS. This is the answer to "what happened at
                       this point", and it was deleting itself 2.5 seconds
                       after being asked — long enough to read the names, not
                       long enough to look from them to the score beside them
                       and back. The next drag replaces it; nothing else
                       needs to. */
                    flashKey.current += 1
                    setFlashMatch({ ...m, _key: flashKey.current })
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
                {/* ALWAYS RENDERED, empty or not. The scrubber is pinned to
                    the bottom of the panel, so anything that grows inside it
                    pushes the slider up — and a slider that moves when you let
                    go of it is a slider you have to re-find. The row holds its
                    two lines of space whether or not there is a match in it. */}
                <span key={flashMatch?._key ?? 'idle'} className="lt-scrubber-flash">
                  {flashMatch && <>
                    {getRoundLabel(flashMatch.round_number - 1, numRounds)}
                    {': '}
                    {flashMatch.winner_name ?? '?'} def. {flashMatch.loser_name ?? '?'}
                    {flashMatch.completed_at && (
                      <span className="lt-scrubber-when">
                        {new Date(flashMatch.completed_at).toLocaleString('en-US', { month: 'short', day: '2-digit', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })}
                      </span>
                    )}
                  </>}
                </span>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function InviteModal({ league, onClose }) {
  // null = idle, true = copied, false = the copy failed and the code is shown
  // instead. Three states, because "we tried" is not the same as "you have it".
  const [copied, setCopied] = useState(null)
  const [emailInput, setEmailInput] = useState('')
  const [sendResults, setSendResults] = useState(null)

  /* CLAIM SUCCESS ONLY ON SUCCESS.
     writeText returns a PROMISE and this had no .catch, while setCopied(true)
     ran unconditionally on the line after — so "✓ Copied!" appeared whether or
     not anything reached the clipboard. It rejects for real reasons: a
     non-secure context, a document that is not focused, Safari outside a user
     gesture, and every WebView that denies the permission. The user then pastes
     nothing into their invite email and has no idea why.
     On failure we say so and select the code, so it can still be copied by
     hand — a failed copy should cost a long-press, not the invite. */
  const codeRef = useRef(null)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(league.invite_code)
      setCopied(true)
    } catch {
      setCopied(false)
      // Select it so the manual path is one gesture, not a transcription.
      const el = codeRef.current
      if (el) {
        const r = document.createRange()
        r.selectNodeContents(el)
        const sel = window.getSelection()
        sel?.removeAllRanges()
        sel?.addRange(r)
      }
    }
    setTimeout(() => setCopied(null), 2500)
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
          {/* Referenced so a failed copy can select it — see copy() above. */}
          <div className="invite-code-value" ref={codeRef}>{league.invite_code}</div>
        </div>
        <button className="btn-primary invite-copy-btn" onClick={copy}>
          {copied === true ? '✓ Copied!'
            : copied === false ? 'Copy failed — select it above'
            : 'Copy Invite Code'}
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
