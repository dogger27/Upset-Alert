/**
 * TournamentDraw — shows the bracket for one tournament.
 * Logged-in users can make / update predictions until the lock time.
 */
import { useState, useEffect, useLayoutEffect, useMemo, useRef, useCallback } from 'react'
import { useParams, Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { getDraw, listTournaments, refreshDraw, toggleUnlockSelections } from '../api/tournaments'
import { getPredictions, savePredictions } from '../api/predictions'
import { useAuth } from '../store/auth'
import BracketView, { COL_W as BV_COL_W, COL_W_SCORES as BV_COL_W_SCORES, COL_GAP as BV_COL_GAP } from '../components/BracketView'
import CombinedView, { COL_W as CV_COL_W, COMPACT_COL_W as CV_COMPACT_COL_W, COL_GAP as CV_COL_GAP, H2H_X as CV_H2H_X } from '../components/CombinedView'
import DrawSidebar from '../components/DrawSidebar'
import './TournamentDraw.css'

// Tier as it appears in the site's tournament-type pills — "GS" for the slams,
// otherwise the tour level (mirrors DrawHistory's categoryShort).
function categoryShort(cat) {
  if (!cat) return ''
  if (/slam/i.test(cat)) return 'GS'
  if (cat.includes('1000')) return '1000'
  if (cat.includes('500')) return '500'
  return '250'
}

// The header's prev/next buttons swap :id in place, which React Router serves
// from the SAME component instance — so picks state and the one-shot refs
// below (auto default picks, "ever had picks") would leak from one draw into
// the next. Keying on the id forces a clean mount per draw instead.
export default function TournamentDrawRoute() {
  const { id } = useParams()
  return <TournamentDraw key={id} />
}

// Boxes awaiting a pick, in either view: CombinedView outlines the pair of
// feeder boxes, BracketView outlines the match box itself. Both classes are
// only ever applied when the viewer can actually make the pick.
const MISSING_PICK_SEL = '.cv-match-outline--missing, .match-box.missing-pick'
// How far past the viewport edge a box must be before it counts as off-screen.
const EDGE_SLACK = 8

function TournamentDraw() {
  const { id } = useParams()
  const navigate = useNavigate()
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
  // In-flight touch gesture for swipe-to-page (see the handlers further down).
  const swipeRef = useRef(null)
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
  // right edge (for positioning the right-hand round-nav button), and to bind
  // the swipe's touchmove natively (below).
  const bodyNodeRef = useRef(null)
  const scrollerRef = useRef(null)   // .cv-scroll / .bracket-scroll, re-found on each measure
  // Which league the sidebar is showing (null = Global). Owned here because the
  // draw itself needs it — the per-match predictors popup lists that league's
  // members — while the <select> that sets it lives in DrawSidebar.
  const [activeLeagueId, setActiveLeagueId] = useState(null)
  // Holds the current render's touchmove handler. Refreshed by plain
  // assignment further down rather than in an effect: the handler is defined
  // after this component's early returns, so a hook there would break the
  // rules-of-hooks ordering.
  const swipeMoveRef = useRef(null)
  // React registers its synthetic touchmove as a PASSIVE listener, where
  // preventDefault() is silently ignored — so cancelling a native pan requires
  // listening natively with { passive: false }.
  const nativeTouchMove = useCallback((e) => { swipeMoveRef.current?.(e) }, [])
  const bodyRef = useCallback((node) => {
    if (bodyNodeRef.current) bodyNodeRef.current.removeEventListener('touchmove', nativeTouchMove)
    bodyNodeRef.current = node
    bodyWidthRef(node)
    if (node) node.addEventListener('touchmove', nativeTouchMove, { passive: false })
  }, [bodyWidthRef, nativeTouchMove])
  const [viewedUserId, setViewedUserId] = useState(() => { const u = searchParams.get('user'); return u ? Number(u) : null })
  const [viewedUserName, setViewedUserName] = useState(null)
  const initialModeSet = useRef(false)
  const [showUnlockConfirm, setShowUnlockConfirm] = useState(false)
  const [showResetConfirm, setShowResetConfirm] = useState(false)
  const [resetToast, setResetToast] = useState(null)
  const [showDefaultPicksBanner, setShowDefaultPicksBanner] = useState(false)
  const resetToastKeyRef = useRef(0)
  const resetToastTimerRef = useRef(null)
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
            applyPicks(newPicks)
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
    // Column widths come from the view components themselves — see the note on
    // the fit calc below for why these must not be re-typed as literals here.
    const anyScores = data.matches.some(m => (m.scores?.length > 0) || m.live_scores != null)
    const colUnit = viewMode === 'combined'
      ? CV_COL_W + CV_COL_GAP
      : (anyScores ? BV_COL_W_SCORES : BV_COL_W) + BV_COL_GAP
    const needed4Main = 4 * colUnit + 16 // draw-main width needed to fit 4 full rounds
    const projMainIfExpanded = bodyWidth - expandedSidebarW.current
    setSidebarCollapsed(projMainIfExpanded < needed4Main)
  }, [sidebarManual, bodyWidth, data, viewMode])

  // Resume auto behaviour when navigating to a different tournament
  useEffect(() => { setSidebarManual(false) }, [id])
  // React Router reuses this component across /tournaments/:id navigations
  // (no remount), so the ref latch below must be reset per-tournament or a
  // draw visited earlier in the session poisons every draw visited after it.
  useEffect(() => { autoInitShownRef.current = false }, [id])

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

  // ── Unpicked matches scrolled off the top/bottom of the round on screen ───
  // The round-nav buttons cover the horizontal case (an unpicked match in a
  // round that's been paged away). This is the vertical one: a 128-draw column
  // is many screens tall on a phone, so a match still waiting for a pick can
  // sit above or below the fold with nothing on screen saying it's there.
  //
  // Measured from the DOM rather than recomputed from bracket geometry. Both
  // views already mark these boxes with a class, the class encodes every rule
  // about whether a pick is actually possible (locked, viewing someone else,
  // both opponents known), and getBoundingClientRect reads through
  // CombinedView's transform:scale for free. Re-measuring is driven by
  // observers instead of a dependency list because the inputs that matter —
  // a pick being made, a page turn, the header collapsing — all show up as a
  // mutation, a resize, or a scroll on this subtree.
  const [pickNav, setPickNav] = useState(null)   // { above, below, top, bottom, cx }
  useLayoutEffect(() => {
    let raf = 0
    const measure = () => {
      raf = 0
      const body = bodyNodeRef.current
      const sc = body?.querySelector('.cv-scroll, .bracket-scroll')
      scrollerRef.current = sc ?? null
      if (!body || !sc) { setPickNav(prev => (prev ? null : prev)); return }

      const sr = sc.getBoundingClientRect()
      const br = body.getBoundingClientRect()
      let above = 0, below = 0
      for (const el of sc.querySelectorAll(MISSING_PICK_SEL)) {
        const r = el.getBoundingClientRect()
        if (r.height === 0) continue
        // Fully past the edge only — a match half in view is visible enough
        // to act on, and flagging it would leave the arrow permanently up.
        if (r.bottom <= sr.top + EDGE_SLACK) above++
        else if (r.top >= sr.bottom - EDGE_SLACK) below++
      }

      const next = (above || below)
        ? { above, below, top: sr.top - br.top, bottom: sr.bottom - br.top, cx: sr.left - br.left + sr.width / 2 }
        : null
      setPickNav(prev => {
        if (!prev && !next) return prev
        if (prev && next && prev.above === next.above && prev.below === next.below
            && Math.abs(prev.top - next.top) < 0.5 && Math.abs(prev.bottom - next.bottom) < 0.5
            && Math.abs(prev.cx - next.cx) < 0.5) return prev
        return next
      })
    }
    const schedule = () => { if (!raf) raf = requestAnimationFrame(measure) }

    measure()
    const onScroll = (e) => {
      const el = e.target
      if (el instanceof HTMLElement && el.matches?.('.cv-scroll, .bracket-scroll')) schedule()
    }
    document.addEventListener('scroll', onScroll, { capture: true, passive: true })
    const body = bodyNodeRef.current
    const ro = new ResizeObserver(schedule)
    const mo = new MutationObserver(schedule)
    if (body) {
      ro.observe(body)
      mo.observe(body, { subtree: true, childList: true, attributes: true, attributeFilter: ['class'] })
    }
    return () => {
      document.removeEventListener('scroll', onScroll, { capture: true })
      ro.disconnect()
      mo.disconnect()
      if (raf) cancelAnimationFrame(raf)
    }
  }, [data, viewMode, id])

  // Bring the nearest off-screen unpicked match into the middle of the view.
  const scrollToMissingPick = (dir) => {
    const sc = scrollerRef.current
    if (!sc) return
    const sr = sc.getBoundingClientRect()
    let best = null
    for (const el of sc.querySelectorAll(MISSING_PICK_SEL)) {
      const r = el.getBoundingClientRect()
      if (r.height === 0) continue
      const off = dir < 0 ? r.bottom <= sr.top + EDGE_SLACK : r.top >= sr.bottom - EDGE_SLACK
      if (!off) continue
      // Nearest first: the last one above, or the first one below.
      if (!best || (dir < 0 ? r.top > best.top : r.top < best.top)) best = r
    }
    if (!best) return
    sc.scrollBy({
      top: best.top - sr.top - Math.max(0, (sr.height - best.height) / 2),
      behavior: 'smooth',
    })
  }

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

  const applyPicks = (newPicks) => {
    setPicks(newPicks)
    if (user) saveMutation.mutate(newPicks)
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

  const handleResetSelections = () => {
    const newPicks = computeAutoPicks() ?? {}
    const filled = Object.values(newPicks).filter(v => v != null).length
    applyPicks(newPicks)
    setShowResetConfirm(false)
    resetToastKeyRef.current += 1
    setResetToast({ key: resetToastKeyRef.current, msg: `${filled} selection${filled !== 1 ? 's' : ''} reset to higher-ranked picks` })
    if (resetToastTimerRef.current) clearTimeout(resetToastTimerRef.current)
    resetToastTimerRef.current = setTimeout(() => setResetToast(null), 3500)
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

  }

  // Admin making picks on behalf of another user
  const handlePickForOther = (matchId, playerId) => {
    const newPicks = computeNextPicks(otherPicks, matchId, playerId)
    setOtherPicks(newPicks)
    saveOtherMutation.mutate(newPicks)
  }

  const everHadPicksRef = useRef(false)

  // ── Prev/next draw of the same status ──────────────────────────────────
  // Shares the ['tournaments'] cache with the dashboard, so this is normally
  // free. Every hook here must stay ABOVE the isLoading guard below (React
  // error #310), hence the optional chaining on data.
  const { data: allDraws } = useQuery({
    queryKey: ['tournaments'],
    queryFn: listTournaments,
    staleTime: 5 * 60 * 1000,
  })
  const siblingDraws = useMemo(() => {
    const status = data?.tournament?.status
    if (!allDraws || !status) return []
    return allDraws
      .filter(d => d.status === status)
      .sort((a, b) =>
        (a.start_date || '').localeCompare(b.start_date || '') ||
        (a.name || '').localeCompare(b.name || '') ||
        a.id - b.id
      )
  }, [allDraws, data?.tournament?.status])

  const siblingIdx = siblingDraws.findIndex(d => d.id === Number(id))
  const stepDraw = (delta) => {
    if (siblingDraws.length < 2 || siblingIdx < 0) return null
    return siblingDraws[(siblingIdx + delta + siblingDraws.length) % siblingDraws.length]
  }
  const prevDraw = stepDraw(-1)
  const nextDraw = stepDraw(1)
  const drawNavTitle = (d) => d
    ? `${d.name} — ${d.gender === 'M' ? 'ATP' : 'WTA'}${categoryShort(d.category) ? ' ' + categoryShort(d.category) : ''}`
    : 'No other draws of this type'

  if (isLoading) return <div className="page-loading">Loading draw…</div>
  if (error) return <div className="page-error">Failed to load draw.</div>

  const { tournament, matches, draw_entries: players } = data
  // Server truth, not a second derivation. draw_lock_state() decides this once
  // for the write path, this endpoint and the client — the three disagreeing is
  // the failure that matters (a bracket that looks editable and 403s).
  const locked = data.draw_locked ?? (tournament.is_locked && !tournament.selections_unlocked)
  // Matches under way while the bracket as a whole is still open.
  const lockedMatchIds = useMemo(
    () => new Set((data.matches || []).filter(m => m.locked).map(m => m.id)),
    [data.matches]
  )
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
  // Combined: 324, mirroring CombinedView's COL_W(260) + COL_GAP(64). Live:
  // mirrors BracketView's COL_W_SCORES(300)/COL_W(252) + its own COL_GAP(24),
  // depending on whether any match in the draw already carries score data.
  // Every width below is imported from the component that actually renders it.
  // These were once local literals copied from those components, and they went
  // stale the moment the feeder gap changed: the page then computed the fit and
  // the zoom against columns wider than the ones on screen, so it shrank the
  // draw further than it needed to and dropped columns sooner than it had to.
  const COL_GAP_PX = BV_COL_GAP // credited back for the last column's missing trailing gap
  const anyScores = matches.some(m => (m.scores?.length > 0) || m.live_scores != null)
  const colUnit = viewMode === 'combined'
    ? CV_COL_W + CV_COL_GAP
    : (anyScores ? BV_COL_W_SCORES : BV_COL_W) + BV_COL_GAP
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
  const COMPACT_COL_W = CV_COMPACT_COL_W
  const COMPACT_GAP = CV_COL_GAP
  const RIGHT_BTN_MARGIN = 3 // the right button's own distance from the body's right edge
  const H2H_GAP = 3          // requested clearance between the trailing H2H chip and the button
  const drawLeftPad = NAV_INSET + 4
  // TRAILING_W mirrors CombinedView's own TRAILING_W (H2H_X + half the H2H
  // chip's rotated visual width): credit the trailing stub only for the H2H
  // chip itself, not a full COMPACT_GAP — the rest of that connector line is
  // decorative and is meant to overflow off the viewport edge once zoomed
  // in, not reserve dead space that would otherwise separate the H2H chip
  // from the right button.
  const TRAILING_W = CV_H2H_X + 9
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

  // ── Swipe-to-page (touch only) ──────────────────────────────────────────
  // Touch events only fire on touch devices, so this is inherently mobile-only
  // — no viewport check needed. The sideways drag can't fight native scrolling
  // because .draw-main--swipe (applied while showPager) restricts touch panning
  // to the vertical axis; see that rule for why the draw has horizontal slack
  // to steal the gesture in the first place.
  const SWIPE_MIN_PX = 45      // ignore taps and small drags (e.g. picking a player)
  const SWIPE_H_RATIO = 1.5    // must be clearly horizontal, not a vertical scroll
  // Axis is decided (and, if horizontal, the native pan cancelled) THIS early,
  // because the browser starts panning after only a few px — waiting until
  // SWIPE_MIN_PX to call preventDefault let the draw visibly slide and snap
  // back before the swipe was ever recognised. Paging still waits for the
  // full SWIPE_MIN_PX, so a short drag cancels harmlessly instead of paging.
  const SWIPE_AXIS_LOCK_PX = 8
  const pageBy = (delta) => {
    if (delta === 0) return
    setWindowStart(Math.min(Math.max(windowPos + delta, 0), maxWindowStart))
  }
  const onDrawTouchStart = (e) => {
    if (!showPager || e.touches.length !== 1) { swipeRef.current = null; return }
    // The sidebar is inside .draw-body too; leave its own gestures alone.
    if (e.target?.closest?.('.draw-sidebar')) { swipeRef.current = null; return }
    // No "defer to native horizontal scrolling" check here: whenever paging is
    // available, .draw-body--swipe pins touch-action to the vertical axis, so
    // there IS no native horizontal pan to defer to. Checking for one anyway
    // would create a dead zone — a drag that neither pages nor scrolls.
    const t = e.touches[0]
    swipeRef.current = { x: t.clientX, y: t.clientY, axis: null, fired: false }
  }
  const onDrawTouchMove = (e) => {
    const s = swipeRef.current
    if (!s || e.touches.length !== 1) return
    const t = e.touches[0]
    const dx = t.clientX - s.x
    const dy = t.clientY - s.y

    // Decide the axis once, as soon as the finger has moved enough to tell.
    if (s.axis === null) {
      if (Math.max(Math.abs(dx), Math.abs(dy)) < SWIPE_AXIS_LOCK_PX) return
      s.axis = Math.abs(dx) > Math.abs(dy) * SWIPE_H_RATIO ? 'h' : 'v'
    }
    // Vertical gesture — hands off, let it scroll normally.
    if (s.axis !== 'h') return

    // Horizontal gesture: this one is ours for its whole duration. Cancelling
    // every move (not just the one that pages) is what actually keeps the draw
    // still — belt-and-braces with touch-action, and only possible because
    // this runs from a non-passive listener.
    if (e.cancelable) e.preventDefault()

    // `fired` caps it at one round per gesture — without it a long drag would
    // keep re-triggering on every touchmove and skip several rounds at once.
    if (s.fired || Math.abs(dx) < SWIPE_MIN_PX) return
    s.fired = true
    // Content follows the finger: dragging left pulls later rounds into view.
    pageBy(dx < 0 ? 1 : -1)
  }
  const onDrawTouchEnd = () => { swipeRef.current = null }
  // Point the native listener at this render's closure (see swipeMoveRef).
  swipeMoveRef.current = onDrawTouchMove

  // Off-screen unpicked matches: a match with no prediction can be paged out
  // of view, with nothing on screen hinting it's still there. Flag whichever
  // edge round-nav button leads toward it so it isn't missed.
  let missingPickLeft = false
  let missingPickRight = false
  if (user && !viewingOther) {
    const roundIndexOf = {}
    roundNumbers.forEach((rn, i) => { roundIndexOf[rn] = i })
    for (const m of matches) {
      if (m.is_bye || activePicks[m.id] != null) continue
      const colIdx = roundIndexOf[m.round_number]
      if (colIdx == null) continue
      if (colIdx < windowPos) missingPickLeft = true
      else if (colIdx >= windowPos + DRAW_WINDOW) missingPickRight = true
    }
  }

  // Viewport so narrow that only 1–2 rounds fit → keep the sub-header hidden
  // at all times (vertical space is at a premium; the edge round-nav buttons
  // still provide paging). Width-based (windowFit), not DRAW_WINDOW, so a
  // small draw on a wide screen doesn't hide it.
  const headerForcedHidden = windowFit <= 2

  // Page-position dots: one per place the round window can sit, so the count
  // is exactly how many swipes' worth of rounds exist and the filled dot is
  // where you are. Shared by two hosts: the minimal header pager, and — when
  // headerForcedHidden collapses that whole header away (the phone case) — the
  // standalone strip above .draw-body, so the indicator survives there too.
  const pageDots = (
    <div className="bracket-page-dots" role="tablist" aria-label="Round pages">
      {Array.from({ length: maxWindowStart + 1 }, (_, i) => (
        <button
          key={i}
          role="tab"
          className={clsx('bracket-page-dot', { active: i === windowPos })}
          onClick={() => setWindowStart(i)}
          aria-selected={i === windowPos}
          aria-label={`Show ${pagerColumns[i].title}`}
          title={pagerColumns[i].title}
        />
      ))}
    </div>
  )

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
  const canReset = user && !locked && !viewingOther && pickedCount > 0

  // Header helpers
  const catShort = tournament.category ? tournament.category.replace(/^(ATP|WTA)\s+/, '') : ''
  const tourLabel = `${tournament.gender === 'M' ? 'ATP' : 'WTA'}${catShort ? ' ' + catShort : ''}`
  // Same value in the site's pill form ("ATP 500", "WTA GS") for the phone
  // dots bar, which has no room for "ATP Grand Slam".
  const isATP = tournament.gender === 'M'
  const catTier = categoryShort(tournament.category)
  const catPill = `${isATP ? 'ATP' : 'WTA'}${catTier ? ' ' + catTier : ''}`
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
          {/* Both arrows sit together at the left, ahead of the draw info, so
              neither moves as you page through draws of different name length. */}
          <div className="draw-sibling-navs">
            <button
              className={clsx('draw-sibling-nav', { 'draw-sibling-nav--off': !prevDraw })}
              onClick={() => prevDraw && navigate(`/tournaments/${prevDraw.id}`)}
              aria-disabled={!prevDraw}
              title={drawNavTitle(prevDraw)}
              aria-label={prevDraw ? `Previous draw: ${drawNavTitle(prevDraw)}` : 'No other draws of this type'}
            >
              ‹
            </button>
            <button
              className={clsx('draw-sibling-nav', { 'draw-sibling-nav--off': !nextDraw })}
              onClick={() => nextDraw && navigate(`/tournaments/${nextDraw.id}`)}
              aria-disabled={!nextDraw}
              title={drawNavTitle(nextDraw)}
              aria-label={nextDraw ? `Next draw: ${drawNavTitle(nextDraw)}` : 'No other draws of this type'}
            >
              ›
            </button>
          </div>
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
            (Picks). BracketView's dedicated picks-only mode ('picks') is
            still supported by the code (see picksOwner/lossRound logic
            elsewhere in this file and in BracketView) but unreachable from
            this switcher, which only offers the two user-facing choices. */}
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
              {pageDots}
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
          <div className="draw-header-actions">
          {/* Per-draw override of the site-wide locking rule. Admin-only, and
              sited here rather than in the admin area because this is where the
              consequence is visible — you can see immediately which matches the
              change freezes. */}
          {user?.is_admin && (
            <select
              className="lock-mode-select"
              title="How predictions lock for this draw"
              value={data.lock_mode || 'draw_start'}
              onChange={async (e) => {
                const { default: client } = await import('../api/client')
                await client.put(`/admin/draws/${tournament.id}/pick-lock-mode`, { mode: e.target.value })
                qc.invalidateQueries({ queryKey: ['draw', id] })
              }}
            >
              <option value="draw_start">🔒 Locks at first ball</option>
              <option value="r1_progressive">🔒 Locks match by match</option>
            </select>
          )}
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
          {/* Saved-picks pill sits directly on top of Reset Selections, both
              stretched to one shared width (see .draw-picks-stack). */}
          {(showPicksBadge || canReset) && (
            <div className="draw-picks-stack">
              {showPicksBadge && (
                <span className={`saved-badge${pickedCount < totalPredictable ? ' saved-badge--incomplete' : ''}`}>
                  {pickedCount < totalPredictable
                    ? `⚠ ${pickedCount}/${totalPredictable} picks saved — complete all picks to COMPETE`
                    : `✓ ${pickedCount}/${totalPredictable} picks saved`}
                </span>
              )}
              {canReset && (
                <button
                  className="btn-reset-selections"
                  onClick={() => setShowResetConfirm(true)}
                >
                  Reset Selections
                </button>
              )}
            </div>
          )}
          {!user && (
            <Link to="/login" className="btn-primary">Log in to make picks</Link>
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


      {showResetConfirm && (() => {
        const { total, upsets } = countPicksAndUpsets()
        return (
          <div className="auto-populate-overlay" onClick={() => setShowResetConfirm(false)}>
            <div className="auto-populate-modal" onClick={e => e.stopPropagation()}>
              <h3 className="auto-populate-modal-title">Reset all selections?</h3>
              <p className="auto-populate-modal-body">
                This will reset {total} match selection{total !== 1 ? 's' : ''} so the higher-ranked player wins every match
                {upsets > 0 ? `, overwriting ${upsets} upset pick${upsets !== 1 ? 's' : ''}` : ''}.
              </p>
              <div className="auto-populate-modal-actions">
                <button className="btn-secondary" onClick={() => setShowResetConfirm(false)}>
                  Cancel
                </button>
                <button className="btn-danger" onClick={handleResetSelections}>
                  Reset selections
                </button>
              </div>
            </div>
          </div>
        )
      })()}

      {resetToast && (
        <div key={resetToast.key} className="reset-toast">{resetToast.msg}</div>
      )}

      {showDefaultPicksBanner && (
        <div className="default-picks-modal-overlay">
          <div className="default-picks-modal">
            <span className="default-picks-modal-icon">✓</span>
            <p className="default-picks-modal-text">
              Your default predictions have been made, using the higher ranked player for the win.
              You <strong>MUST</strong> select at least one <strong>UPSET</strong> to compete in this draw!
            </p>
            <button
              className="btn-primary"
              onClick={() => setShowDefaultPicksBanner(false)}
            >
              Got it
            </button>
          </div>
        </div>
      )}

      {/* Phone case: headerForcedHidden collapses the whole draw-header (pager
          included) to reclaim vertical space, so the page indicator gets its
          own slim always-visible strip here instead. No arrows — the big edge
          round-nav buttons already float over the draw, and you can swipe. */}
      {showPager && headerForcedHidden && (
        <div className="draw-page-dots-bar">
          <span className="draw-dots-bar-name" title={tournament.name}>{tournament.name}</span>
          {pageDots}
          <span className={clsx('draw-dots-bar-cat', isATP ? 'draw-dots-bar-cat--atp' : 'draw-dots-bar-cat--wta')}>
            {catPill}
          </span>
        </div>
      )}

      {/* Swipe is bound here, not on .draw-main, so gestures that start on the
          floating round-nav edge buttons count too — those are absolutely
          positioned in .draw-body and sit OUTSIDE .draw-main, so an edge swipe
          (a natural way to page) previously escaped both the handler and the
          touch-action restriction. touchmove is attached natively inside
          bodyRef; only these three go through React. */}
      <div
        className={clsx('draw-body', { 'draw-body--swipe': showPager })}
        ref={bodyRef}
        onTouchStart={onDrawTouchStart}
        onTouchEnd={onDrawTouchEnd}
        onTouchCancel={onDrawTouchEnd}
      >
        <DrawSidebar
          tournamentId={Number(id)}
          tournament={tournament}
          selectedUserId={viewedUserId}
          defaultLeagueId={searchParams.get('league') ? Number(searchParams.get('league')) : undefined}
          onLeagueChange={setActiveLeagueId}
          collapsed={sidebarCollapsed}
          overlay={compactDraw}
          onToggleCollapsed={() => { setSidebarManual(true); setSidebarCollapsed(c => !c) }}
          onSelectUser={(uid, uname) => {
            setViewedUserId(uid)
            setViewedUserName(uname ?? null)
            // Live Draw shows no picks at all, so jump back to Picks (Combined)
            // when a user is selected — otherwise the selection would appear
            // to do nothing.
            if (uid != null) setViewMode('combined')
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
              lockedMatchIds={lockedMatchIds}
              windowStart={windowPos}
              windowSize={DRAW_WINDOW}
              labelsHidden={headerHidden}
              insetLeft={drawInsetLeft}
              compact={compactDraw}
              zoom={drawZoom}
              leagueId={activeLeagueId}
            />
          ) : (
            <BracketView
              tournament={tournament}
              matches={matches}
              players={players}
              picks={user ? activePicks : {}}
              onPick={viewingOther ? (canEditOther ? handlePickForOther : () => {}) : handlePick}
              locked={!user || locked || (viewingOther && !canEditOther)}
              lockedMatchIds={lockedMatchIds}
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
            className={clsx('round-nav round-nav--left', { 'round-nav--missing-pick': missingPickLeft })}
            style={{ left: sidebarCollapsed ? 3 : Math.max(3, bodyWidth - mainWidth + 3) }}
            onClick={() => setWindowStart(windowPos - 1)}
            title={missingPickLeft
              ? `Show ${pagerColumns[windowPos - 1].title} — missing pick(s)`
              : `Show ${pagerColumns[windowPos - 1].title}`}
            aria-label={`Show ${pagerColumns[windowPos - 1].title}`}
          >
            <span className="round-nav-label round-nav-label--sizer" aria-hidden="true">CHAMP</span>
            <span className="round-nav-label">{pagerColumns[windowPos - 1].nav}</span>
          </button>
        )}
        {showPager && windowPos < maxWindowStart && (compactDraw || rightNavX != null) && (
          <button
            ref={navBtnRightRef}
            className={clsx('round-nav round-nav--right', { 'round-nav--missing-pick': missingPickRight })}
            style={compactDraw ? { right: 3, left: 'auto' } : { left: Math.min(rightNavX + 6, bodyWidth - 30) }}
            onClick={() => setWindowStart(windowPos + 1)}
            title={missingPickRight
              ? `Show ${pagerColumns[windowPos + DRAW_WINDOW].title} — missing pick(s)`
              : `Show ${pagerColumns[windowPos + DRAW_WINDOW].title}`}
            aria-label={`Show ${pagerColumns[windowPos + DRAW_WINDOW].title}`}
          >
            <span className="round-nav-label round-nav-label--sizer" aria-hidden="true">CHAMP</span>
            <span className="round-nav-label">{pagerColumns[windowPos + DRAW_WINDOW].nav}</span>
          </button>
        )}

        {/* Vertical counterpart to the round-nav buttons above: unpicked
            matches in the round on screen that are scrolled out of sight.
            Pinned to the scroller's own top/bottom edge (measured, since the
            sidebar and collapsing header both move it) and tapping jumps to
            the nearest one. */}
        {pickNav?.above > 0 && (
          <button
            className="pick-nav pick-nav--up"
            style={{ top: pickNav.top + 6, left: pickNav.cx }}
            onClick={() => scrollToMissingPick(-1)}
            title={`${pickNav.above} match${pickNav.above > 1 ? 'es' : ''} above still needs a pick`}
            aria-label={`Scroll up to ${pickNav.above} unpicked match${pickNav.above > 1 ? 'es' : ''}`}
          >
            <span className="pick-nav-arrow" aria-hidden="true">▲</span>
            <span className="pick-nav-count">{pickNav.above}</span>
          </button>
        )}
        {pickNav?.below > 0 && (
          <button
            className="pick-nav pick-nav--down"
            style={{ top: pickNav.bottom - 6, left: pickNav.cx }}
            onClick={() => scrollToMissingPick(1)}
            title={`${pickNav.below} match${pickNav.below > 1 ? 'es' : ''} below still needs a pick`}
            aria-label={`Scroll down to ${pickNav.below} unpicked match${pickNav.below > 1 ? 'es' : ''}`}
          >
            <span className="pick-nav-count">{pickNav.below}</span>
            <span className="pick-nav-arrow" aria-hidden="true">▼</span>
          </button>
        )}
      </div>
    </div>
  )
}

