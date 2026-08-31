import { splitPlayerName } from '../utils/flags'

/* THE PIECES THE COMPARE TAB IS BUILT FROM.
   This was a standalone table. It is not one any more: Compare Picks is now
   the standings table with its bar track swapped for columns of predicted
   names, so the same row keeps its buttons, rank, name, correct count and
   score whichever tab is showing. What is left here is what BOTH tabs' compare
   view needs — how wide a round is, what to call it, and how one pick is
   drawn — kept in its own module so the chart does not grow a second job.
   Rendered by RoundProgressChart in pages/LeagueDetail.jsx. */

/* HOW MANY POSITIONS A ROUND HAS.
   Read off the label, not off the column's index: the server names these tiers
   by what the pick MEANS — your predicted semi-finalists, finalists, champion
   — so SF is four people, F is two and W is one however many tiers a small
   draw happens to have. Deriving it from position in the array would give the
   same answers only while all three are present, and break silently on the
   draws where they are not. */
export const ROUND_SLOTS = { SF: 4, F: 2, W: 1 }

/* The column groups are wide enough to say what they are. The short label is
   kept as the fallback, so an unmapped tier still reads correctly. */
export const ROUND_TITLES = { SF: 'Semi-Finalists', F: 'Finalists', W: 'Winner' }

/* SURNAME ONLY. Seven name columns sit where a bar track used to, and the
   given name is the least informative part of a tennis name — the seed beside
   it already separates the rare same-surname pair, and the full name is on the
   title attribute either way.
   splitPlayerName is the same parser the draw and the schedule use, so a team,
   a seed prefix or a trailing IOC code is handled identically here. */
function shortName(raw) {
  const { last } = splitPlayerName(raw)
  return last || raw
}

/** One predicted player, in the draw page's own verdict colours. */
export function PickChip({ pk }) {
  return (
    <div className={`compare-pick-name${
      pk.state === 'correct' ? ' compare-pick-name--correct'
      : pk.state === 'out' ? ' compare-pick-name--out'
      : ' compare-pick-name--open'}`}>
      {/* WRITTEN, NOT BOXED. A badge is a box inside a box: at seven columns a
          row it was a rail of little rectangles down every one, and each
          reserved a uniform 30px whether or not the player had a seed. As
          "[12]" the number costs what it costs and reads as part of the name.
          Seed and implied draw-order rank stay distinguishable by colour —
          the same distinction the badges made, without the geometry. */}
      {pk.seed != null ? (
        <span className="cmp-seed">[{pk.seed}]</span>
      ) : pk.implied != null ? (
        <span className="cmp-seed cmp-seed--implied">[{pk.implied}]</span>
      ) : null}
      <span className="compare-pick-label" title={pk.name}>{shortName(pk.name)}</span>
      {pk.entry_type && (
        <span className={`pos-badge entry entry-${pk.entry_type.toLowerCase()} compare-pick-entry`}>{pk.entry_type}</span>
      )}
    </div>
  )
}
