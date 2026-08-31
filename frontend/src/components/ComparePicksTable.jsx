import { useQuery } from '@tanstack/react-query'
import { getComparePicks } from '../api/tournaments'
import UserName from './UserName'
import { splitPlayerName } from '../utils/flags'

/** Everyone's late-round picks side by side — the "Compare Picks" tab of a
    draw's card. Users down the side, SF/F/W across, and within each round one
    column per BRACKET POSITION. The server scopes to the league's members
    (or all pickers on Global) and enforces the same predictions_visible
    rule as the draw: before picks lock, another user's bracket is not
    yours to read. */

/* HOW MANY POSITIONS A ROUND HAS.
   Read off the label, not off the column's index: the server names these tiers
   by what the pick MEANS — your predicted semi-finalists, finalists, champion
   — so SF is four people, F is two and W is one however many tiers a small
   draw happens to have. Deriving it from position in the array would give the
   same answers only while all three are present, and break silently on the
   draws where they are not. */
const ROUND_SLOTS = { SF: 4, F: 2, W: 1 }

/* The column groups are wide enough now to say what they are. The short label
   is kept as the fallback, so an unmapped tier still reads correctly. */
const ROUND_TITLES = { SF: 'Semi-Finalists', F: 'Finalists', W: 'Winner' }

/* SURNAME AND AN INITIAL. Seven name columns now sit where three stacked
   lists used to, so a full given name is width the row cannot spare — and it
   is the least informative part of the name. The initial stays rather than
   going entirely, because a bracket routinely holds two players who share a
   surname (Zverev, Murray) and a bare surname would make them the same person.
   splitPlayerName is the same parser the draw and the schedule use, so a
   team, a seed prefix or a trailing IOC code is handled identically here. */
function shortName(raw) {
  const { first, last } = splitPlayerName(raw)
  if (!last) return raw
  return first ? `${first.trim()[0]}. ${last}` : last
}

function PickChip({ pk }) {
  return (
    <div className={`compare-pick-name${
      pk.state === 'correct' ? ' compare-pick-name--correct'
      : pk.state === 'out' ? ' compare-pick-name--out'
      : ' compare-pick-name--open'}`}>
      {/* Exactly the draw page's rules: a real seed is the grey box, an
          implied draw-order rank the coloured one, and the entry token
          (WC/Q/LL...) sits flush right — same classes, same colours, both
          themes. */}
      {pk.seed != null ? (
        <span className="pos-badge seeded">{pk.seed}</span>
      ) : pk.implied != null ? (
        <span className="pos-badge unseeded">{pk.implied}</span>
      ) : null}
      <span className="compare-pick-label" title={pk.name}>{shortName(pk.name)}</span>
      {pk.entry_type && (
        <span className={`pos-badge entry entry-${pk.entry_type.toLowerCase()} compare-pick-entry`}>{pk.entry_type}</span>
      )}
    </div>
  )
}

export default function ComparePicksTable({ drawId, leagueId }) {
  const { data } = useQuery({
    queryKey: ['compare-picks', drawId, leagueId ?? 'global'],
    queryFn: () => getComparePicks(drawId, leagueId),
    staleTime: 60_000,
  })
  if (!data) return <p className="compare-picks-empty">Loading…</p>
  if (data.hidden) {
    return <p className="compare-picks-empty">Picks are hidden until the draw locks.</p>
  }
  if (!data.users.length) {
    return <p className="compare-picks-empty">No picks submitted yet.</p>
  }

  /* Never fewer columns than someone actually has picks for. The map above is
     the truth about the bracket, but a column that exists in the data and not
     in the table would drop a pick silently, which is worse than a stray
     empty column. */
  const slotsOf = data.rounds.map(r => Math.max(
    ROUND_SLOTS[r] ?? 1,
    ...data.users.map(u => (u.picks[r] ?? []).length),
  ))

  return (
    <div className="compare-table-scroll">
      <table className="compare-table compare-table--positions">
        <thead>
          <tr>
            <th rowSpan={2} className="compare-table-user">User</th>
            {data.rounds.map((r, i) => (
              <th key={r} colSpan={slotsOf[i]} className="cmp-round">
                {ROUND_TITLES[r] ?? r}
              </th>
            ))}
          </tr>
          <tr>
            {data.rounds.flatMap((r, i) =>
              Array.from({ length: slotsOf[i] }, (_, k) => (
                <th key={`${r}-${k}`}
                    className={`cmp-pos${k === 0 ? ' cmp-group-start' : ''}`}>
                  {k + 1}
                </th>
              )))}
          </tr>
        </thead>
        <tbody>
          {data.users.map(u => (
            <tr key={u.user_id}>
              <td className="compare-table-user"><UserName user={u} /></td>
              {data.rounds.flatMap((r, i) => {
                const picks = u.picks[r] ?? []
                /* One cell per position, occupied or not. An unfilled slot
                   still holds its column open — otherwise the people who
                   picked a full bracket and the people who did not would have
                   their names under different headings on the same row. */
                return Array.from({ length: slotsOf[i] }, (_, k) => (
                  <td key={`${r}-${k}`}
                      className={`cmp-cell${k === 0 ? ' cmp-group-start' : ''}`}>
                    {picks[k] ? <PickChip pk={picks[k]} /> : null}
                  </td>
                ))
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
