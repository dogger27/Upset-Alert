/**
 * ScoreHistoryPopup — a match's score with a slider through its history.
 *
 * Opened by clicking a match on the draw page once the draw is no longer open
 * for picking. Each slider position is one CHANGE of the score — a point, in
 * practice — rendered through MatchScoreCard, the same component the schedule
 * page draws every score with, so the two surfaces cannot drift apart.
 *
 * Fully right is not a history position: it is "now". For a live match that is
 * the current snapshot off the draw payload, which the page's SSE nudge keeps
 * refetching, so the popup follows the score without any timer of its own. For
 * a completed match it is the final score — matches.scores_json, the record,
 * which the last live snapshot can miss the closing point of.
 *
 * Modal skeleton follows PredictorsPopup; the slider follows LeagueDetail's
 * timeline scrubber, including its "fully right = null = live" convention.
 */
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import { getMatchScoreHistory } from '../api/tournaments'
import MatchScoreCard from './MatchScoreCard'
import './ScoreHistoryPopup.css'

export default function ScoreHistoryPopup({ drawId, match, onClose }) {
  const { data } = useQuery({
    queryKey: ['score-history', drawId, match?.id],
    queryFn: () => getMatchScoreHistory(drawId, match.id),
    enabled: !!match?.id,
    staleTime: 15_000,
  })

  // null = fully right = follow live / show final. An index otherwise.
  const [pos, setPos] = useState(null)

  useEffect(() => {
    const root = document.documentElement
    root.classList.add('h2h-modal-open')
    return () => root.classList.remove('h2h-modal-open')
  }, [])
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  if (!match) return null

  const snapshots = data?.snapshots ?? []
  const max = snapshots.length            // rightmost notch = live/final
  const atEnd = pos == null || pos >= max
  const completed = match.winner != null || data?.status === 'completed'

  /* The row MatchScoreCard reads. History positions render as a live row at
     that moment; the end position renders exactly what the draw page holds
     now, so a running match keeps ticking while the popup is open. */
  const snap = atEnd ? null : snapshots[pos]
  const e = atEnd
    ? (completed
        ? { discipline: 'singles', status: 'completed',
            scores: data?.final ?? match.scores ?? null }
        : { discipline: 'singles', status: 'live',
            live_point: match.live_point ?? null,
            live_scores: match.live_scores ?? null,
            scores: match.scores ?? null })
    : { discipline: 'singles', status: 'live', live_point: snap,
        live_scores: null, scores: null }

  const players = [match.player1, match.player2]
    .map((p, i) => (p ? {
      side: i === 0 ? 'a' : 'b', position: 1,
      name: p.name, seed: p.seed, nationality: p.nationality,
    } : null))
    .filter(Boolean)
  const a = players.filter(p => p.side === 'a')
  const b = players.filter(p => p.side === 'b')

  const when = atEnd
    ? (completed ? 'Final' : 'Live')
    : (snap?.at
        ? new Date(snap.at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
        : `${pos + 1} / ${max}`)

  return createPortal(
    <div className="shp-backdrop" onClick={onClose}>
      <div className="shp-popup" onClick={e2 => e2.stopPropagation()} role="dialog" aria-modal="true">
        <div className="shp-header">
          <span className={`shp-when${atEnd && !completed ? ' shp-when--live' : ''}`}>{when}</span>
          <button className="shp-close" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="shp-card">
          <MatchScoreCard e={e} a={a} b={b} />
        </div>
        {max > 0 && (
          <div className="shp-scrub">
            <input
              type="range"
              min={0}
              max={max}
              value={atEnd ? max : pos}
              onChange={ev => {
                const v = Number(ev.target.value)
                // Fully right = null = follow live, the LeagueDetail convention.
                setPos(v >= max ? null : v)
              }}
              className="shp-range"
              style={{ '--fill-pct': `${((atEnd ? max : pos) / max) * 100}%` }}
              aria-label="Scrub through the match's score history"
            />
          </div>
        )}
      </div>
    </div>,
    document.body
  )
}
