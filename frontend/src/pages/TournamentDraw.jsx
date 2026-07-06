/**
 * TournamentDraw — shows the bracket for one tournament.
 * Logged-in users can make / update predictions until the lock time.
 */
import { useState, useEffect, useRef } from 'react'
import { useParams, Link, useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { getDraw, refreshDraw, toggleUnlockSelections } from '../api/tournaments'
import { getPredictions, savePredictions } from '../api/predictions'
import { useAuth } from '../store/auth'
import BracketView from '../components/BracketView'
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
  const [viewMode, setViewMode] = useState('live')
  const [windowStart, setWindowStart] = useState(0) // left-most visible round (pager)
  const [viewedUserId, setViewedUserId] = useState(() => { const u = searchParams.get('user'); return u ? Number(u) : null })
  const [viewedUserName, setViewedUserName] = useState(null)
  const initialModeSet = useRef(false)
  const [celebrating, setCelebrating] = useState(false)
  const [showUnlockConfirm, setShowUnlockConfirm] = useState(false)
  const [pendingAutoPicks, setPendingAutoPicks] = useState(null)
  const [showClearConfirm, setShowClearConfirm] = useState(false)
  const [clearToast, setClearToast] = useState(null)
  const [showAutoInitPrompt, setShowAutoInitPrompt] = useState(false)
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
          setShowAutoInitPrompt(true)
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
  useEffect(() => {
    if (initialModeSet.current || savedPreds === undefined || !data) return
    initialModeSet.current = true
    if (searchParams.get('user') || data.tournament.status === 'open' || savedPreds.some(p => p.predicted_winner_id != null)) setViewMode('picks')
  }, [savedPreds, data])

  // Auto-switch to 'live' when the draw locks mid-session and the user has no picks of their own
  const _isLockedNow = !!(data?.tournament?.is_locked && !data?.tournament?.selections_unlocked)
  const _userHasPicks = savedPreds ? savedPreds.some(p => p.predicted_winner_id != null) : false
  useEffect(() => {
    if (user && _isLockedNow && !_userHasPicks && viewMode === 'picks' && !viewingOther) {
      setViewMode('live')
    }
  }, [_isLockedNow, _userHasPicks, viewMode, viewingOther, user])

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
      const total = data.matches.filter(m => !m.is_bye).length
      const filled = Object.values(newPicks).filter(v => v != null).length
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
      const total = data.matches.filter(m => !m.is_bye).length
      const filled = Object.values(newPicks).filter(v => v != null).length
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
  const pickedCount = Object.values(picks).filter(v => v != null).length
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
  const DRAW_WINDOW = 4
  const roundNumbers = [...new Set(matches.map(m => m.round_number))].sort((a, b) => a - b)
  const maxWindowStart = Math.max(0, roundNumbers.length - DRAW_WINDOW)
  const windowPos = Math.min(windowStart, maxWindowStart)
  const showPager = roundNumbers.length > DRAW_WINDOW
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
  // Pixel geometry for the round dots + the shaded window highlight behind them.
  const DOT_SIZE = 42, DOT_GAP = 10, DOT_PAD = 6
  const DOT_STEP = DOT_SIZE + DOT_GAP

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
      <div className="draw-header">
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
          <div className="draw-mode-buttons">
            <button
              className={clsx('draw-mode-btn', { active: viewMode === 'picks' })}
              onClick={() => setViewMode('picks')}
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
        </div>
        <div className="draw-header-center">
          {showPager && (
            <div className="bracket-pager">
              <button
                className={clsx('bracket-pager-arrow', { hidden: windowPos === 0 })}
                onClick={() => setWindowStart(windowPos - 1)}
                aria-label="Earlier rounds"
              >
                ‹
              </button>
              <div className="bracket-dots" style={{ padding: DOT_PAD }}>
                <span
                  className="bracket-dots-highlight"
                  aria-hidden="true"
                  style={{
                    left: windowPos * DOT_STEP,
                    width: DRAW_WINDOW * DOT_SIZE + (DRAW_WINDOW - 1) * DOT_GAP + 2 * DOT_PAD,
                  }}
                />
                {roundNumbers.map((rn, i) => {
                  const inWindow = i >= windowPos && i < windowPos + DRAW_WINDOW
                  return (
                    <button
                      key={rn}
                      className={clsx('bracket-dot', { 'in-window': inWindow })}
                      style={{ width: DOT_SIZE, height: DOT_SIZE }}
                      onClick={() => setWindowStart(Math.min(i, maxWindowStart))}
                      aria-label={roundNameByNum[rn] || `Round ${rn}`}
                      title={roundNameByNum[rn] || `Round ${rn}`}
                    >
                      {dotLabel(rn, i)}
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
        <div className="draw-header-right">
          <div className="draw-picks-zone">
            {user && !locked && !viewingOther && viewMode === 'picks' && (
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

      {showAutoInitPrompt && (
        <div className="auto-populate-overlay" onClick={() => setShowAutoInitPrompt(false)}>
          <div className="auto-populate-modal" onClick={e => e.stopPropagation()}>
            <h3 className="auto-populate-modal-title">Initialize your predictions?</h3>
            <p className="auto-populate-modal-body">
              Would you like to initialize your predictions by auto-selecting the higher-ranked player for every match? If so, you could then proceed by fine-tuning predictions by hand-picking your desired upsets.
            </p>
            <div className="auto-populate-modal-actions">
              <button
                className="btn-primary"
                onClick={() => {
                  const newPicks = computeAutoPicks()
                  if (newPicks) applyPicksAndCelebrate(newPicks)
                  setShowAutoInitPrompt(false)
                }}
              >
                Yes, Auto-Select
              </button>
              <button
                className="btn-secondary"
                onClick={() => setShowAutoInitPrompt(false)}
              >
                No thanks
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

      <div className="draw-body">
        <DrawSidebar
          tournamentId={Number(id)}
          tournament={tournament}
          selectedUserId={viewedUserId}
          defaultLeagueId={searchParams.get('league') ? Number(searchParams.get('league')) : undefined}
          onSelectUser={(uid, uname) => {
            setViewedUserId(uid)
            setViewedUserName(uname ?? null)
            if (uid != null) setViewMode('picks')
          }}
        />

        <div className="draw-main">
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
          />
        </div>
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
