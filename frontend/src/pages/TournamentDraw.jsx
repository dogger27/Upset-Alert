/**
 * TournamentDraw — shows the bracket for one tournament.
 * Logged-in users can make / update predictions until the lock time.
 */
import { useState, useEffect, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getDraw } from '../api/tournaments'
import { getPredictions, savePredictions } from '../api/predictions'
import { useAuth } from '../store/auth'
import BracketView from '../components/BracketView'
import './TournamentDraw.css'

export default function TournamentDraw() {
  const { id } = useParams()
  const { user } = useAuth()
  const qc = useQueryClient()

  const { data, isLoading, error } = useQuery({
    queryKey: ['draw', id],
    queryFn: () => getDraw(Number(id)),
  })

  const { data: savedPreds } = useQuery({
    queryKey: ['predictions', id],
    queryFn: () => getPredictions(Number(id)),
    enabled: !!user,
  })

  // Local picks state: {match_id: player_id}
  const [picks, setPicks] = useState({})
  // Matches whose composition changed since the pick was made — need user review
  const [stalePicks, setStalePicks] = useState(new Set())
  // Celebration state
  const [celebrating, setCelebrating] = useState(false)
  const celebrateTimerRef = useRef(null)

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

  const saveMutation = useMutation({
    mutationFn: (latestPicks) => savePredictions(Number(id), latestPicks),
    onSuccess: () => qc.invalidateQueries(['predictions', id]),
  })

  const handlePick = (matchId, playerId) => {
    const newPicks = { ...picks }
    const newStale = new Set(stalePicks)
    const oldPlayerId = newPicks[matchId]

    if (oldPlayerId != null && oldPlayerId !== playerId && data) {
      const byKey = {}
      for (const m of data.matches) byKey[`${m.round_number}:${m.match_number}`] = m
      let cur = data.matches.find(m => m.id === matchId)
      while (cur) {
        const next = byKey[`${cur.round_number + 1}:${Math.ceil(cur.match_number / 2)}`]
        if (!next) break
        if (newPicks[next.id] === oldPlayerId) {
          // Cascade-clear: old player can no longer reach this match
          newPicks[next.id] = null
          newStale.delete(next.id)
        } else if (newPicks[next.id] != null) {
          // Different player picked here — matchup has changed, flag for review
          newStale.add(next.id)
        }
        cur = next
      }
    }

    // Making a pick for a match resolves its stale status
    newStale.delete(matchId)

    newPicks[matchId] = playerId
    setPicks(newPicks)
    setStalePicks(newStale)
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

  const { tournament, matches, players } = data
  const locked = tournament.is_locked

  const pickedCount = Object.values(picks).filter(v => v != null).length
  const totalPredictable = matches.filter(m => !m.is_bye).length

  return (
    <div className="draw-page">
      <div className="draw-header">
        <div>
          <h1>{tournament.year} {tournament.name}</h1>
          <p className="muted">
            {tournament.start_date && (
              <>
                {new Date(tournament.start_date + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                {' · '}
              </>
            )}
            {tournament.gender === 'M' ? "Men's" : "Women's"} Singles ·{' '}
            {tournament.draw_size}-player draw · {tournament.num_rounds} rounds
            {tournament.surface && ` · ${tournament.surface}`}
          </p>
        </div>
        <div className="draw-header-actions">
          {locked ? (
            <span className="lock-badge">🔒 Predictions locked</span>
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
                  Closes {userLocal}
                </span>
              )
            })()
          )}
          {user && !locked && (
            <span className="saved-badge">
              {saveMutation.isPending ? '⏳ Saving…' : pickedCount > 0 ? `✓ ${pickedCount}/${totalPredictable} picks saved` : ''}
            </span>
          )}
          {!user && (
            <Link to="/login" className="btn-primary">Log in to make picks</Link>
          )}
        </div>
      </div>

      {saveMutation.isError && (
        <div className="error" style={{ padding: '0 1.5rem' }}>
          Failed to save: {saveMutation.error?.response?.data?.detail || 'Unknown error'}
        </div>
      )}

      {celebrating && <CelebrationOverlay />}

      <BracketView
        tournament={tournament}
        matches={matches}
        players={players}
        picks={user ? picks : {}}
        stalePicks={stalePicks}
        onPick={handlePick}
        locked={!user || locked}
      />
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
