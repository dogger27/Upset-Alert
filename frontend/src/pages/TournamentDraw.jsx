/**
 * TournamentDraw — shows the bracket for one tournament.
 * Logged-in users can make / update predictions until the lock time.
 */
import { useState, useEffect, useLayoutEffect, useRef, useCallback } from 'react'
import { useParams, Link, useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { getDraw, refreshDraw, toggleUnlockSelections } from '../api/tournaments'
import { getPredictions, savePredictions } from '../api/predictions'
import { useAuth } from '../store/auth'
import BracketView from '../components/BracketView'
import CombinedView from '../components/CombinedView'
import DrawSidebar from '../components/DrawSidebar'
import './TournamentDraw.css'

export default function TournamentDraw() {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const { user } = useAuth()
  const qc = useQueryClient()

  // All state declared first
  const [picks, setPicks] = useState({})
  const [otherPicks, setOtherPicks] = useState({})
  // 'combined' (labelled "Picks" in the switcher) is the default; 'live'
  // shows BracketView with actual results only, no predictions. The old
  // dedicated picks-only BracketView mode ('picks') and the auto-switch
  // effects that used to flip into/out of it are left disabled below.
  const [viewMode, setViewMode] = useState('combined')
  const [windowStart, setWindowStart] = useState(0) // left-most visible round (pager)
  const [mainWidth, setMainWidth] = useState(0) // width of the bracket area (drives # rounds shown)
  const [bodyWidth, setBodyWidth] = useState(0) // width of the whole draw body (stable, drives sidebar auto-hide)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [sidebarManual, setSidebarManual] = useState(false) // user overrode auto-hide?
  const expandedSidebarW = useRef(290) // cached expanded sidebar width (updated while expanded)

  // Callback refs + ResizeObservers on .draw-main / .draw-body. (Callback refs
  // rather than useEffect so they attach once the elements mount after the
  // loading guard.)
  const makeWidthRef = (setter) => {
    let ro = null
    return node => {
      if (ro) { ro.disconnect(); ro = null }
      if (node) {
        const measure = () => setter(node.clientWidth)
        measure()
        ro = new ResizeObserver(measure)
        ro.observe(node)
      }
    }
  }
  const mainRef = useCallback(makeWidthRef(setMainWidth), [])
  const bodyWidthRef = useCallback(makeWidthRef(setBodyWidth), [])
  // Round-nav buttons' own rendered width, for the compact-mode zoom-fit
  // calc below (so the draw content's zoom targets the button's ACTUAL size
  // rather than a guessed constant). Left and right buttons share the same
  // CSS sizing, so either one updates this — two independent observers
  // (not one shared closure) so whichever button happens to be mounted
  // (paging can hide either one) keeps it current.
  const [navBtnW, setNavBtnW] = useState(26) // seed with a reasonable guess pre-measurement
  const navBtnLeftRef = useCallback(makeWidthRef(setNavBtnW), [])
  const navBtnRightRef = useCallback(makeWidthRef(setNavBtnW), [])
  // Also capture the .draw-body node so we can measure the drawn bracket's
  // right edge (for positioning the right-hand round-nav button).
  const bodyNodeRef = useRef(null)
  const bodyRef = useCallback((node) => { bodyNodeRef.current = node; bodyWidthRef(node) }, [bodyWidthRef])
  const [viewedUserId, setViewedUserId] = useState(() => { const u = searchParams.get('user'); return u ? Number(u) : null })
  const [viewedUserName, setViewedUserName] = useState(null)
  const initialModeSet = useRef(false)
  const [celebrating, setCelebrating] = useState(false)
  const [showUnlockConfirm, setShowUnlockConfirm] = useState(false)
  const [pendingAutoPicks, setPendingAutoPicks] = useState(null)
  const [showClearConfirm, setShowClearConfirm] = useState(false)
  const [clearToast, setClearToast] = useState(null)
  const [showDefaultPicksBanner, setShowDefaultPicksBanner] = useState(false)
  const clearToastKeyRef = useRef(0)
  const celebrateTimerRef = useRef(null)
  const clearToastTimerRef = useRef(null)
  const autoInitShownRef = useRef(false)

  const { data, isLoading, error } = useQuery({
    queryKey: ['draw', id],
    queryFn: () => getDraw(Number(id)),
    // Poll every 2 min for active tournaments (live scores) and any unlocked tournament
    // so non-admins see the unlock state change without a manual refresh
    refetchInterval: (query) => {
      const t = query.state.data?.tournament
      if (!t) return false
      if (t.status === 'active' || t.selections_unlocked) return 2 * 60 * 1000
      if (t.status === 'upcoming' || t.status === 'open') return 2 * 60 * 1000
      return false
    },
  })

  const { data: savedPreds } = useQuery({
    queryKey: ['predictions', id],
    queryFn: () => getPredictions(Number(id)),
    enabled: !!user,
  })

  const viewingOther = viewedUserId != null && viewedUserId !== user?.id
  const { data: viewedPreds } = useQuery({
    queryKey: ['predictions', id, viewedUserId],
    queryFn: () => getPredictions(Number(id), viewedUserId),
    enabled: viewingOther,
  })

  // Initialise picks from saved predictions, filtering out any stale match IDs
  useEffect(() => {
    if (savedPreds && data) {
      const validIds = new Set(data.matches.map(m => m.id))
      const map = {}
      for (const p of savedPreds) {
        if (p.predicted_winner_id != null && validIds.has(p.match_id))
          map[p.match_id] = p.predicted_winner_id
      }
      setPicks(map)

      if (!autoInitShownRef.current && user && data.tournament.status === 'open') {
        const isLocked = data.tournament.is_locked && !data.tournament.selections_unlocked
        const hasAnyPick = savedPreds.some(p => p.predicted_winner_id != null)
        if (!isLocked && !hasAnyPick) {
          autoInitShownRef.current = true
          const newPicks = computeAutoPicks()
          if (newPicks) {
            applyPicksAndCelebrate(newPicks)
            setShowDefaultPicksBanner(true)
          }
        }
      }
    }
  }, [savedPreds, data])

  // Initialise otherPicks (for admin editing another user's picks) from that user's saved predictions
  useEffect(() => {
    if (viewingOther && viewedPreds && data) {
      const validIds = new Set(data.matches.map(m => m.id))
      const map = {}
      for (const p of viewedPreds) {
        if (p.predicted_winner_id != null && validIds.has(p.match_id))
          map[p.match_id] = p.predicted_winner_id
      }
      setOtherPicks(map)
    }
  }, [viewingOther, viewedPreds, data])

  // Set initial view mode once: always 'picks' for open tournaments, or if user has picks, or if ?user= param present
  // DISABLED — Combined is the only view shown; kept for when Picks/Live Draw are re-enabled.
  // useEffect(() => {
  //   if (initialModeSet.current || savedPreds === undefined || !data) return
  //   initialModeSet.current = true
  //   if (searchParams.get('user') || data.tournament.status === 'open' || savedPreds.some(p => p.predicted_winner_id != null)) setViewMode('picks')
  // }, [savedPreds, data])

  // Auto-switch to 'live' when the draw locks mid-session and the user has no picks of their own
  // DISABLED — Combined is the only view shown; kept for when Picks/Live Draw are re-enabled.
  const _isLockedNow = !!(data?.tournament?.is_locked && !data?.tournament?.selections_unlocked)
  const _userHasPicks = savedPreds ? savedPreds.some(p => p.predicted_winner_id != null) : false
  // useEffect(() => {
  //   if (user && _isLockedNow && !_userHasPicks && viewMode === 'picks' && !viewingOther) {
  //     setViewMode('live')
  //   }
  // }, [_isLockedNow, _userHasPicks, viewMode, viewingOther, user])

  // ── Sidebar auto-hide ──────────────────────────────────────────────────
  // Cache the expanded sidebar width while it's showing (so we can reason
  // about it once it's collapsed). Declared before the auto effect so the
  // cache updates first when the body resizes.
  useEffect(() => {
    if (!sidebarCollapsed && bodyWidth > 0 && mainWidth > 0) {
      const sw = bodyWidth - mainWidth
      if (sw > 60) expandedSidebarW.current = sw
    }
  }, [sidebarCollapsed, bodyWidth, mainWidth])

  // Auto-hide the leagues sidebar so 4 rounds stay visible; re-show it when
  // there's room again. Disabled once the user manually toggles it.
  useEffect(() => {
    if (sidebarManual || bodyWidth <= 0 || !data) return
    const colUnit = 260 + 64 // mirrors CombinedView COL_W + COL_GAP (see fit calc below)
    const needed4Main = 4 * colUnit + 16 // draw-main width needed to fit 4 full rounds
    const projMainIfExpanded = bodyWidth - expandedSidebarW.current
    setSidebarCollapsed(projMainIfExpanded < needed4Main)
  }, [sidebarManual, bodyWidth, data])

  // Resume auto behaviour when navigating to a different tournament
  useEffect(() => { setSidebarManual(false) }, [id])

  // Auto-hide the round-selection header on scroll-down, reveal on scroll-up
  // (common site behaviour). The bracket's vertical scroll lives on the inner
  // .cv-scroll / .bracket-scroll element (created by a child component), so we
  // listen in the capture phase on document — timing-independent, no child ref.
  const [headerHidden, setHeaderHidden] = useState(false)
  const headerHiddenRef = useRef(false)
  useEffect(() => { headerHiddenRef.current = headerHidden }, [headerHidden])
  useEffect(() => {
    // Bobble guard: collapsing the header grows the scroll viewport, which can
    // nudge scrollTop and fire a reflow scroll event read as the OPPOSITE
    // direction — flipping the state straight back. Two defences:
    //   1. Deadband: require THRESH px of sustained travel in one direction
    //      before toggling, so tiny jitters never flip it.
    //   2. Settle window: ignore scroll events for the length of the collapse
    //      animation after each toggle, so its own reflow can't re-trigger.
    const THRESH = 40
    const SETTLE_MS = 340
    let lastY = 0
    let accum = 0
    let ignoreUntil = 0
    const apply = (hide) => {
      accum = 0
      if (headerHiddenRef.current === hide) return
      headerHiddenRef.current = hide
      ignoreUntil = performance.now() + SETTLE_MS
      setHeaderHidden(hide)
    }
    const onScroll = (e) => {
      const el = e.target
      if (!(el instanceof HTMLElement) || !el.matches?.('.cv-scroll, .bracket-scroll')) return
      const now = performance.now()
      const y = el.scrollTop
      const dy = y - lastY
      lastY = y
      if (now < ignoreUntil) return               // reflow during animation: ignore
      if (y <= 24) { apply(false); return }        // near the top: always show
      if ((dy > 0) !== (accum > 0)) accum = 0      // direction flipped: reset travel
      accum += dy
      if (accum > THRESH) apply(true)              // sustained down: hide
      else if (accum < -THRESH) apply(false)       // sustained up: reveal
    }
    document.addEventListener('scroll', onScroll, { capture: true, passive: true })
    return () => document.removeEventListener('scroll', onScroll, { capture: true })
  }, [])
  // Never leave the header hidden when the view or tournament changes
  useEffect(() => { setHeaderHidden(false) }, [viewMode, id])

  // Measure the right edge of the last visible round's boxes (relative to
  // .draw-body) so the right-hand round-nav button can sit just past the drawn
  // content rather than flush against the page edge. Re-runs whenever the
  // window, view, size, or sidebar changes; a ResizeObserver catches the rest.
  const [rightNavX, setRightNavX] = useState(null)
  useLayoutEffect(() => {
    const body = bodyNodeRef.current
    if (!body) return
    const measure = () => {
      // Anchor to the trailing connector gap's right edge when present (so the
      // button clears the green feed lines + H2H chip), else the last column.
      const gaps = body.querySelectorAll('.cv-gap')
      const cols = body.querySelectorAll('.cv-col, .bracket-col')
      const anchor = gaps[gaps.length - 1] || cols[cols.length - 1]
      if (!anchor) { setRightNavX(null); return }
      const bx = body.getBoundingClientRect().left
      setRightNavX(anchor.getBoundingClientRect().right - bx)
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(body)
    return () => ro.disconnect()
  }, [windowStart, data, mainWidth, bodyWidth, sidebarCollapsed, viewMode, headerHidden])

  const saveMutation = useMutation({
    mutationFn: (latestPicks) => savePredictions(Number(id), latestPicks),
    onSuccess: () => qc.invalidateQueries(['predictions', id]),
  })

  const saveOtherMutation = useMutation({
    mutationFn: (latestPicks) => savePredictions(Number(id), latestPicks, viewedUserId),
    onSuccess: () => qc.invalidateQueries(['predictions', id, viewedUserId]),
  })

  const refreshMutation = useMutation({
    mutationFn: () => refreshDraw(Number(id)),
    onSuccess: () => qc.invalidateQueries(['draw', id]),
  })

  const unlockMutation = useMutation({
    mutationFn: () => toggleUnlockSelections(Number(id)),
    onSuccess: () => { qc.invalidateQueries(['draw', id]); setShowUnlockConfirm(false) },
  })

  const applyPicksAndCelebrate = (newPicks) => {
    setPicks(newPicks)
    if (user) saveMutation.mutate(newPicks)
    if (data) {
      const nonByeIds = new Set(data.matches.filter(m => !m.is_bye).map(m => m.id))
      const total = nonByeIds.size
      const filled = Object.entries(newPicks).filter(([k, v]) => v != null && nonByeIds.has(Number(k))).length
      if (total > 0 && filled >= total) {
        if (celebrateTimerRef.current) clearTimeout(celebrateTimerRef.current)
        setCelebrating(true)
        celebrateTimerRef.current = setTimeout(() => setCelebrating(false), 3600)
      }
    }
  }

  const computeAutoPicks = () => {
    if (!data) return null
    const allPlayers = data.draw_entries
    const allMatches = data.matches

    const drawRanks = {}
    const seeded = allPlayers.filter(p => p.seed != null)
    for (const p of seeded) drawRanks[p.id] = p.seed
    const unseeded = allPlayers
      .filter(p => p.seed == null && p.name)
      .sort((a, b) => {
        if (a.ranking != null && b.ranking != null) return a.ranking - b.ranking
        if (a.ranking != null) return -1
        if (b.ranking != null) return 1
        return a.bracket_position - b.bracket_position
      })
    const autoOffset = seeded.reduce((max, p) => Math.max(max, p.seed), 0)
    unseeded.forEach((p, i) => { drawRanks[p.id] = autoOffset + i + 1 })

    const byKey = {}
    for (const m of allMatches) byKey[`${m.round_number}:${m.match_number}`] = m

    const newPicks = {}
    const resolvedWinner = {}
    const roundNums = [...new Set(allMatches.map(m => m.round_number))].sort((a, b) => a - b)

    for (const rn of roundNums) {
      const roundMatches = allMatches
        .filter(m => m.round_number === rn)
        .sort((a, b) => a.match_number - b.match_number)

      for (const m of roundMatches) {
        if (m.is_bye) {
          resolvedWinner[m.id] = m.player1?.id ?? null
          continue
        }

        let p1id, p2id
        if (rn === 1) {
          p1id = m.player1?.id ?? null
          p2id = m.player2?.id ?? null
        } else {
          const f1 = byKey[`${rn - 1}:${m.match_number * 2 - 1}`]
          const f2 = byKey[`${rn - 1}:${m.match_number * 2}`]
          p1id = f1 ? resolvedWinner[f1.id] : null
          p2id = f2 ? resolvedWinner[f2.id] : null
        }

        if (p1id == null || p2id == null) continue

        const rank1 = drawRanks[p1id] ?? Infinity
        const rank2 = drawRanks[p2id] ?? Infinity
        const winnerId = rank1 <= rank2 ? p1id : p2id

        newPicks[m.id] = winnerId
        resolvedWinner[m.id] = winnerId
      }
    }

    return newPicks
  }

  const autoPopulatePicks = () => {
    if (!data) return
    const isLocked = data.tournament.is_locked && !data.tournament.selections_unlocked
    if (isLocked) return

    const newPicks = computeAutoPicks()
    if (!newPicks) return

    const hasConflict = Object.entries(newPicks).some(
      ([matchId, winnerId]) => picks[Number(matchId)] != null && picks[Number(matchId)] !== winnerId
    )

    if (hasConflict) {
      setPendingAutoPicks(newPicks)
    } else {
      applyPicksAndCelebrate(newPicks)
    }
  }

  const countPicksAndUpsets = () => {
    if (!data) return { total: 0, upsets: 0 }
    const allPlayers = data.draw_entries
    const allMatches = data.matches

    const drawRanks = {}
    const seeded = allPlayers.filter(p => p.seed != null)
    for (const p of seeded) drawRanks[p.id] = p.seed
    const unseeded = allPlayers
      .filter(p => p.seed == null && p.name)
      .sort((a, b) => {
        if (a.ranking != null && b.ranking != null) return a.ranking - b.ranking
        if (a.ranking != null) return -1
        if (b.ranking != null) return 1
        return a.bracket_position - b.bracket_position
      })
    const countOffset = seeded.reduce((max, p) => Math.max(max, p.seed), 0)
    unseeded.forEach((p, i) => { drawRanks[p.id] = countOffset + i + 1 })

    const byKey = {}
    for (const m of allMatches) byKey[`${m.round_number}:${m.match_number}`] = m

    let total = 0
    let upsets = 0
    const resolvedAdvancer = {}
    const roundNums = [...new Set(allMatches.map(m => m.round_number))].sort((a, b) => a - b)

    for (const rn of roundNums) {
      const roundMatches = allMatches
        .filter(m => m.round_number === rn)
        .sort((a, b) => a.match_number - b.match_number)

      for (const m of roundMatches) {
        if (m.is_bye) { resolvedAdvancer[m.id] = m.player1?.id ?? null; continue }

        let p1id, p2id
        if (rn === 1) {
          p1id = m.player1?.id ?? null
          p2id = m.player2?.id ?? null
        } else {
          const f1 = byKey[`${rn - 1}:${m.match_number * 2 - 1}`]
          const f2 = byKey[`${rn - 1}:${m.match_number * 2}`]
          p1id = f1 ? resolvedAdvancer[f1.id] : null
          p2id = f2 ? resolvedAdvancer[f2.id] : null
        }

        const userPick = picks[m.id]
        if (userPick != null) {
          total++
          if (p1id != null && p2id != null) {
            const rank1 = drawRanks[p1id] ?? Infinity
            const rank2 = drawRanks[p2id] ?? Infinity
            const expectedWinner = rank1 <= rank2 ? p1id : p2id
            if (userPick !== expectedWinner) upsets++
          }
          resolvedAdvancer[m.id] = userPick
        } else {
          resolvedAdvancer[m.id] = null
        }
      }
    }

    return { total, upsets }
  }

  const handleClearSelections = () => {
    const { total } = countPicksAndUpsets()
    const cleared = Object.fromEntries(Object.keys(picks).map(k => [k, null]))
    setPicks(cleared)
    if (user) saveMutation.mutate(cleared)
    setShowClearConfirm(false)
    clearToastKeyRef.current += 1
    setClearToast({ key: clearToastKeyRef.current, msg: `${total} selection${total !== 1 ? 's' : ''} cleared` })
    if (clearToastTimerRef.current) clearTimeout(clearToastTimerRef.current)
    clearToastTimerRef.current = setTimeout(() => setClearToast(null), 3500)
  }

  // Cascade-clear: if switching picks, clear downstream picks for the old player
  const computeNextPicks = (basePicks, matchId, playerId) => {
    const newPicks = { ...basePicks }
    const oldPlayerId = newPicks[matchId]
    if (oldPlayerId != null && oldPlayerId !== playerId && data) {
      const byKey = {}
      for (const m of data.matches) byKey[`${m.round_number}:${m.match_number}`] = m
      let cur = data.matches.find(m => m.id === matchId)
      while (cur) {
        const next = byKey[`${cur.round_number + 1}:${Math.ceil(cur.match_number / 2)}`]
        if (!next) break
        if (newPicks[next.id] === oldPlayerId) {
          newPicks[next.id] = null
        }
        cur = next
      }
    }
    newPicks[matchId] = playerId
    return newPicks
  }

  const handlePick = (matchId, playerId) => {
    const newPicks = computeNextPicks(picks, matchId, playerId)
    setPicks(newPicks)
    if (user && !locked) {
      saveMutation.mutate(newPicks)
    }

    // Celebrate when every non-bye match has a pick
    if (data && !locked) {
      const nonByeIds = new Set(data.matches.filter(m => !m.is_bye).map(m => m.id))
      const total = nonByeIds.size
      const filled = Object.entries(newPicks).filter(([k, v]) => v != null && nonByeIds.has(Number(k))).length
      if (total > 0 && filled >= total) {
        if (celebrateTimerRef.current) clearTimeout(celebrateTimerRef.current)
        setCelebrating(true)
        celebrateTimerRef.current = setTimeout(() => setCelebrating(false), 3600)
      }
    }
  }

  // Admin making picks on behalf of another user
  const handlePickForOther = (matchId, playerId) => {
    const newPicks = computeNextPicks(otherPicks, matchId, playerId)
    setOtherPicks(newPicks)
    saveOtherMutation.mutate(newPicks)
  }

  const everHadPicksRef = useRef(false)

  if (isLoading) return <div className="page-loading">Loading draw…</div>
  if (error) return <div className="page-error">Failed to load draw.</div>

  const { tournament, matches, draw_entries: players } = data
  const locked = tournament.is_locked && !tournament.selections_unlocked
  const nonByeMatchIds = new Set(matches.filter(m => !m.is_bye).map(m => m.id))
  const pickedCount = Object.entries(picks).filter(([k, v]) => v != null && nonByeMatchIds.has(Number(k))).length
  const userHasPicks = savedPreds ? savedPreds.some(p => p.predicted_winner_id != null) : pickedCount > 0
  const picksDisabled = !!user && locked && !userHasPicks
  const picksOwner = viewMode === 'picks' ? (viewingOther ? viewedUserName : user?.username) ?? null : null

  // Admins may edit another user's picks while predictions are still unlocked
  const canEditOther = viewingOther && !!user?.is_admin && !locked

  // When viewing another user's picks, build their picks map from fetched predictions
  const viewedPicksMap = viewingOther && viewedPreds
    ? Object.fromEntries(viewedPreds.filter(p => p.predicted_winner_id != null).map(p => [p.match_id, p.predicted_winner_id]))
    : null

  const activePicks = viewingOther ? (canEditOther ? otherPicks : (viewedPicksMap ?? {})) : picks
  const totalPredictable = matches.filter(m => !m.is_bye).length

  // Round pager: the bracket shows DRAW_WINDOW rounds at a time; the dots below
  // page the window forward/back. State lives here so the dots can sit in the
  // header, while BracketView renders the corresponding slice.
  const roundNumbers = [...new Set(matches.map(m => m.round_number))].sort((a, b) => a - b)
  const roundNameByNum = {}
  const roundCountByNum = {}
  for (const m of matches) {
    if (!(m.round_number in roundNameByNum)) roundNameByNum[m.round_number] = m.round_name
    roundCountByNum[m.round_number] = (roundCountByNum[m.round_number] || 0) + 1
  }
  // Short label inside each dot: final stages by name, earlier rounds by order
  // (e.g. Grand Slam → R1, R2, R3, R16, QF, SF, F).
  const dotLabel = (rn, i) => {
    const c = roundCountByNum[rn]
    if (c === 1) return 'F'
    if (c === 2) return 'SF'
    if (c === 4) return 'QF'
    if (c === 8) return 'R16'
    return `R${i + 1}`
  }
  // Round label by DRAW SIZE at that round (players = 2×matches): R128/R64/R32/
  // R16, then QF/SF/F. Used on the edge round-nav buttons.
  const navLabel = (rn) => {
    const c = roundCountByNum[rn]
    if (c === 1) return 'F'
    if (c === 2) return 'SF'
    if (c === 4) return 'QF'
    return `R${c * 2}`
  }
  // Pager columns: one per round for Picks/Live; Combined adds a Champion column.
  const roundCols = roundNumbers.map((rn, i) => ({ label: dotLabel(rn, i), title: roundNameByNum[rn] || `Round ${rn}`, nav: navLabel(rn) }))
  const pagerColumns = viewMode === 'combined'
    ? [...roundCols, { label: '🏆', title: 'Champion', nav: 'CHAMP' }]
    : roundCols
  const columnCount = pagerColumns.length

  // How many columns fit in the bracket area: shrink from 4 toward 1 as it
  // narrows; a column is only counted when it fits ENTIRELY (no h-scroll).
  // 324 mirrors CombinedView's COL_W(260) + COL_GAP(64) — the only view shown.
  // (If Picks/Live are ever re-enabled, restore a per-view unit: BracketView
  // is (anyScores ? 300 : 252) + 24.)
  const COL_GAP_PX = 24 // credited back for the last column's missing trailing gap
  const colUnit = 260 + 64
  // Left gutter reserved INSIDE the draw for the left round-nav button when the
  // sidebar is expanded (collapsed → the button lives in the page-edge gutter).
  // Tuned tight to the button's own footprint (left:3px + its CHAMP-sized
  // width) plus a few px of breathing room — not a generous guess — so the
  // draw content sits close to the button rather than leaving a wide gap.
  const NAV_INSET = 28
  const computeWindow = (inset) => {
    const usableW = mainWidth - 24 /* scroll padding */ - 16 /* vertical scrollbar */ - inset
    const fitCols = mainWidth > 0 ? Math.floor((usableW + COL_GAP_PX) / colUnit) : 4
    const fit = Math.max(1, fitCols) // how many the WIDTH allows, pre-clamp
    const dw = Math.min(4, columnCount, fit)
    const maxStart = Math.max(0, columnCount - dw)
    return { dw, maxStart, pos: Math.min(windowStart, maxStart), fit }
  }
  // Pass 1 (no inset) decides whether the left button COULD show (paging
  // possible at all); pass 2 reserves its gutter. Reserved whenever paging is
  // possible — not just while the button is visible (pos > 0) — so pressing
  // the right button doesn't shift the whole bracket sideways by the gutter
  // width the moment the left button first appears.
  const w0 = computeWindow(0)

  // COMPACT draw mode: when fewer than 2 full-size rounds would fit in NORMAL
  // mode, go all-in on showing TWO rounds anyway: the collapsed sidebar strip
  // overlays the draw instead of taking flex space (its reveal button and the
  // left round-nav button float over the boxes), country flags are dropped,
  // and the draw is zoomed down until two rounds fit without horizontal
  // scrolling. Decided from bodyWidth ONLY (stable — unaffected by the
  // overlay/zoom outputs) so the mode can't feedback-loop with its own layout
  // changes. Threshold = what normal mode needs for 2 rounds: 2 column units
  // + the collapsed sidebar strip (44) + scroll padding (24) + scrollbar (16)
  // − the last column's trailing-gap credit (COL_GAP_PX).
  const COMPACT_BREAK = 2 * colUnit + 44 + 24 + 16 - COL_GAP_PX
  const compactDraw = viewMode === 'combined' && bodyWidth > 0 && sidebarCollapsed
    && bodyWidth < COMPACT_BREAK
  // Zoomed content is inset by the left nav gutter (drawInsetLeft below, +4 —
  // mirrors CombinedView's actual paddingLeft). The right boundary targets
  // the right round-nav button's OWN measured position (navBtnW, pinned at
  // RIGHT_BTN_MARGIN from the body's right edge in compact mode — see the
  // button's style below) minus a small requested clearance, rather than a
  // symmetric guessed gutter — the last visible round's trailing connector
  // stub carries a real, clickable H2H chip, and the goal is that chip
  // sitting almost flush against the button, not just clear of it.
  // COMPACT_COL_W/COMPACT_GAP mirror CombinedView's COMPACT_COL_W/COL_GAP —
  // NOT colUnit/COL_GAP_PX (260+24), which describe normal mode's wider
  // columns and would shrink the draw more than the actually-rendered
  // (narrower) compact content needs.
  const COMPACT_COL_W = 158
  const COMPACT_GAP = 64
  const RIGHT_BTN_MARGIN = 3 // the right button's own distance from the body's right edge
  const H2H_GAP = 3          // requested clearance between the trailing H2H chip and the button
  const drawLeftPad = NAV_INSET + 4
  // TRAILING_W mirrors CombinedView's own TRAILING_W (H2H_X + half the H2H
  // chip's rotated visual width): credit the trailing stub only for the H2H
  // chip itself, not a full COMPACT_GAP — the rest of that connector line is
  // decorative and is meant to overflow off the viewport edge once zoomed
  // in, not reserve dead space that would otherwise separate the H2H chip
  // from the right button.
  const TRAILING_W = 8 + 9
  const naturalWCompact = 2 * COMPACT_COL_W + 1 * COMPACT_GAP + TRAILING_W
  const rightBoundary = bodyWidth - RIGHT_BTN_MARGIN - navBtnW - H2H_GAP
  const drawZoom = compactDraw
    ? Math.max(0.5, (rightBoundary - drawLeftPad) / naturalWCompact)
    : 1

  // Left gutter: reserved whenever paging is possible in normal mode (so the
  // bracket doesn't shift sideways when the left button first appears), and
  // ALWAYS in compact mode — there the button floats over the draw, and the
  // gutter keeps the leftmost boxes clear of it (they'd otherwise start at
  // the scroll padding, right underneath the button).
  const leftNavInDraw = compactDraw || (!sidebarCollapsed && columnCount > w0.dw)
  const drawInsetLeft = leftNavInDraw ? NAV_INSET : 0
  let { dw: DRAW_WINDOW, maxStart: maxWindowStart, pos: windowPos, fit: windowFit } = computeWindow(drawInsetLeft)
  if (compactDraw) {
    DRAW_WINDOW = Math.min(2, columnCount)
    maxWindowStart = Math.max(0, columnCount - DRAW_WINDOW)
    windowPos = Math.min(windowStart, maxWindowStart)
    windowFit = 2
  }
  const showPager = columnCount > DRAW_WINDOW
  // Viewport so narrow that only 1–2 rounds fit → keep the sub-header hidden
  // at all times (vertical space is at a premium; the edge round-nav buttons
  // still provide paging). Width-based (windowFit), not DRAW_WINDOW, so a
  // small draw on a wide screen doesn't hide it.
  const headerForcedHidden = windowFit <= 2

  // Pixel geometry for the round dots + the shaded window highlight behind them.
  const DOT_SIZE = 38, DOT_GAP = 10, DOT_PAD = 6
  const DOT_STEP = DOT_SIZE + DOT_GAP

  // Responsive header stages (approx element widths; tune if titles are long):
  //  'full'    — everything shown; switch centred between info and pager.
  //  'compact' — hide tournament info + right-hand status; keep switch + dots.
  //  'minimal' — replace the dot pager with two large prev/next arrows.
  const DOTS_W = columnCount * DOT_SIZE + (columnCount - 1) * DOT_GAP + 2 * DOT_PAD + 110
  const SWITCH_W = 255, INFO_W = 300, RIGHT_W = 220, HPAD = 48, HGAP = 16
  const needFull = INFO_W + SWITCH_W + DOTS_W + RIGHT_W + 3 * HGAP + HPAD
  const needCompact = SWITCH_W + DOTS_W + HGAP + HPAD
  const headerStage = bodyWidth <= 0 || bodyWidth >= needFull ? 'full'
    : bodyWidth >= needCompact ? 'compact'
    : 'minimal'

  // Once picks > 0 this session, keep the badge visible through any transient refetch resets
  if (pickedCount > 0) everHadPicksRef.current = true
  const showPicksBadge = user && !locked && (saveMutation.isPending || everHadPicksRef.current || pickedCount > 0)

  // Header helpers
  const catShort = tournament.category ? tournament.category.replace(/^(ATP|WTA)\s+/, '') : ''
  const tourLabel = `${tournament.gender === 'M' ? 'ATP' : 'WTA'}${catShort ? ' ' + catShort : ''}`
  const surface = tournament.surface ? tournament.surface.replace(/\s*\(.*?\)/g, '') : ''

  const fmtDateRange = (start, end) => {
    if (!start) return ''
    const s = new Date(start + 'T00:00:00')
    const mo = d => d.toLocaleDateString('en-US', { month: 'short' })
    if (!end) return `${mo(s)} ${s.getDate()}`
    const e = new Date(end + 'T00:00:00')
    return s.getMonth() === e.getMonth() && s.getFullYear() === e.getFullYear()
      ? `${mo(s)} ${s.getDate()} – ${e.getDate()}`
      : `${mo(s)} ${s.getDate()} – ${mo(e)} ${e.getDate()}`
  }

  const fmtModified = raw => {
    const d = new Date(raw.endsWith('Z') || raw.includes('+') ? raw : raw + 'Z')
    const date = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    const time = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })
      .replace(' AM', 'am').replace(' PM', 'pm')
    return `${date}, ${time}`
  }

  return (
    <div className="draw-page">
      <div className={clsx('draw-header', `draw-header--${headerStage}`, { 'draw-header--collapsed': headerHidden || headerForcedHidden })}>
        {headerStage === 'full' && (
        <div className="draw-header-top">
          <div className="draw-name-block">
            <h1 className="draw-title">
              {tournament.name}
              {catShort && <span className="draw-title-level">{tourLabel}</span>}
              {tournament.wiki_page_id && (
                <a
                  href={`https://en.wikipedia.org/?curid=${tournament.wiki_page_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="draw-wiki-link"
                  title={tournament.wiki_page_title}
                >
                  🌐
                </a>
              )}
            </h1>
            <div className="draw-meta-row">
              <span className="draw-meta-left">
                {[tournament.city, surface, tournament.start_date ? fmtDateRange(tournament.start_date, tournament.end_date) : null].filter(Boolean).join(' · ')}
              </span>
            </div>
          </div>
        </div>
        )}
        {/* Picks/Live Draw switcher. "Picks" renders CombinedView (picks +
            live result merged); "Live Draw" renders BracketView in 'live'
            mode (actual results only, no predictions). Default is 'combined'
            (Picks). The old dedicated picks-only BracketView mode still
            exists and is reachable via viewMode === 'picks' elsewhere in
            this file, but this switcher only offers the two user-facing
            choices. */}
        <div className="draw-mode-buttons">
          <button
            className={clsx('draw-mode-btn', { active: viewMode === 'combined' })}
            onClick={() => setViewMode('combined')}
            disabled={picksDisabled}
            title={picksDisabled ? 'You have no picks for this tournament' : undefined}
          >
            Picks
          </button>
          <button
            className={clsx('draw-mode-btn', { active: viewMode === 'live' })}
            onClick={() => setViewMode('live')}
          >
            Live Draw
          </button>
        </div>
        <div className="draw-header-center">
          {showPager && headerStage === 'minimal' && (
            <div className="bracket-pager bracket-pager--minimal">
              <button
                className="bracket-pager-arrow"
                onClick={() => setWindowStart(windowPos - 1)}
                disabled={windowPos === 0}
                aria-label="Earlier rounds"
              >
                ‹
              </button>
              <button
                className="bracket-pager-arrow"
                onClick={() => setWindowStart(windowPos + 1)}
                disabled={windowPos === maxWindowStart}
                aria-label="Later rounds"
              >
                ›
              </button>
            </div>
          )}
          {showPager && headerStage !== 'minimal' && (
            <div className="bracket-pager">
              <button
                className={clsx('bracket-pager-arrow', { hidden: windowPos === 0 })}
                onClick={() => setWindowStart(windowPos - 1)}
                aria-label="Earlier rounds"
              >
                ‹
              </button>
              <div className="bracket-dots" style={{ padding: DOT_PAD, gap: DOT_GAP }}>
                <span
                  className="bracket-dots-highlight"
                  aria-hidden="true"
                  style={{
                    left: windowPos * DOT_STEP,
                    width: DRAW_WINDOW * DOT_SIZE + (DRAW_WINDOW - 1) * DOT_GAP + 2 * DOT_PAD,
                  }}
                />
                {pagerColumns.map((col, i) => {
                  const inWindow = i >= windowPos && i < windowPos + DRAW_WINDOW
                  return (
                    <button
                      key={i}
                      className={clsx('bracket-dot', { 'in-window': inWindow })}
                      style={{ width: DOT_SIZE, height: DOT_SIZE }}
                      onClick={() => setWindowStart(
                        // Reveal the clicked column at the nearest edge (minimal
                        // shift): left edge if it's left of the window, right
                        // edge if it's right, otherwise leave the window as-is.
                        i < windowPos ? i
                          : i >= windowPos + DRAW_WINDOW ? i - DRAW_WINDOW + 1
                          : windowPos
                      )}
                      aria-label={col.title}
                      title={col.title}
                    >
                      {col.label}
                    </button>
                  )
                })}
              </div>
              <button
                className={clsx('bracket-pager-arrow', { hidden: windowPos === maxWindowStart })}
                onClick={() => setWindowStart(windowPos + 1)}
                aria-label="Later rounds"
              >
                ›
              </button>
            </div>
          )}
        </div>
        {headerStage === 'full' && (
        <div className="draw-header-right">
          <div className="draw-picks-zone">
            {user && !locked && !viewingOther && (viewMode === 'picks' || viewMode === 'combined') && (
              <button
                className="btn-auto-populate"
                onClick={autoPopulatePicks}
                title="Fill all picks using seeds and world rankings"
              >
                Auto-Populate Picks
              </button>
            )}
            {user && !locked && !viewingOther && pickedCount > 0 && (
              <button
                className="btn-clear-selections"
                onClick={() => setShowClearConfirm(true)}
              >
                Clear Selections
              </button>
            )}
          </div>
          <div className="draw-header-actions">
          {tournament.selections_unlocked ? (
            <span
              className={`lock-badge lock-badge--unlocked${user?.is_admin ? ' lock-badge--admin' : ''}`}
              onClick={user?.is_admin ? () => unlockMutation.mutate() : undefined}
            >
              🔓 Predictions UNLOCKED
            </span>
          ) : locked ? (
            <div style={{ position: 'relative' }}>
              <span
                className={`lock-badge${user?.is_admin ? ' lock-badge--admin' : ''}`}
                onClick={user?.is_admin ? () => setShowUnlockConfirm(v => !v) : undefined}
              >
                🔒 Predictions locked
              </span>
              {showUnlockConfirm && (
                <div className="unlock-confirm">
                  <p>Unlock predictions for this tournament?<br /><span className="unlock-confirm-sub">Players will be able to make picks.</span></p>
                  <div className="unlock-confirm-actions">
                    <button className="btn-primary" onClick={() => unlockMutation.mutate()} disabled={unlockMutation.isPending}>
                      {unlockMutation.isPending ? 'Unlocking…' : 'Unlock'}
                    </button>
                    <button className="btn-secondary" onClick={() => setShowUnlockConfirm(false)}>Cancel</button>
                  </div>
                </div>
              )}
            </div>
          ) : (
            tournament.closing_time && (() => {
              const dt = new Date(tournament.closing_time + 'Z')
              const userLocal = dt.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })
              let venueLocal = null
              if (tournament.venue_timezone) {
                try {
                  venueLocal = 'Local: ' + dt.toLocaleString('en-US', { timeZone: tournament.venue_timezone, month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })
                } catch {}
              }
              return (
                <span className="muted" title={venueLocal ?? undefined}>
                  Pick selection closes {userLocal}
                </span>
              )
            })()
          )}
          {showPicksBadge && (
            <span className={`saved-badge${pickedCount < totalPredictable ? ' saved-badge--incomplete' : ''}`}>
              {pickedCount < totalPredictable
                ? `⚠ ${pickedCount}/${totalPredictable} picks saved — Populate to COMPETE`
                : `✓ ${pickedCount}/${totalPredictable} picks saved`}
            </span>
          )}
          {!user && (
            <Link to="/login" className="btn-primary">Log in to make picks</Link>
          )}
          {tournament.status === 'open' && (
            <div className="draw-status-level">
              <span className="draw-meta-right">
                {tournament.draw_released_direct_at
                  ? <span className="draw-confirmed">✓ DA</span>
                  : tournament.draw_release_direct
                    ? <span className="draw-pending-label">DA: {new Date(tournament.draw_release_direct + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span>
                    : null}
                {tournament.draw_released_qualifiers_at
                  ? <span className="draw-confirmed">✓ Qual</span>
                  : tournament.draw_release_qualifiers
                    ? <span className="draw-pending-label">Qual: {new Date(tournament.draw_release_qualifiers + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span>
                    : null}
              </span>
            </div>
          )}
          </div>
        </div>
        )}
      </div>

      {saveMutation.isError && (
        <div className="error" style={{ padding: '0 1.5rem' }}>
          Failed to save: {saveMutation.error?.response?.data?.detail || 'Unknown error'}
        </div>
      )}

      {celebrating && <CelebrationOverlay />}

      {pendingAutoPicks && (
        <div className="auto-populate-overlay" onClick={() => setPendingAutoPicks(null)}>
          <div className="auto-populate-modal" onClick={e => e.stopPropagation()}>
            <h3 className="auto-populate-modal-title">Replace existing picks?</h3>
            <p className="auto-populate-modal-body">
              You already have picks that differ from the auto-populated selections.
              Replace them with seed-based picks?
            </p>
            <div className="auto-populate-modal-actions">
              <button
                className="btn-primary"
                onClick={() => { applyPicksAndCelebrate(pendingAutoPicks); setPendingAutoPicks(null) }}
              >
                Replace my picks
              </button>
              <button
                className="btn-secondary"
                onClick={() => {
                  const merged = { ...pendingAutoPicks }
                  Object.entries(picks).forEach(([mid, wid]) => { if (wid != null) merged[Number(mid)] = wid })
                  applyPicksAndCelebrate(merged)
                  setPendingAutoPicks(null)
                }}
              >
                Keep my picks
              </button>
              <button
                className="btn-secondary"
                onClick={() => setPendingAutoPicks(null)}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {showClearConfirm && (() => {
        const { total, upsets } = countPicksAndUpsets()
        return (
          <div className="auto-populate-overlay" onClick={() => setShowClearConfirm(false)}>
            <div className="auto-populate-modal" onClick={e => e.stopPropagation()}>
              <h3 className="auto-populate-modal-title">Clear all selections?</h3>
              <p className="auto-populate-modal-body">
                This will clear {total} match selection{total !== 1 ? 's' : ''}
                {upsets > 0 ? `, including ${upsets} upset${upsets !== 1 ? 's' : ''}` : ''}.
              </p>
              <div className="auto-populate-modal-actions">
                <button className="btn-secondary" onClick={() => setShowClearConfirm(false)}>
                  Cancel
                </button>
                <button className="btn-danger" onClick={handleClearSelections}>
                  Clear selections
                </button>
              </div>
            </div>
          </div>
        )
      })()}

      {clearToast && (
        <div key={clearToast.key} className="clear-toast">{clearToast.msg}</div>
      )}

      {showDefaultPicksBanner && (
        <div className="default-picks-banner">
          <span className="default-picks-banner-icon">✓</span>
          <p className="default-picks-banner-text">
            Your default predictions have been made, using the higher ranked player for the win.
            Please select your <strong>UPSETS</strong> now!
          </p>
          <button
            className="default-picks-banner-close"
            onClick={() => setShowDefaultPicksBanner(false)}
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      )}

      <div className="draw-body" ref={bodyRef}>
        <DrawSidebar
          tournamentId={Number(id)}
          tournament={tournament}
          selectedUserId={viewedUserId}
          defaultLeagueId={searchParams.get('league') ? Number(searchParams.get('league')) : undefined}
          collapsed={sidebarCollapsed}
          overlay={compactDraw}
          onToggleCollapsed={() => { setSidebarManual(true); setSidebarCollapsed(c => !c) }}
          onSelectUser={(uid, uname) => {
            setViewedUserId(uid)
            setViewedUserName(uname ?? null)
            // Previously switched to the (now-disabled) Picks view here.
            // Combined view already reads the selected user's picks via
            // activePicks/viewingOther, so no view-mode change is needed.
          }}
        />

        <div className="draw-main" ref={mainRef}>
          {viewMode === 'combined' ? (
            <CombinedView
              tournament={tournament}
              matches={matches}
              players={players}
              picks={user ? activePicks : {}}
              onPick={viewingOther ? (canEditOther ? handlePickForOther : () => {}) : handlePick}
              locked={!user || locked || (viewingOther && !canEditOther)}
              windowStart={windowPos}
              windowSize={DRAW_WINDOW}
              labelsHidden={headerHidden}
              insetLeft={drawInsetLeft}
              compact={compactDraw}
              zoom={drawZoom}
            />
          ) : (
            <BracketView
              tournament={tournament}
              matches={matches}
              players={players}
              picks={user ? activePicks : {}}
              onPick={viewingOther ? (canEditOther ? handlePickForOther : () => {}) : handlePick}
              locked={!user || locked || (viewingOther && !canEditOther)}
              mode={viewMode}
              picksOwner={picksOwner}
              windowStart={windowPos}
              windowSize={DRAW_WINDOW}
              labelsHidden={headerHidden}
              insetLeft={drawInsetLeft}
            />
          )}

        </div>

        {/* Big edge buttons to page the round just off-screen. The left button
            hugs the page edge; the right one, in compact mode, is pinned to
            the far right edge instead (drawZoom is computed to bring the
            content right up to it — see the comment there) — in normal mode
            it still sits just past the last drawn round (rightNavX = last
            visible column's right edge, measured below). */}
        {showPager && windowPos > 0 && (
          <button
            ref={navBtnLeftRef}
            className="round-nav round-nav--left"
            style={{ left: sidebarCollapsed ? 3 : Math.max(3, bodyWidth - mainWidth + 3) }}
            onClick={() => setWindowStart(windowPos - 1)}
            title={`Show ${pagerColumns[windowPos - 1].title}`}
            aria-label={`Show ${pagerColumns[windowPos - 1].title}`}
          >
            <span className="round-nav-label round-nav-label--sizer" aria-hidden="true">CHAMP</span>
            <span className="round-nav-label">{pagerColumns[windowPos - 1].nav}</span>
          </button>
        )}
        {showPager && windowPos < maxWindowStart && (compactDraw || rightNavX != null) && (
          <button
            ref={navBtnRightRef}
            className="round-nav round-nav--right"
            style={compactDraw ? { right: 3, left: 'auto' } : { left: Math.min(rightNavX + 6, bodyWidth - 30) }}
            onClick={() => setWindowStart(windowPos + 1)}
            title={`Show ${pagerColumns[windowPos + DRAW_WINDOW].title}`}
            aria-label={`Show ${pagerColumns[windowPos + DRAW_WINDOW].title}`}
          >
            <span className="round-nav-label round-nav-label--sizer" aria-hidden="true">CHAMP</span>
            <span className="round-nav-label">{pagerColumns[windowPos + DRAW_WINDOW].nav}</span>
          </button>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Celebration overlay
// ---------------------------------------------------------------------------

const PARTY_EMOJIS = ['🎉', '🎊', '🥳', '🏆', '🎾', '⭐', '✨', '🌟']

function CelebrationOverlay() {
  const [particles] = useState(() =>
    Array.from({ length: 30 }, (_, i) => {
      const angle = (i / 30) * 2 * Math.PI + (Math.random() - 0.5) * 0.4
      const dist = 130 + Math.random() * 210
      return {
        id: i,
        emoji: PARTY_EMOJIS[i % PARTY_EMOJIS.length],
        tx: Math.round(Math.cos(angle) * dist),
        ty: Math.round(Math.sin(angle) * dist),
        rot: Math.round((Math.random() - 0.5) * 720),
        delay: `${(Math.random() * 0.3).toFixed(2)}s`,
        dur: `${(1.2 + Math.random() * 0.9).toFixed(2)}s`,
        size: `${(1.5 + Math.random() * 1.5).toFixed(1)}rem`,
      }
    })
  )

  return (
    <div className="celebration-overlay">
      {particles.map(p => (
        <span
          key={p.id}
          className="celebration-particle"
          style={{
            '--tx': `${p.tx}px`,
            '--ty': `${p.ty}px`,
            '--rot': `${p.rot}deg`,
            '--delay': p.delay,
            '--dur': p.dur,
            fontSize: p.size,
          }}
        >
          {p.emoji}
        </span>
      ))}
      <div className="celebration-banner">🎉 Bracket complete!</div>
    </div>
  )
}
