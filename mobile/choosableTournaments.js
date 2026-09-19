/*
 * WHICH TOURNAMENTS ARE ON OFFER — the one answer, for every control that asks.
 *
 * The tab bar's sheet and the Schedule page both filter by tournament, and two
 * copies of "which ones are there" is two chances to disagree: a page listing
 * a tournament the sheet does not offer is a filter the reader cannot undo
 * from the other control (owner, 2026-09-14).
 *
 * Three conditions, and all three earn their place:
 *
 *   1. A BRACKET TO OPEN (`hasDrawData`) — the dashboard's own test.
 *   2. LIVE, meaning the dashboard's top two sections: picks still open, or
 *      play under way. Without this the list was every draw ever released, so
 *      a season of finished events buried the two being played. getHomeSection
 *      also promotes a completed draw back to 'active' while the rest of its
 *      cohort plays on — a men's final does not retire the event while the
 *      women's is on court.
 *   3. ON THE SHEETS. A bracket released for next week has no order of play
 *      yet, so filtering a schedule to it hides everything.
 *
 * Returned as EVENTS, not draws: one US Open, not two. The ATP/WTA split is a
 * control these screens already have.
 */
import { getScheduleDates, listTournaments } from './api'
import { computeCohortInfo, getHomeSection } from './drawStatus'
import { tournamentsOf } from './scheduleRows'
import { useApi } from './useApi'

const LIVE_SECTIONS = new Set(['open', 'active'])
/* A bracket that actually exists to look at — the dashboard's own test, so no
   control can offer a tournament whose draw is unreleased. */
export const hasDrawData = t => t.status === 'completed' || !!t.draw_released_direct_at

export function useChoosableTournaments(ready = true) {
  /* Both under the keys the rest of the app already holds, so on all but the
     first visit this hook costs nothing. */
  const tours = useApi(ready ? 'tournaments' : null, listTournaments, { enabled: ready })
  const sched = useApi(ready ? 'schedule-dates:all' : null, () => getScheduleDates(),
                       { enabled: ready })

  /* computeCohortInfo needs EVERY draw: clustering a filtered list moves the
     boundaries it works out, which is how "Last Week" starts stealing from
     "Active". Filter AFTER, never before. */
  const all = tours.data || []
  const cohort = computeCohortInfo(all)
  const live = all.filter(hasDrawData)
    .filter(t => LIVE_SECTIONS.has(getHomeSection(t, cohort)))

  const events = tournamentsOf(live)
  const onSheets = sched.data?.tournaments
  return {
    all,
    live,
    /* WHICH SECTION a draw sits in — 'open', 'active' — off the cohort above,
       which was clustered over EVERY draw. Exposed so a caller can GROUP what
       this hook returned without recomputing that clustering on the filtered
       list, which is exactly the mistake the note at the top warns about
       (drawGroups.js). */
    sectionOf: t => getHomeSection(t, cohort),
    // Every live event, whether or not a sheet has been published for it.
    events,
    // The ones a filter can usefully name. Falls back to `events` while the
    // schedule's answer is still in flight, which is what this did before the
    // sheet-awareness existed.
    choosable: onSheets?.length ? events.filter(t => onSheets.includes(t.id)) : events,
  }
}
