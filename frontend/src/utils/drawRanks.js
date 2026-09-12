/*
 * The number in a bracket badge: a player's rank WITHIN THIS FIELD.
 *
 * Seeds keep their seed number; everyone else is ordered behind them. The
 * offset is the HIGHEST SEED NUMBER PRESENT, not the count, so a withdrawn
 * seed leaves a gap instead of colliding two players onto one number.
 *
 * ORDERED BY THE SEEDING WEEK (`seed_week_ranking`). `ranking` is the ENTRY
 * week — the cutoff that decided who got in — so using it put the unseeded on
 * a ranking a fortnight older than the one the seeds were drawn from, which is
 * one scale stitched out of two moments. Fifteen of Guadalajara's twenty-five
 * players moved between those weeks and eight of its unseeded would have taken
 * a different badge (owner, 2026-09-12). Falls back to `ranking` on draws
 * scraped before the column existed, then to bracket position.
 *
 * ONE COPY. This lived in BracketView and again in CombinedView, with
 * mobile/drawRanks.js a third and services/upsets.py a fourth — and the app
 * once showed 83 where the site showed 76 for the same player because a copy
 * had drifted. The server's upset check must agree with the badge a reader
 * sees, so the rule is imported, never re-derived.
 */
export function computeDrawRanks(players) {
  const ranks = {}
  if (!players) return ranks
  const seeded = players.filter(p => p.seed != null)
  for (const p of seeded) ranks[p.id] = p.seed
  const rank = p => (p.seed_week_ranking != null ? p.seed_week_ranking : p.ranking)
  const unseeded = players
    .filter(p => p.seed == null)
    .sort((a, b) => {
      const ra = rank(a), rb = rank(b)
      if (ra != null && rb != null) return ra - rb
      if (ra != null) return -1
      if (rb != null) return 1
      return (a.bracket_position ?? 0) - (b.bracket_position ?? 0)
    })
  const offset = seeded.reduce((max, p) => Math.max(max, p.seed), 0)
  unseeded.forEach((p, i) => { ranks[p.id] = offset + i + 1 })
  return ranks
}
