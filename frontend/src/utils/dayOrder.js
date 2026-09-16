/* THE TIME VIEW'S ORDER — one day as a chronology.
 *
 * Ordered by when a match ACTUALLY began, falling back to the estimate for
 * anything still to come. The API sorts on expected_start_at, which for a
 * match already under way is the time the sheet PRINTED — so a match that went
 * on late sat among the slots it was scheduled beside rather than where it
 * belongs, while its own row said "Started at" some quite different time.
 * Sorting on the same value the row displays is what makes the list read as a
 * chronology.
 *
 * THE TIME IT HAPPENS ON THIS DAY, which for a carried match is not the time
 * it began. A match suspended overnight keeps yesterday's started_at — that is
 * what the field means — so sorting on it filed the resumptions among
 * yesterday afternoon's slots. Resumed: when it came back. Still waiting to
 * resume: the slot it is scheduled to come back in. Keyed off the status
 * rather than off comparing started_at's date with play_date — those are a UTC
 * instant and a venue-local date, and a night match crossing midnight makes
 * that comparison lie.
 *
 * A ROW WITH NO TIME AT ALL GOES LAST. Guadalajara 2026-09-17 printed its
 * doubles semi-final "Time TBA - After suitable rest", alone on CANCHA with
 * that court's first band left empty: no clock, and nothing ahead of it to
 * chain an estimate from. The key read '' — which sorts before every instant —
 * and filed the one match whose time nobody knows at the TOP of the day, above
 * the 1:00 PM opener, where the sheet's layout and its own "after rest" both
 * put it later. Unknown is not early. `mobile/schedule.js` keeps the same rule
 * (byTimeOfDay) and routers/schedule.py serves the day in the same order.
 */

export function timeKey(e) {
  if (e.resumed_at) return e.resumed_at
  if (e.status === 'to_be_completed') return e.expected_start_at || null
  return e.started_at || e.expected_start_at || null
}

export function byTimeOfDay(entries) {
  return [...entries].sort((a, b) => {
    const ka = timeKey(a), kb = timeKey(b)
    if ((ka == null) !== (kb == null)) return ka == null ? 1 : -1
    if (ka !== kb) return ka < kb ? -1 : 1
    // Same instant, or both unknown: keep a court's own running order intact.
    return (a.court || '').localeCompare(b.court || '') || a.court_order - b.court_order
  })
}
