import { useQuery } from '@tanstack/react-query'
import { getComparePicks } from '../api/tournaments'

/** Everyone's late-round picks side by side — the "Compare Picks" tab of a
    draw's card. Users down the side, QF/SF/F across, one predicted winner
    per line in bracket order. The server scopes to the league's members
    (or all pickers on Global) and enforces the same predictions_visible
    rule as the draw: before picks lock, another user's bracket is not
    yours to read. */
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
  return (
    <div className="compare-table-scroll">
      <table className="compare-table">
        <thead>
          <tr>
            <th className="compare-table-user">User</th>
            {data.rounds.map(r => <th key={r}>{r}</th>)}
          </tr>
        </thead>
        <tbody>
          {data.users.map(u => (
            <tr key={u.user_id}>
              <td className="compare-table-user">{u.username}</td>
              {data.rounds.map(r => (
                <td key={r}>
                  {(u.picks[r] ?? []).map((pk, i) => (
                    <div key={i} className="compare-pick-name">
                      {/* The draw page's own badges, same classes, same
                          colours — a seed box or a WC/Q/LL entry box. */}
                      {pk.seed != null && (
                        <span className="pos-badge seeded">{pk.seed}</span>
                      )}
                      {pk.seed == null && pk.entry_type && (
                        <span className={`pos-badge entry entry-${pk.entry_type.toLowerCase()}`}>{pk.entry_type}</span>
                      )}
                      <span>{pk.name}</span>
                    </div>
                  ))}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
