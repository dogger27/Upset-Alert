/* THE COURT VIEW'S GROUPS: one per court, the site's rule for their order —
 * courts by the best seed playing on them, so the show courts rise without
 * hardcoding venue names (every tournament calls its main court something
 * different); then by how many matches a court hosts, then name. Singles
 * only: a doubles [1] says nothing next to a singles [1]. A finite sentinel,
 * not Infinity — two unseeded courts would compare as NaN and a NaN
 * comparator leaves the array in whatever order it started.
 *
 * BY TOURNAMENT when more than one is showing (owner, 2026-09-17):
 * tournaments in name order, as a past day's record is, each one's courts
 * ranked among themselves; the first court of each carries the tournament's
 * heading (`title`), the rest none. One tournament: no headings at all.
 *
 * Returns [{ key, court, title, list }], each list in the court's own
 * running order. */
const NO_SEED = 9999

export function courtGroups(entries) {
  const byT = new Map()
  for (const e of entries) {
    const t = e.tournament_id
    if (!byT.has(t)) byT.set(t, { name: e.tournament_name || `Tournament ${t}`, courts: new Map() })
    const courts = byT.get(t).courts
    const k = e.court || 'Court TBA'
    if (!courts.has(k)) courts.set(k, [])
    courts.get(k).push(e)
  }
  const many = byT.size > 1
  const tournaments = [...byT.entries()].sort((a, b) => a[1].name.localeCompare(b[1].name))
  const out = []
  for (const [t, { name, courts }] of tournaments) {
    const ranked = [...courts.entries()].map(([court, list]) => {
      list.sort((a, b) => (a.court_order ?? 99) - (b.court_order ?? 99))
      let best = NO_SEED, count = 0
      for (const e of list) {
        if (e.discipline !== 'singles') continue
        count += 1
        for (const p of e.players || []) if (p.seed != null && p.seed < best) best = p.seed
      }
      return { court, list, best, count }
    })
    ranked.sort((a, b) => a.best - b.best || b.count - a.count || a.court.localeCompare(b.court))
    ranked.forEach((r, i) => out.push({
      key: many ? `${t} ${r.court}` : r.court,
      court: r.court,
      title: many && i === 0 ? name : null,
      list: r.list,
    }))
  }
  return out
}
