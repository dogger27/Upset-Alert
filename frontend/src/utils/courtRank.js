/* THE COURT VIEW'S ORDER — which court is listed first.
 *
 * Courts are ordered by the best seed playing on them, so the show courts
 * rise to the top without hardcoding venue-specific names — every tournament
 * calls its main court something different. Falls back to how many matches a
 * court is hosting, which is the next best proxy for importance when nobody
 * seeded is out there.
 *
 * Ranked on SINGLES only, even though the view lists everything: a doubles
 * bracket is seeded separately, so its [1] says nothing about how big the
 * match is next to a singles [1]. A court hosting only doubles scores nothing
 * on either measure and settles at the bottom, which is where it belongs
 * without being hidden.
 *
 * A QUALIFYING seed is seeded separately too, so it ranks below every
 * main-draw seed (QUALI_SEED + n). Chengdu 2026-09-23: the Q-final [1] and [3]
 * put both qualifying courts above CENTER COURT's R32 [8], the reverse of the
 * sheet. Offset, not dropped, so a qualifying-only day still orders its courts
 * by seed.
 *
 * AND BELOW EVERY MAIN-DRAW MATCH, seeded or not. Hangzhou 2026-09-23 (doc
 * 421): CENTER COURT carried the day's two main-draw R32s, both unseeded, and
 * COURT 1 only qualifying finals. An unseeded player ranked at NO_SEED — below
 * any qualifying seed — so COURT 1's Q-final [1] listed it above CENTER COURT,
 * the reverse of the sheet again. The Chengdu offset had fixed the seeded half
 * of one rule: the main draw is what a tournament puts on its show courts. An
 * unseeded main-draw player now ranks at QUALI_SEED, between the two.
 *
 * mobile/courtGroups.js is the twin; this copy is pinned by
 * courtRank.test.mjs and that one by courtGroups.test.mjs.
 */
import { splitPlayerName } from './flags.js'

// A finite sentinel rather than Infinity: two unseeded courts would otherwise
// compare as Infinity - Infinity = NaN, and a NaN comparator silently leaves
// the array in whatever order it started in.
const NO_SEED = 9999
// A main-draw player with no seed; a qualifying seed ranks at QUALI_SEED + n.
const QUALI_SEED = 1000

/**
 * A player's seed number, or null.
 *
 * The API sends it as a field, taken from the bracket where the player
 * resolved and from the sheet's own "[17]" otherwise — so a resolved name can
 * be shown clean without the seeding disappearing with the brackets. The parse
 * stays as the fallback for anything the API has not filled in.
 *
 * Only digits count. The same brackets carry [Q], [WC], [LL], [PR] and [Alt],
 * which say how a player ENTERED rather than how highly they are ranked — and a
 * name can carry both, as in "[WC] [2]".
 */
export function seedNumber(player) {
  if (player?.seed != null) return player.seed
  const { seed } = splitPlayerName(player?.name)
  const nums = seed && seed.match(/\d+/g)
  return nums ? Math.min(...nums.map(Number)) : null
}

/* Where one singles player ranks the court they are on. */
function playerRank(e, p) {
  const n = seedNumber(p)
  if (e.stage === 'qualifying') return n == null ? NO_SEED : QUALI_SEED + n
  return n == null ? QUALI_SEED : n
}

/* [[court, entries]] in the order the Court view lists them, each court's
   entries in its own running order. */
export function courtsByRank(entries) {
  const m = new Map()
  for (const e of entries) {
    const k = e.court || 'Unassigned'
    if (!m.has(k)) m.set(k, [])
    m.get(k).push(e)
  }
  for (const list of m.values()) list.sort((x, y) => x.court_order - y.court_order)

  const ranked = [...m.entries()].map(([name, list]) => {
    let best = NO_SEED
    let count = 0
    for (const e of list) {
      if (e.discipline !== 'singles') continue
      count += 1
      for (const p of e.players || []) best = Math.min(best, playerRank(e, p))
    }
    return { name, list, best, count }
  })
  ranked.sort((a, b) =>
    a.best - b.best || b.count - a.count || a.name.localeCompare(b.name))
  return ranked.map(r => [r.name, r.list])
}
