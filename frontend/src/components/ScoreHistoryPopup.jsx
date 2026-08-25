/**
 * ScoreHistoryPopup — a match's score with a slider through its history.
 *
 * Opened by clicking any match on the draw page that has started or finished,
 * whether or not the draw is still open for picking — a started match's pick
 * is locked by then, so the click is free to mean "show me the score".
 * Each slider position is one CHANGE of the score — a point, in
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
import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import { getMatchScoreHistory } from '../api/tournaments'
import MatchScoreCard from './MatchScoreCard'
import { timelineMarkers } from '../utils/scoreTimeline'
import './ScoreHistoryPopup.css'

/* Two callers, one popup. The draw page passes `match` (a bracket match);
   the schedule page passes `entry` (a schedule row, which already carries the
   exact shape MatchScoreCard renders — players with sides, discipline,
   live_point, scores). Normalised here rather than at the call sites so the
   two surfaces cannot drift. A schedule row without a mapped bracket match
   (doubles — their draws have no rows in `matches`) still opens: it shows
   the live/final card with no slider, because there is no history to scrub. */
export default function ScoreHistoryPopup({ drawId, match, entry, onClose }) {
  const histDrawId = entry ? entry.draw_id : drawId
  const histMatchId = entry ? entry.match_id : match?.id
  const { data } = useQuery({
    queryKey: ['score-history', histDrawId, histMatchId],
    queryFn: () => getMatchScoreHistory(histDrawId, histMatchId),
    enabled: !!histDrawId && !!histMatchId,
    staleTime: 15_000,
  })

  // null = fully right = follow live / show final. An index otherwise.
  const [pos, setPos] = useState(null)

  /* Breaks and set-ends, as coloured ticks on the track — the timeline as a
     map instead of a blind scrubber. Derived per snapshot pair in
     utils/scoreTimeline (a plain module, unit-tested under node); memoised
     because a live match re-renders this popup on every point. */
  const markers = useMemo(
    () => timelineMarkers(data?.snapshots ?? []), [data?.snapshots])

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

  if (!match && !entry) return null

  const snapshots = data?.snapshots ?? []
  const max = snapshots.length            // rightmost notch = live/final
  const atEnd = pos == null || pos >= max
  const completed = entry
    ? (entry.status === 'completed' || entry.winner_side != null)
    : (match.winner != null || data?.status === 'completed')

  /* The row MatchScoreCard reads. History positions render as a live row at
     that moment; the end position renders exactly what the draw page holds
     now, so a running match keeps ticking while the popup is open. */
  const snap = atEnd ? null : snapshots[pos]
  const discipline = entry?.discipline ?? 'singles'
  const e = atEnd
    ? (entry
        // The schedule row IS the card's shape — pass it through whole, so a
        // doubles final renders exactly as the schedule page renders it.
        ? entry
        : (completed
            ? { discipline, status: 'completed',
                scores: data?.final ?? match.scores ?? null }
            : { discipline, status: 'live',
                live_point: match.live_point ?? null,
                live_scores: match.live_scores ?? null,
                scores: match.scores ?? null }))
    : { discipline, status: 'live', live_point: snap,
        live_scores: null, scores: null }

  const players = entry
    ? entry.players || []
    : [match.player1, match.player2]
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
            {/* Ticks sit UNDER the input (z-index) and take no pointer events
                — the slider owns every touch, exactly as before. Positioned
                against the thumb's travel, not naive percent: the thumb is
                28px wide, so its centre runs [14px, 100%-14px]. */}
            {markers.map(m => (
              <span
                key={`${m.kind}${m.i}`}
                className={`shp-tick shp-tick--${m.kind}`}
                style={{ left: `calc(14px + (100% - 28px) * ${m.i / max})` }}
              />
            ))}
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
            {markers.length > 0 && (
              <div className="shp-legend">
                <span className="shp-legend-item">
                  <span className="shp-legend-box shp-tick--break" /> break
                </span>
                <span className="shp-legend-item">
                  <span className="shp-legend-box shp-tick--set" /> set
                </span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>,
    document.body
  )
}
