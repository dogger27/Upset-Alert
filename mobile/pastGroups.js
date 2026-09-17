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

const ROUND_RANK = { Q1: 1, Q2: 2, Q3: 3, Q4: 4, R256: 9, R128: 10, R64: 11, R32: 12, R16: 13, QF: 14, SF: 15, F: 16 }

export function roundRank(label) {
  const key = shortRound(label) || ''
  if (key in ROUND_RANK) return ROUND_RANK[key]
  const m = /^R(\d+)$/.exec(key)
  if (m) return 20 - Math.log2(Number(m[1]))       // any other Rn lands between R256 and R16 in order
  return 50                                         // unknown wording: after everything named
}

const DISCIPLINE = { singles: ['Singles', 0], doubles: ['Doubles', 1], mixed: ['Mixed doubles', 2] }
function discipline(e) {
  return DISCIPLINE[e.discipline] || DISCIPLINE.doubles
}

/* `entries` in the day's chronology. Returns groups in reading order:
   { key, tournament, first, discipline, round, list } — `first` marks the
   first group of a tournament (the one that carries the tournament's
   heading), `tournament` is null unless `byTournament`. */
export function groupPastDay(entries, { byTournament = false } = {}) {
  const groups = new Map()
  for (const e of entries || []) {
    const t = byTournament ? (e.tournament_name || `Tournament ${e.tournament_id}`) : null
    const [dName, dRank] = discipline(e)
    const round = shortRound(e.round_label) || ''
    const key = `${t ?? ''}|${dName}|${round}`
    if (!groups.has(key)) {
      groups.set(key, { key, tournament: t, first: false, discipline: dName, dRank, round, rRank: roundRank(e.round_label), list: [] })
    }
    groups.get(key).list.push(e)
  }
  const out = [...groups.values()].sort((a, b) =>
    (a.tournament ?? '').localeCompare(b.tournament ?? '') || a.dRank - b.dRank || a.rRank - b.rRank || a.round.localeCompare(b.round))
  let last = null
  for (const g of out) {
    g.first = g.tournament != null && g.tournament !== last
    last = g.tournament
    delete g.dRank; delete g.rRank
  }
  return out
}
