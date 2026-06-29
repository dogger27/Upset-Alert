const ONE_DAY_MS = 86400000

// Cluster draws where consecutive end_dates are ≤1 day apart.
// Returns { [id]: { cohortMaxDate, cohortHasActive } }
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
      for (const t of cluster) result[t.id] = { cohortMaxDate, cohortHasActive }
      clusterStart = i
    }
  }
  return result
}

// Maps a draw to one of: 'upcoming' | 'open' | 'active' | 'lastweek' | 'previous'
// All upcoming draws return 'upcoming' regardless of start_date proximity.
export function getDisplayStatus(t, cohortInfo) {
  if (t.status === 'upcoming') return 'upcoming'
  if (t.status === 'open') return 'open'
  if (t.status === 'active') return 'active'
  if (t.status === 'completed') {
    const info = cohortInfo?.[t.id]
    if (info?.cohortHasActive) return 'active'
    const endDate = info?.cohortMaxDate ?? t.end_date
    if (endDate) {
      const today = new Date(); today.setHours(0, 0, 0, 0)
      const daysAgo = (today - new Date(endDate + 'T00:00:00')) / ONE_DAY_MS
      if (daysAgo >= 0 && daysAgo < 7) return 'lastweek'
    }
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
    if (info?.cohortHasActive) return 'active'
    const endDate = info?.cohortMaxDate ?? t.end_date
    if (endDate) {
      const today = new Date(); today.setHours(0, 0, 0, 0)
      const daysAgo = (today - new Date(endDate + 'T00:00:00')) / ONE_DAY_MS
      if (daysAgo >= 0 && daysAgo < 7) return 'lastweek'
    }
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
