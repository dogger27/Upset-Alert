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
 * THE EVENT decides whether a finished draw keeps showing as Active. A
 * combined tournament is two draws under one name, and a men's final does
 * not retire the event while the women's is still on court — that is the
 * whole point of the rule, and an event is exactly the set of draws sharing
 * a tournament_id.
 *
 * It used to be a DATE CLUSTER: any two draws whose end dates were within a
 * day of each other moved as one. That welded unrelated tournaments
 * together, and the failure was visible — 2026 Guadalajara finished on the
 * 19th and went on reading "Active" for two days because SP Open, a
 * different event in a different country, ended on the 20th (owner,
 * 2026-09-21: "Is it waiting for SP Open to finish so they can move
 * together?"). It also made the bucket depend on a date that can be wrong:
 * SP Open's own end date was stale by a rain delay at the time.
 *
 * THE WEEK still decides which finished cohort is "Last Week", and there the
 * date proximity is right: that section is a week's worth of tournaments,
 * not one event. So the clustering survives for exactly that, and for
 * nothing else.
 */
export function computeCohortInfo(draws) {
  const withDate = (draws || []).filter(t => t.end_date)
  if (!withDate.length) return {}

  // ── the event ────────────────────────────────────────────────────────────
  // A draw with no tournament_id is its own event; nothing else can be said
  // about it, and pretending otherwise is how the date cluster went wrong.
  const events = new Map()
  for (const t of withDate) {
    const key = t.tournament_id != null ? `t${t.tournament_id}` : `d${t.id}`
    if (!events.has(key)) events.set(key, [])
    events.get(key).push(t)
  }
  const result = {}
  for (const members of events.values()) {
    const cohortMaxDate = members.reduce(
      (mx, t) => (t.end_date > mx ? t.end_date : mx), members[0].end_date)
    const cohortHasActive = members.some(t => t.status === 'active')
    for (const t of members) result[t.id] = { cohortMaxDate, cohortHasActive, isLastWeek: false }
  }

  // ── the week, for "Last Week" alone ──────────────────────────────────────
  const sorted = [...withDate].sort((a, b) => a.end_date.localeCompare(b.end_date))
  const weeks = []
  let clusterStart = 0
  for (let i = 1; i <= sorted.length; i++) {
    const isLast = i === sorted.length
    const gap = isLast ? Infinity
      : new Date(sorted[i].end_date + 'T00:00:00') - new Date(sorted[i - 1].end_date + 'T00:00:00')
    if (isLast || gap > ONE_DAY_MS) {
      weeks.push(sorted.slice(clusterStart, i))
      clusterStart = i
    }
  }

  // The most recent week in which nothing is still playing. A week holding an
  // active draw is not last week, whatever its dates say.
  const today = todayPacific()
  const finished = weeks.filter(
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
