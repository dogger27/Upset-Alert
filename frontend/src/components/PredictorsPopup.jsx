/**
 * PredictorsPopup — who called a finished match right, and who didn't; on a
 * match still to be decided, whose pick is still standing and whose is out.
 *
 * Opened from the group chip on the left edge of a match box (the mirror of
 * the H2H chip on its right edge). Scoped to the league the draw page
 * currently has selected; on Global that's every participant in the draw.
 *
 * Undecided match: the left column's check becomes a yellow "?" (nobody has
 * been proven right yet), both columns name the pick, and the server orders
 * them by how many backed each player.
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

/** The match is still open: nobody is right yet, only still in it. */
function QuestionMark() {
  return <span className="pp-question" aria-hidden="true">?</span>
}

/** "Sho Shimabukuro" → "Shimabukuro": surname only, as asked — the handle
    beside it is the point, the pick just needs to be recognisable. A
    two-word surname ("Díaz Acosta") stays whole. */
function shortName(raw) {
  const { last } = splitPlayerName(raw)
  return last || raw
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
  // Decided by the match itself, not the response, so the title and the "?"
  // are right from the first paint rather than after the fetch. player1 and
  // player2 here are the draw's own entrants (the /draw payload), not the
  // user's cascade — the names line is shown only once both are known.
  const pending = winner?.id == null
  const known = !!(match?.player1?.id && match?.player2?.id)
  // Same test as the bracket's own "In Progress" badge (CombinedView's
  // isLiveMatch), so the pill here never disagrees with the box it came from.
  const live = pending && match?.live_scores != null
  const status = !pending ? 'Completed' : !known ? 'TBD' : live ? 'In Progress' : 'Upcoming'
  const statusMod = { Completed: 'done', TBD: 'tbd', 'In Progress': 'live', Upcoming: 'upcoming' }[status]
  const correct = data?.correct ?? []
  const incorrect = data?.incorrect ?? []

  const PickedRow = ({ u }) => (
    <li key={u.id}>
      <UserName user={u} />
      <span className="pp-picked">{u.picked ? `(${shortName(u.picked)})` : ''}</span>
    </li>
  )

  return createPortal(
    <div className="pp-backdrop" onClick={onClose}>
      <div className="pp-popup" onClick={e => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="pp-header">
          <div className="pp-head-main">
            {/* Names only once the ACTUAL players of this match are known: a
                later round still waiting on its feeders gets no "TBD vs. TBD"
                — the round and status pills below carry it instead. */}
            {(known || !pending) && (
              <div className="pp-title">
                {pending ? (
                  <>
                    <span className="pp-winner">{match.player1.name}</span>
                    <span className="pp-def"> vs. </span>
                    <span className="pp-winner">{match.player2.name}</span>
                  </>
                ) : (
                  <>
                    <span className="pp-winner">{winner?.name || '—'}</span>
                    <span className="pp-def"> def. </span>
                    <span className="pp-loser">{loser?.name || '—'}</span>
                  </>
                )}
              </div>
            )}
            {/* Always: which round this is, and where the match stands. */}
            <div className="pp-meta">
              <span className="pp-round">{match?.round_name || '—'}</span>
              <span className={`pp-status pp-status--${statusMod}`}>{status}</span>
            </div>
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
                {pending
                  ? <span className="pp-badge pp-badge--question"><QuestionMark /></span>
                  : <span className="pp-badge pp-badge--check"><CheckMark /></span>}
                <span className="pp-count">{correct.length}</span>
              </div>
              <ul className={`pp-names${pending ? ' pp-names--picked' : ''}`}>
                {/* Still open: the pick is named here too, since neither
                    player is "the winner, already in the title" yet. */}
                {correct.map(u => pending
                  ? <PickedRow key={u.id} u={u} />
                  : <li key={u.id}><UserName user={u} /></li>)}
                {correct.length === 0 && <li className="pp-none">Nobody</li>}
              </ul>
            </div>
            <div className="pp-list">
              <div className="pp-list-head pp-list-head--wrong">
                <span className="pp-badge pp-badge--square" />
                <span className="pp-count">{incorrect.length}</span>
              </div>
              <ul className="pp-names pp-names--picked">
                {/* Name the player they backed. The handle alone says a pick
                    missed; the name says what they believed — and whether the
                    room split or everyone backed the same loser. Initial and
                    surname only: the column is narrow and the full name would
                    wrap under every handle. */}
                {incorrect.map(u => <PickedRow key={u.id} u={u} />)}
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
