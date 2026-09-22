/* A PAST DAY, IN THE TIME VIEW, READS AS A RECORD RATHER THAN A RUNNING
 * ORDER (owner, 2026-09-17): grouped by tournament when more than one is
 * showing, singles before doubles within each, and by round within those —
 * qualifying rounds first, then the draw from its first round to the final.
 * Inside a group the rows keep the order they arrived in (the day's
 * chronology), so a group is still read top to bottom as it was played.
 *
 * Today and the days ahead keep the plain chronology: a reader on the day
 * wants what is on next, not the bracket. */
import { shortRound } from './rounds.js'
import { sideDrawRank, sideSeed } from './schedule.js'

const ROUND_RANK = { Q1: 1, Q2: 2, Q3: 3, Q4: 4, R256: 9, R128: 10, R64: 11, R32: 12, R16: 13, QF: 14, SF: 15, F: 16 }

export function roundRank(label) {
  const key = shortRound(label) || ''
  if (key in ROUND_RANK) return ROUND_RANK[key]
  const m = /^R(\d+)$/.exec(key)
  if (m) return 20 - Math.log2(Number(m[1]))       // any other Rn lands between R256 and R16 in order
  return 50                                         // unknown wording: after everything named
}

/* THE ORDER THE EVENTS THEMSELVES GO IN (owner, 2026-09-23): "show the higher
 * tournament categories First. Whenever tied / equal, give preference to ATP
 * over WTA."
 *
 * Alphabetical is what this was, which put Almaty above the US Open. The tier
 * is stated in RANKING POINTS because that is what a tier IS — the number the
 * draw-filter bar prints above each name, 2000 down to 125 — so the order the
 * reader sees on this page is the order they see there.
 *
 * A combined week is as big as its BIGGER half: Beijing is a WTA 1000 beside
 * an ATP 500, and the 1000 is what puts it above a 500-only week. It counts
 * as ATP for the tie-break, because it has an ATP draw in it.
 */
export function tierPoints(category) {
  const s = String(category || '')
  if (/slam/i.test(s)) return 2000
  // The season finale carries no number of its own and is second only to a
  // Slam; without this it would read as 0 and sort below a 125.
  if (/finals/i.test(s)) return 1500
  const m = /(\d{3,4})/.exec(s)
  return m ? Number(m[1]) : 0
}

/* [size, tour] for one event, from the tier stamps the day already carries
   ({ gender, category } per gendered draw). Sorted ascending, so size is
   negated: the biggest event is the smallest key. */
export function eventRank(stamps) {
  const points = Math.max(0, ...(stamps || []).map(x => tierPoints(x.category)))
  // `0 - points`, never `-points`: an event with no tier would answer -0,
  // which is the same number everywhere except a deepEqual.
  return [0 - points, (stamps || []).some(x => x.gender === 'M') ? 0 : 1]
}

/* The lookup groupPastDay takes, built from the day's own tournaments. An
   event we hold no stamp for ranks last rather than first: an unknown tier is
   not a big one. */
export function eventRankFrom(tournaments) {
  const by = new Map((tournaments || []).map(t => [t.id, eventRank(t.stamps)]))
  return (e) => by.get(e?.tournament_id) || [0, 2]
}

const DISCIPLINE = { singles: ['Singles', 0], doubles: ['Doubles', 1], mixed: ['Mixed doubles', 2] }
function discipline(e) {
  return DISCIPLINE[e.discipline] || DISCIPLINE.doubles
}

/* THE STRENGTH OF A MATCH, for the order inside a group (owner,
   2026-09-17): the matches with the higher seeds first, then the higher
   ranked, then the day's chronology. A seed outranks any ranking; lower
   numbers are stronger; nothing known sorts last. */
export function matchStrength(e) {
  const seeds = ['a', 'b'].map(s => sideSeed(e.players, s)).filter(x => x != null)
  const ranks = ['a', 'b'].map(s => sideDrawRank(e.players, s)).filter(x => x != null)
  return [seeds.length ? Math.min(...seeds) : Infinity, ranks.length ? Math.min(...ranks) : Infinity]
}

export function sortByStrength(list) {
  return list.map((e, i) => ({ e, i, k: matchStrength(e) }))
    .sort((x, y) => x.k[0] - y.k[0] || x.k[1] - y.k[1] || x.i - y.i)
    .map(x => x.e)
}

/* `entries` in the day's chronology. Returns groups in reading order:
   { key, tournament, first, tour, discipline, round, list } — `first`
   marks the first group of a tournament (the one that carries the
   tournament's heading), `tournament` is null unless `byTournament`, `tour`
   is null unless `byTour` (a dual-gender event: ATP before WTA — owner,
   2026-09-17). Inside a group the matches are in order of strength. */
export function groupPastDay(entries, { byTournament = false, byTour = false,
                                        eventRank: rankOf = null } = {}) {
  const groups = new Map()
  for (const e of entries || []) {
    const t = byTournament ? (e.tournament_name || `Tournament ${e.tournament_id}`) : null
    const tour = byTour ? (e.tour || '') : null
    const [dName, dRank] = discipline(e)
    const round = shortRound(e.round_label) || ''
    const key = `${t ?? ''}|${tour ?? ''}|${dName}|${round}`
    if (!groups.has(key)) {
      groups.set(key, { key, tournament: t, first: false, tour, discipline: dName, dRank,
                        eRank: rankOf ? rankOf(e) : [0, 0],
                        round, rRank: roundRank(e.round_label), list: [] })
    }
    groups.get(key).list.push(e)
  }
  const out = [...groups.values()].sort((a, b) =>
    a.eRank[0] - b.eRank[0] || a.eRank[1] - b.eRank[1]
    // Two events of the same size on the same tour still need one order, and
    // the name is the only thing left that does not change between passes.
    || (a.tournament ?? '').localeCompare(b.tournament ?? '') || (a.tour ?? '').localeCompare(b.tour ?? '')
    || a.dRank - b.dRank || a.rRank - b.rRank || a.round.localeCompare(b.round))
  for (const g of out) g.list = sortByStrength(g.list)
  let last = null
  for (const g of out) {
    g.first = g.tournament != null && g.tournament !== last
    last = g.tournament
    delete g.dRank; delete g.rRank; delete g.eRank
  }
  return out
}
