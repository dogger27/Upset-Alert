const ONE_DAY_MS = 86400000

/* Today's date as YYYY-MM-DD in Pacific time (handles PST/PDT automatically).
 *
 * BOTH HALVES OF THIS ARE LOAD-BEARING, and the plain one-liner it replaced —
 * `new Date().toLocaleDateString('en-CA', { timeZone })` — was the single most
 * expensive line in this directory:
 *
 *  - Passing options to toLocaleDateString CONSTRUCTS A FORMATTER on every
 *    call. Measured at ~110µs each against ~1.5µs for a reused one.
 *  - It is called once per draw, and Home runs four independent filter passes
 *    over every draw, so 111 production draws cost 444 constructions —
 *    measured at 37.2ms per Home render, for a string that changes once a day.
 *
 * The formatter is therefore built once, and its answer held for a minute. The
 * cost of that minute is that a draw can move from Active to Last Week up to
 * 60s after Pacific midnight; nothing else on the page reacts to that boundary
 * any faster, so the lag is invisible. Same buckets, 0.9ms.
 */
const PACIFIC_DAY = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Los_Angeles' })
const DAY_TTL_MS = 60_000
let _day = null
let _dayAt = 0

function todayPacific() {
  const now = Date.now()
  if (_day === null || now - _dayAt >= DAY_TTL_MS) {
    _day = PACIFIC_DAY.format(new Date())
    _dayAt = now
  }
  return _day
}

/* WHICH DRAWS MOVE TOGETHER, and which week they belong to — two questions,
 * and they need two different groupings. Returns
 * { [id]: { cohortMaxDate, cohortHasActive, isLastWeek } }.
 *
 * THE EVENT, AND THE WEEK IT IS PLAYED IN, decide whether a finished draw
 * keeps showing as Active. Both halves are load-bearing, and each was tried
 * alone first:
 *
 *   DATES ALONE welded unrelated tournaments together. 2026 Guadalajara
 *   finished on the 19th and went on reading "Active" for two days because
 *   SP Open — a different event, a different country — ended on the 20th
 *   (owner, 2026-09-21).
 *
 *   A tournament_id ALONE trusts that a tournament row is one week of play,
 *   and four of them are not: an ATP and a WTA event sharing a city's name
 *   are one row here even when they are months apart. Hong Kong's ATP 250
 *   was played in January and its WTA 250 is in November, so the January
 *   event inherited a cohort running to November and reappeared under
 *   ACTIVE in September, ten months after its final (owner, 2026-09-21).
 *
 * So a cohort is draws that share a tournament_id AND are played together —
 * the intersection, narrower than either rule was. A combined event's two
 * draws qualify: same row, same week, and a men's final does not retire the
 * event while the women's is on court, which is what the rule is for.
 *
 * THE WEEK, separately, decides which finished cohort is "Last Week", and
 * there date proximity across events is right: that section is a week's
 * worth of tournaments, not one event.
 */
export function computeCohortInfo(draws) {
  const withDate = (draws || []).filter(t => t.end_date)
  if (!withDate.length) return {}

  /* Split a list, sorted by end_date, wherever consecutive draws are more
     than a day apart. Used twice below, on two different groupings. */
  const runs = (sorted) => {
    const out = []
    let start = 0
    for (let i = 1; i <= sorted.length; i++) {
      const isLast = i === sorted.length
      const gap = isLast ? Infinity
        : new Date(sorted[i].end_date + 'T00:00:00') - new Date(sorted[i - 1].end_date + 'T00:00:00')
      if (isLast || gap > ONE_DAY_MS) {
        out.push(sorted.slice(start, i))
        start = i
      }
    }
    return out
  }
  const byEnd = (a, b) => a.end_date.localeCompare(b.end_date)

  // ── the event, as played ─────────────────────────────────────────────────
  // A draw with no tournament_id is its own event; nothing else can be said
  // about it.
  const events = new Map()
  for (const t of withDate) {
    const key = t.tournament_id != null ? `t${t.tournament_id}` : `d${t.id}`
    if (!events.has(key)) events.set(key, [])
    events.get(key).push(t)
  }
  const result = {}
  for (const members of events.values()) {
    for (const cohort of runs([...members].sort(byEnd))) {
      const cohortMaxDate = cohort[cohort.length - 1].end_date
      const cohortHasActive = cohort.some(t => t.status === 'active')
      for (const t of cohort) result[t.id] = { cohortMaxDate, cohortHasActive, isLastWeek: false }
    }
  }

  // ── the week, for "Last Week" alone ──────────────────────────────────────
  // The most recent week in which nothing is still playing. A week holding an
  // active draw is not last week, whatever its dates say.
  const today = todayPacific()
  const finished = runs([...withDate].sort(byEnd)).filter(
    w => w.every(t => t.status !== 'active') && w[w.length - 1].end_date < today)
  const lastWeek = finished[finished.length - 1]
  if (lastWeek) for (const t of lastWeek) result[t.id].isLastWeek = true

  return result
}

// Rule 3: cohort stays in Active until midnight Pacific on cohortMaxDate
function cohortIsStillActive(info) {
  if (!info) return false
  if (info.cohortHasActive) return true
  return info.cohortMaxDate >= todayPacific()
}

// Maps a draw to one of: 'upcoming' | 'open' | 'active' | 'lastweek' | 'previous'
export function getDisplayStatus(t, cohortInfo) {
  if (t.status === 'upcoming') return 'upcoming'
  if (t.status === 'open') return 'open'
  if (t.status === 'active') return 'active'
  if (t.status === 'completed') {
    const info = cohortInfo?.[t.id]
    if (cohortIsStillActive(info)) return 'active'
    if (info?.isLastWeek) return 'lastweek'
    return 'previous'
  }
  return 'previous'
}

// Home page only: upcoming limited to within 8 days; null = not shown
export function getHomeSection(t, cohortInfo) {
  if (t.status === 'open') return 'open'
  if (t.status === 'active') return 'active'
  if (t.status === 'completed') {
    const info = cohortInfo?.[t.id]
    if (cohortIsStillActive(info)) return 'active'
    if (info?.isLastWeek) return 'lastweek'
  }
  if (t.status === 'upcoming' && t.start_date) {
    const today = new Date(); today.setHours(0, 0, 0, 0)
    const in8Days = new Date(today); in8Days.setDate(today.getDate() + 8)
    const start = new Date(t.start_date + 'T00:00:00')
    if (start > today && start <= in8Days) return 'upcoming'
  }
  return null
}

export const DISPLAY_STATUS_LABELS = {
  upcoming: 'Upcoming',
  open: 'Open',
  active: 'Active',
  lastweek: 'Last Week',
  previous: 'Previous',
}
