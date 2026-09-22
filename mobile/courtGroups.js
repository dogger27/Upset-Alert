/* THE COURT VIEW'S GROUPS: one per court, the site's rule for their order —
 * courts by the best seed playing on them, so the show courts rise without
 * hardcoding venue names (every tournament calls its main court something
 * different); then by how many matches a court hosts, then name. Singles
 * only: a doubles [1] says nothing next to a singles [1]. A finite sentinel,
 * not Infinity — two unseeded courts would compare as NaN and a NaN
 * comparator leaves the array in whatever order it started.
 *
 * A QUALIFYING seed is seeded separately too, so it ranks below every
 * main-draw seed (QUALI_SEED + n). Chengdu 2026-09-23: the Q-final [1] and [3]
 * put both qualifying courts above CENTER COURT's R32 [8], the reverse of the
 * sheet. Offset, not dropped, so a qualifying-only day still orders its courts
 * by seed. AND BELOW EVERY MAIN-DRAW MATCH, seeded or not: Hangzhou 2026-09-23
 * (doc 421) put its two unseeded R32s on CENTER COURT and only Q-finals on
 * COURT 1, and an unseeded player ranking at NO_SEED listed COURT 1's
 * qualifying [1] first — the reverse of the sheet again. An unseeded main-draw
 * player ranks at QUALI_SEED, between the two. The web's twin is
 * frontend/src/utils/courtRank.js.
 *
 * BY TOURNAMENT, ALWAYS (owner, 2026-09-17; always 2026-09-20): tournaments
 * in name order, as a past day's record is, each one's courts ranked among
 * themselves, and the first court of each carrying the tournament's heading
 * (`title`) while the rest carry none.
 *
 * The heading used to appear only where two tournaments were showing, on the
 * grounds that it says nothing when there is only one. It does say something:
 * WHICH one. Ticking a tournament off left the courts of the remaining event
 * under no name at all, so the page stopped telling the reader whose courts
 * these were at exactly the moment they had narrowed to them — and a court
 * called "Grandstand" or "Center Court" belongs to any tournament you like.
 *
 * Returns [{ key, court, title, list }], each list in the court's own
 * running order. */
const NO_SEED = 9999
const QUALI_SEED = 1000

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
  const tournaments = [...byT.entries()].sort((a, b) => a[1].name.localeCompare(b[1].name))
  const out = []
  for (const [t, { name, courts }] of tournaments) {
    const ranked = [...courts.entries()].map(([court, list]) => {
      list.sort((a, b) => (a.court_order ?? 99) - (b.court_order ?? 99))
      let best = NO_SEED, count = 0
      for (const e of list) {
        if (e.discipline !== 'singles') continue
        count += 1
        for (const p of e.players || []) {
          const rank = e.stage === 'qualifying'
            ? (p.seed == null ? NO_SEED : QUALI_SEED + p.seed)
            : (p.seed == null ? QUALI_SEED : p.seed)
          if (rank < best) best = rank
        }
      }
      return { court, list, best, count }
    })
    ranked.sort((a, b) => a.best - b.best || b.count - a.count || a.court.localeCompare(b.court))
    ranked.forEach((r, i) => out.push({
      // The tournament is always in the key: two events on one day can both
      // have a "Court 1", and a shared key would collide them into one group.
      key: `${t} ${r.court}`,
      court: r.court,
      title: i === 0 ? name : null,
      list: r.list,
    }))
  }
  return out
}
