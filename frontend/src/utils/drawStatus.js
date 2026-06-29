const ONE_DAY_MS = 86400000

// Returns today's date as YYYY-MM-DD in Pacific time (handles PST/PDT automatically)
function todayPacific() {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'America/Los_Angeles' })
}

// Cluster draws where consecutive end_dates are ≤1 day apart.
// Returns { [id]: { cohortMaxDate, cohortHasActive, isLastWeek } }
// isLastWeek is true for exactly one cohort: the most recently completed one.
// A cohort is "still active" (not yet completed) if any draw is status='active',
// OR if cohortMaxDate >= todayPacific() (Rule 3: stay Active until Pacific midnight).
export function computeCohortInfo(draws) {
  const withDate = (draws || [])
    .filter(t => t.end_date)
    .sort((a, b) => a.end_date.localeCompare(b.end_date))
  if (!withDate.length) return {}

  const result = {}
  let clusterStart = 0

  for (let i = 1; i <= withDate.length; i++) {
    const isLast = i === withDate.length
    const gap = isLast ? Infinity
      : new Date(withDate[i].end_date + 'T00:00:00') - new Date(withDate[i - 1].end_date + 'T00:00:00')
    if (isLast || gap > ONE_DAY_MS) {
      const cluster = withDate.slice(clusterStart, i)
      const cohortMaxDate = cluster[cluster.length - 1].end_date
      const cohortHasActive = cluster.some(t => t.status === 'active')
      for (const t of cluster) result[t.id] = { cohortMaxDate, cohortHasActive, isLastWeek: false }
      clusterStart = i
    }
  }

  // Among cohorts that are truly completed (not still active), the one with the
  // most recent cohortMaxDate is "Last Week". All others go to Previous.
  const today = todayPacific()
  const completedDates = [
    ...new Set(
      Object.values(result)
        .filter(r => !r.cohortHasActive && r.cohortMaxDate < today)
        .map(r => r.cohortMaxDate)
    ),
  ].sort()

  const lastWeekDate = completedDates.at(-1) ?? null

  if (lastWeekDate) {
    for (const id in result) {
      if (result[id].cohortMaxDate === lastWeekDate) result[id].isLastWeek = true
    }
  }

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
