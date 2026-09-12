/*
 * The number in a bracket badge is a player's rank WITHIN THIS FIELD, not their
 * world ranking.
 *
 * Ported verbatim from frontend/src/utils/drawRanks.js rather than re-derived,
 * because re-deriving it is exactly how the app came to show Sonego as 83 while
 * the site showed 76 for the same match: the API's `ranking` IS the world
 * ranking (83), and the site never puts it in the badge — it is the tooltip.
 * Seeds keep their seed number; everyone else is ordered behind them.
 *
 * BY THE SEEDING WEEK (`seed_week_ranking`), which is the week the seeds
 * themselves came from. `ranking` is the ENTRY week — the cutoff that decided
 * who got in — so ordering the unseeded by it made one scale out of two
 * moments a fortnight apart (owner, 2026-09-12). Falls back to `ranking` for
 * draws scraped before the column existed.
 *
 * The offset is the HIGHEST SEED NUMBER PRESENT, not the count of seeds, so a
 * withdrawn seed leaves a gap instead of colliding two players onto one number.
 */
export function computeDrawRanks(players) {
  const ranks = {}
  if (!players) return ranks

  const seeded = players.filter(p => p.seed != null)
  for (const p of seeded) ranks[p.id] = p.seed

  const unseeded = players
    .filter(p => p.seed == null)
    .sort((a, b) => {
      const ra = a.seed_week_ranking != null ? a.seed_week_ranking : a.ranking
      const rb = b.seed_week_ranking != null ? b.seed_week_ranking : b.ranking
      if (ra != null && rb != null) return ra - rb
      if (ra != null) return -1
      if (rb != null) return 1
      return a.bracket_position - b.bracket_position
    })

  const offset = seeded.reduce((max, p) => Math.max(max, p.seed), 0)
  unseeded.forEach((p, i) => { ranks[p.id] = offset + i + 1 })
  return ranks
}
