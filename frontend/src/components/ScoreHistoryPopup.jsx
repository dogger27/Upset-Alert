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
import { splitPlayerName } from '../utils/flags'
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

  /* EVERYTHING THE MEMO NEEDS IS DERIVED ABOVE THE EARLY RETURN, null-safe.
     The first version computed these after `if (!match && !entry) return`
     with the memo below them — a hook after a conditional return is React
     #310, the exact trap this codebase's own draw page documents. Hooks
     first, guards after, always. */
  const snapshots = data?.snapshots ?? []
  const max = snapshots.length            // rightmost notch = live/final
  const atEnd = pos == null || pos >= max
  const completed = entry
    ? (entry.status === 'completed' || entry.winner_side != null)
    : (match?.winner != null || data?.status === 'completed')

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
                scores: data?.final ?? match?.scores ?? null }
            : { discipline, status: 'live',
                live_point: match?.live_point ?? null,
                live_scores: match?.live_scores ?? null,
                scores: match?.scores ?? null }))
    : { discipline, status: 'live', live_point: snap,
        live_scores: null, scores: null }

  const players = entry
    ? entry.players || []
    : [match?.player1, match?.player2]
        .map((p, i) => (p ? {
          side: i === 0 ? 'a' : 'b', position: 1,
          name: p.name, seed: p.seed, nationality: p.nationality,
        } : null))
        .filter(Boolean)
  const a = players.filter(p => p.side === 'a')
  const b = players.filter(p => p.side === 'b')

  /* WHICH SNAPSHOT SIDE IS THE TOP ROW. Snapshots read in the match's own
     orientation (side 1 = bracket player1). The draw caller shows player1 on
     top by construction; the schedule caller shows the SHEET's order, which
     need not agree — so line them up by draw_entry_id where the row is
     stamped, by surname where it is not, and only then assume. Getting this
     wrong flips every tick to the wrong player, which is worse than no
     ticks. */
  const topIsP1 = (() => {
    if (!entry) return true
    const top = a[0]
    if (!top) return true
    if (top.draw_entry_id != null && data?.player1_id != null) {
      return top.draw_entry_id === data.player1_id
    }
    if (data?.player1_name) {
      const last = (splitPlayerName(top.name).last || '').toLowerCase()
      if (last) return data.player1_name.toLowerCase().includes(last)
    }
    return true
  })()

  /* WHO WON, in the SNAPSHOT's orientation, for the match tick. Handed to
     the detector rather than read off the games, because a retirement
     decides a match from behind and the games would name the wrong side.
     Draw caller: compare winner to player1. Schedule caller: winner_side is
     sheet-oriented, so route it through topIsP1. */
  const winnerSide = (() => {
    if (!completed) return null
    if (entry) {
      if (entry.winner_side !== 'a' && entry.winner_side !== 'b') return null
      return (entry.winner_side === 'a') === topIsP1 ? 1 : 2
    }
    if (match?.winner?.id == null || match?.player1?.id == null) return null
    return match.winner.id === match.player1.id ? 1 : 2
  })()

  /* Breaks, set-ends and the match's end as coloured ticks — the timeline
     as a map. Derived in utils/scoreTimeline (plain module, node-tested);
     memoised because a live match re-renders this popup on every point. */
  const markers = useMemo(
    () => timelineMarkers(snapshots, { completed, winnerSide }),
    [data?.snapshots, completed, winnerSide])

  if (!match && !entry) return null

  const initials = (row) => {
    const { first, last } = splitPlayerName(row?.name || '')
    const ini = `${(first || '').charAt(0)}${(last || '').charAt(0)}`.toUpperCase()
    return ini || (row?.name || '').slice(0, 2).toUpperCase()
  }

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
            {/* The gutter names the rows: top player's initials above the
                track's level, bottom player's below — the same order as the
                card. Each tick then hangs toward whoever earned it. */}
            <div className="shp-scrub-names">
              <span>{initials(a[0])}</span>
              <span>{initials(b[0])}</span>
            </div>
            <div className="shp-track">
            {/* Ticks sit UNDER the input (z-index) and take no pointer events
                — the slider owns every touch, exactly as before. Positioned
                against the thumb's travel, not naive percent: the thumb is
                28px wide, so its centre runs [14px, 100%-14px]. */}
            {markers.map(m => (
              <span
                key={`${m.kind}${m.i}${m.adj ? 'a' : ''}`}
                className={`shp-tick shp-tick--${m.kind} shp-tick--${
                  (m.side === 1) === topIsP1 ? 'up' : 'down'}`}
                /* adj: a break that sealed the set/match rides 7px to the
                   LEFT of the tick it sealed — beside, never underneath. */
                style={{ left: `calc(var(--shp-thumb) / 2 + (100% - var(--shp-thumb)) * ${m.i / max}${m.adj ? ' - 7px' : ''})` }}
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
            </div>
            {markers.length > 0 && (
              <div className="shp-legend">
                <span className="shp-legend-item">
                  <span className="shp-legend-box shp-tick--break" /> break
                </span>
                <span className="shp-legend-item">
                  <span className="shp-legend-box shp-tick--set" /> set
                </span>
                {markers.some(m => m.kind === 'match') && (
                  <span className="shp-legend-item">
                    <span className="shp-legend-box shp-tick--match" /> match
                  </span>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>,
    document.body
  )
}
