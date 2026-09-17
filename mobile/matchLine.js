/* One match as one line — the schedule's compact list (owner, 2026-09-17):
 *
 *     round · Player 1 vs Player 2 · score          (still to be played, or on)
 *     round · Winner def. Loser · score             (decided)
 *
 * Surnames only, particles kept ("del Potro"); doubles as "Hsieh/Ostapenko".
 * Everything is derived through the card's own helpers — sideName for the
 * furniture-stripped names, winnerSide for who won, scoreLine for the sets —
 * so the line and the card can never disagree about a match. */
import { sideName, winnerSide } from './schedule.js'
import { scoreLine, scoreSets } from './score.js'
import { surname } from './scoring.js'
import { shortRound } from './rounds.js'

/* Doubles: six letters of each surname at most (owner, 2026-09-17) — two
   pairs of full surnames do not share a row with a score. A cut, not an
   ellipsis: "Ostape/Hsieh" reads; "Ostap…/Hsieh" does not. Singles keeps
   the whole surname. */
const DOUBLES_LETTERS = 6

export function sideSurnames(players, side) {
  const full = sideName(players, side)
  if (full === 'TBD') return 'TBD'
  const names = full.split(' / ').map(surname)
  if (names.length < 2) return names[0]
  return names.map(n => n.slice(0, DOUBLES_LETTERS)).join('/')
}

export function matchLine(e) {
  const a = sideSurnames(e.players, 'a'), b = sideSurnames(e.players, 'b')
  const won = e.status === 'completed' ? winnerSide(e) : null
  const decided = won === 'a' || won === 'b'
  const names = decided ? `${won === 'a' ? a : b} def. ${won === 'a' ? b : a}` : `${a} vs ${b}`
  /* THE SCORE READS FROM THE WINNER'S SIDE once the winner is named first:
     "Lys def. Knutson 6-3 6-3", never "3-6 3-6". The sets are stored in the
     sheet's order (side a first), so a side-b winner has the rows swapped
     before they are printed — scoreLine's tiebreak and retirement marks are
     symmetric, so nothing else changes. An undecided match keeps the sheet's
     order, as its names do. */
  let sets = scoreSets(e)
  if (won === 'b' && Array.isArray(sets) && sets.length >= 2) sets = [sets[1], sets[0]]
  return {
    round: shortRound(e.round_label) || '',
    names,
    decided,
    score: scoreLine(sets, ' ') || '',
  }
}
