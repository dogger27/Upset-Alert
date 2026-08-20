import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'

/**
 * Subscribe to a tournament's server-sent events and refetch when it changes.
 *
 * The backend has been publishing these for a long time with nothing listening
 * — no route, no EventSource — so a score reached the screen only on the next
 * poll: two minutes on the draw page, and never on the schedule page, which has
 * no interval at all. For a set score that is slow. For the POINT score, which
 * changes every few seconds, it made the feature pointless; a 40-15 delivered
 * two minutes late is worse than showing none, which is exactly the reasoning
 * the server-side freshness guard is built on.
 *
 * The event carries no data on purpose. It is a nudge, and the component
 * refetches through its normal query — already written, already cached, already
 * authorised. Pushing scores down this channel would create a second way for a
 * client to learn a score, and therefore a second thing to keep consistent.
 */
export function useLiveUpdates(tournamentIds, queryKeys) {
  const qc = useQueryClient()

  // One id or several. The schedule page shows a whole day, which can span two
  // tournaments at once, and subscribing to only the first would leave the
  // other silently stale — the exact failure this hook exists to remove.
  const ids = (Array.isArray(tournamentIds) ? tournamentIds : [tournamentIds])
    .filter(Boolean)

  useEffect(() => {
    if (ids.length === 0) return

    const base = import.meta.env.VITE_API_URL ?? '/api'

    const invalidate = () => {
      for (const key of queryKeys) qc.invalidateQueries({ queryKey: key })
    }

    // EventSource cannot send an Authorization header, which is fine: this
    // endpoint only ever says "something changed", never what. The refetch it
    // triggers carries the token as usual.
    const sources = ids.map((id) => {
      const es = new EventSource(`${base}/stream/${id}`)
      // The server names the event; listen for the specific one AND the default
      // channel, so renaming it server-side degrades to "still works" rather
      // than "silently stops".
      es.addEventListener('draw_updated', invalidate)
      es.onmessage = invalidate
      // No onerror handler that closes the stream: EventSource reconnects by
      // itself, and closing here would turn one dropped connection — a laptop
      // lid, a tunnel blip — into a permanently dead page.
      return es
    })

    return () => sources.forEach((es) => es.close())
    // queryKeys is an array literal at most call sites and would be a new
    // reference every render; serialising it keeps this from reconnecting on
    // every paint.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids.join(','), JSON.stringify(queryKeys), qc])
}
