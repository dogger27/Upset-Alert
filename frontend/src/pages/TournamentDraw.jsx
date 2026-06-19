/**
 * TournamentDraw — shows the bracket for one tournament.
 * Logged-in users can make / update predictions until the lock time.
 */
import { useState, useEffect, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
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
  const { user } = useAuth()
  const qc = useQueryClient()

  // All state declared first
  const [picks, setPicks] = useState({})
  const [viewMode, setViewMode] = useState('live')
  const [viewedUserId, setViewedUserId] = useState(null)
  const [viewedUserName, setViewedUserName] = useState(null)
  const initialModeSet = useRef(false)
  const [celebrating, setCelebrating] = useState(false)
  const [showUnlockConfirm, setShowUnlockConfirm] = useState(false)
  const celebrateTimerRef = useRef(null)

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
    }
  }, [savedPreds, data])

  // Set initial view mode once: 'picks' if user has picks, otherwise 'live'
  useEffect(() => {
    if (initialModeSet.current || savedPreds === undefined) return
    initialModeSet.current = true
    if (savedPreds.some(p => p.predicted_winner_id != null)) setViewMode('picks')
  }, [savedPreds])

  const saveMutation = useMutation({
    mutationFn: (latestPicks) => savePredictions(Number(id), latestPicks),
    onSuccess: () => qc.invalidateQueries(['predictions', id]),
  })

  const refreshMutation = useMutation({
    mutationFn: () => refreshDraw(Number(id)),
    onSuccess: () => qc.invalidateQueries(['draw', id]),
  })

  const unlockMutation = useMutation({
    mutationFn: () => toggleUnlockSelections(Number(id)),
    onSuccess: () => { qc.invalidateQueries(['draw', id]); setShowUnlockConfirm(false) },
  })

  const handlePick = (matchId, playerId) => {
    const newPicks = { ...picks }
    const oldPlayerId = newPicks[matchId]

    // Cascade-clear: if switching picks, clear downstream picks for the old player
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

  if (isLoading) return <div className="page-loading">Loading draw…</div>
  if (error) return <div className="page-error">Failed to load draw.</div>

  const { tournament, matches, draw_entries: players } = data
  const locked = tournament.is_locked && !tournament.selections_unlocked
  const picksOwner = viewMode === 'picks' ? (viewingOther ? viewedUserName : user?.username) ?? null : null

  // When viewing another user's picks, build their picks map from fetched predictions
  const viewedPicksMap = viewingOther && viewedPreds
    ? Object.fromEntries(viewedPreds.filter(p => p.predicted_winner_id != null).map(p => [p.match_id, p.predicted_winner_id]))
    : null

  const activePicks = viewingOther ? (viewedPicksMap ?? {}) : picks
  const pickedCount = Object.values(picks).filter(v => v != null).length
  const totalPredictable = matches.filter(m => !m.is_bye).length

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
          <div className="draw-title-row">
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
          </div>
          <div className="draw-meta-row">
            <span className="draw-meta-left">
              {[tournament.city, surface].filter(Boolean).join(' · ')}
            </span>
          </div>
          {tournament.latest_result_at && (
            <p className="draw-last-modified">Latest result: {fmtModified(tournament.latest_result_at)}</p>
          )}
        </div>
        <div className="draw-header-center">
          {tournament.start_date && (
            <span className="draw-title-dates">{fmtDateRange(tournament.start_date, tournament.end_date)}</span>
          )}
          <div className="draw-mode-buttons">
            <button
              className={clsx('draw-mode-btn', { active: viewMode === 'picks' })}
              onClick={() => setViewMode('picks')}
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
          {user?.is_admin && (
            <button
              className="btn-admin-refresh"
              onClick={() => refreshMutation.mutate()}
              disabled={refreshMutation.isPending}
            >
              {refreshMutation.isPending ? '⏳ Updating…' : '↻ Update Draw'}
            </button>
          )}
          {user && !locked && (
            <span className="saved-badge">
              {saveMutation.isPending ? '⏳ Saving…' : pickedCount > 0 ? `✓ ${pickedCount}/${totalPredictable} picks saved` : ''}
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

      {saveMutation.isError && (
        <div className="error" style={{ padding: '0 1.5rem' }}>
          Failed to save: {saveMutation.error?.response?.data?.detail || 'Unknown error'}
        </div>
      )}

      {celebrating && <CelebrationOverlay />}

      <div className="draw-body">
        <DrawSidebar
          tournamentId={Number(id)}
          tournament={tournament}
          selectedUserId={viewedUserId}
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
            onPick={viewingOther ? () => {} : handlePick}
            locked={!user || locked || viewingOther}
            mode={viewMode}
            picksOwner={picksOwner}
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
