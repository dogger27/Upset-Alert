/**
 * PredictorsPopup — who called a finished match right, and who didn't.
 *
 * Opened from the group chip on the left edge of a completed match box (the
 * mirror of the H2H chip on its right edge). Scoped to the league the draw
 * page currently has selected; on Global that's every participant in the draw.
 *
 * Portalled to <body> so it isn't clipped by the bracket's scroller, and so a
 * chip near the edge of the draw doesn't push the popup off screen.
 */
import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import { getMatchPredictors } from '../api/tournaments'
import UserName from './UserName'
import { splitPlayerName } from '../utils/flags'
import './PredictorsPopup.css'

function CheckMark() {
  return (
    <svg className="pp-icon" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M2.5 8.5 L6.2 12.2 L13.5 3.8" fill="none" stroke="currentColor"
            strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/** "Sho Shimabukuro" → "S. Shimabukuro"; a two-word surname stays whole. */
function shortName(raw) {
  const { first, last } = splitPlayerName(raw)
  if (!last) return raw
  return first ? `${first[0]}. ${last}` : last
}


export default function PredictorsPopup({ drawId, match, leagueId, onClose }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['match-predictors', drawId, match?.id, leagueId ?? 'global'],
    queryFn: () => getMatchPredictors(drawId, match.id, leagueId),
    enabled: !!match?.id,
    staleTime: 60_000,
  })

  // Same body-scroll lock the H2H panel uses — see the .h2h-modal-open rule in
  // H2HPanel.css for why an unlocked background is worse on iOS than it looks.
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

  const winner = match?.winner
  const loser = match?.player1?.id === winner?.id ? match?.player2 : match?.player1
  const correct = data?.correct ?? []
  const incorrect = data?.incorrect ?? []

  return createPortal(
    <div className="pp-backdrop" onClick={onClose}>
      <div className="pp-popup" onClick={e => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="pp-header">
          <div className="pp-title">
            <span className="pp-winner">{winner?.name || '—'}</span>
            <span className="pp-def"> def. </span>
            <span className="pp-loser">{loser?.name || '—'}</span>
          </div>
          <button className="pp-close" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="pp-scope">{data?.league_name || 'Global'}</div>

        {isLoading && <div className="pp-state">Loading…</div>}
        {isError && <div className="pp-state">Couldn’t load predictions.</div>}

        {!isLoading && !isError && (
          <div className="pp-lists">
            <div className="pp-list">
              <div className="pp-list-head pp-list-head--correct">
                <span className="pp-badge pp-badge--check"><CheckMark /></span>
                <span className="pp-count">{correct.length}</span>
              </div>
              <ul className="pp-names">
                {correct.map(u => <li key={u.id}><UserName user={u} /></li>)}
                {correct.length === 0 && <li className="pp-none">Nobody</li>}
              </ul>
            </div>
            <div className="pp-list">
              <div className="pp-list-head pp-list-head--wrong">
                <span className="pp-badge pp-badge--square" />
                <span className="pp-count">{incorrect.length}</span>
              </div>
              <ul className="pp-names pp-names--wrong">
                {/* Name the player they backed. The handle alone says a pick
                    missed; the name says what they believed — and whether the
                    room split or everyone backed the same loser. Initial and
                    surname only: the column is narrow and the full name would
                    wrap under every handle. */}
                {incorrect.map(u => (
                  <li key={u.id}>
                    <UserName user={u} />
                    <span className="pp-picked">{u.picked ? `(${shortName(u.picked)})` : ''}</span>
                  </li>
                ))}
                {incorrect.length === 0 && <li className="pp-none">Nobody</li>}
              </ul>
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body
  )
}
