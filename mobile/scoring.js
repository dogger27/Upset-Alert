/*
 * The two comparisons that decide what the standings and picks screens SAY.
 *
 * Pulled out of the screens so they can be tested without a renderer. Both
 * encode rules that fail silently — a wrong answer here looks like a working
 * app that quietly disagrees with the website.
 */

/* Level on total AND on every round.
 *
 * The server sorts entries by total points, then by points in the latest
 * rounds first (Final -> SF -> QF -> ...). That tiebreak is LEXICOGRAPHIC over
 * the round vector, not a weighted sum, so two people on the same total are
 * only actually tied if their whole round vector matches. Comparing totals
 * alone would call them tied and give them the same rank when the server has
 * deliberately ordered one above the other.
 */
export function sameStanding(a, b) {
  if (!a || !b || a.total !== b.total) return false
  const x = a.round_points || [], y = b.round_points || []
  return x.length === y.length && x.every((v, i) => v === y[i])
}

/* Competition ranking: 1, 1, 1, 4 — not 1, 1, 1, 2.
 * Genuinely level people share a rank, and the next person takes the position
 * they actually occupy. */
export function competitionRanks(entries) {
  const out = []
  entries.forEach((e, i) => {
    out.push(i > 0 && sameStanding(entries[i - 1], e) ? out[i - 1] : i + 1)
  })
  return out
}

/* What to print in one side of a match.
 *
 * A named entrant always wins: in a bye match one side IS a real player, and
 * labelling both sides "Bye" hides who received it. An empty slot is NOT a
 * bye — power-of-two draws have zero byes, so a null player is a match whose
 * feeder has not been played. A drawn-but-unnamed qualifier slot reads
 * "Qualifier", which is what the draw sheet says. */
export function slotLabel(entry, match) {
  if (entry?.name) return entry.name
  if (match?.is_bye) return 'Bye'
  if (!entry) return 'TBD'
  return entry.entry_type === 'Q' ? 'Qualifier' : 'TBD'
}

/* The finish column: where a bracket can still end up, over every result
 * left to play. "3" is a place clinched; "3–7" a range still open. The
 * server sends it from R16 on (see scoring.FINISH_RANGE_MAX_UNDECIDED) and
 * nothing before, so a missing value is "not yet", not "unknown". */
export function finishText(e) {
  if (e?.best_rank == null) return '–'
  return e.best_rank === e.worst_rank ? String(e.best_rank) : `${e.best_rank}–${e.worst_rank}`
}

/* Sort by best possible finish, then by least to lose, then the standings
 * order — the same tiebreak the site uses for its Finish header. */
export function byFinish(order) {
  return (a, b) =>
    ((a.best_rank ?? Infinity) - (b.best_rank ?? Infinity))
    || ((a.worst_rank ?? Infinity) - (b.worst_rank ?? Infinity))
    || (order.get(a.user_id) - order.get(b.user_id))
}

/* The round a match belongs to, as a chip: F, SF, QF, then R16, R32 … by
 * how far it sits from the final. The timeline carries round numbers only. */
export function roundTag(roundNumber, numRounds) {
  const fromEnd = numRounds - roundNumber
  if (fromEnd === 0) return 'F'
  if (fromEnd === 1) return 'SF'
  if (fromEnd === 2) return 'QF'
  return `R${2 ** (fromEnd + 1)}`
}

/* A surname, particles kept ("del Potro"), the way the draw prints them. */
const PARTICLES = new Set(['de', 'del', 'della', 'di', 'da', 'van', 'von', 'der', 'den', 'le', 'la', 'du', 'dos', 'das'])
export function surname(full) {
  const parts = String(full ?? '').trim().split(/\s+/)
  let i = parts.length - 1
  while (i > 0 && PARTICLES.has(parts[i - 1].toLowerCase())) i -= 1
  return parts.slice(i).join(' ') || '?'
}
export const worldLine = w => `${surname(w.final.winner)} def. ${surname(w.final.loser)}`

/* The standings order: points, then the later rounds first — the site's
 * sort and the server's, for rows re-scored on the phone. */
export function sortStandings(rows) {
  return [...rows].sort((a, b) => {
    if (b.total !== a.total) return b.total - a.total
    for (let i = a.round_points.length - 1; i >= 0; i--) {
      const d = (b.round_points[i] ?? 0) - (a.round_points[i] ?? 0)
      if (d !== 0) return d
    }
    return 0
  })
}

/* THE TABLE REWOUND to the first `pos` matches of the timeline: every row
 * re-scored from its picks on those matches alone, then re-sorted, with the
 * finish range and podium as they stood at that point. */
export function scrubEntries(entries, timeline, pos, userPredictions, finishHistory = {}) {
  const slice = timeline.slice(0, pos)
  const hist = finishHistory[String(pos)] ?? null
  const rows = entries.map(e => {
    const preds = userPredictions[String(e.user_id)] ?? {}
    let total = 0, correct_count = 0
    const byRound = {}
    for (const m of slice) {
      if (String(preds[String(m.id)]) === String(m.winner_id)) {
        byRound[m.round_number] = (byRound[m.round_number] ?? 0) + m.points
        total += m.points
        correct_count += 1
      }
    }
    const round_points = Array.from({ length: e.round_points.length }, (_, i) => byRound[i + 1] ?? 0)
    // The Finish column of THIS snapshot: the range as it stood at this
    // position, a dash before the first position it exists at.
    const r = hist?.[String(e.user_id)] ?? null
    return { ...e, round_points, total, correct_count,
             best_rank: r ? r[0] : null, worst_rank: r ? r[1] : null, podium_locked: !!r && r[1] <= 3 }
  })
  return sortStandings(rows)
}

/* THE TABLE UNDER A WORLD: each pick that names the world's winner pays that
 * match's points; then the usual order. Nothing is left to play in a chosen
 * world, so Max is the score and the finish is a single place. */
export function worldEntries(entries, world, worldPredictions) {
  const rows = entries.map(e => {
    const preds = worldPredictions[String(e.user_id)] ?? {}
    const round_points = [...e.round_points]
    let total = e.total, correct_count = e.correct_count ?? 0
    for (const r of world.results) {
      if (String(preds[String(r.match_id)]) === String(r.winner_id)) {
        round_points[r.round_number - 1] = (round_points[r.round_number - 1] ?? 0) + r.points
        total += r.points
        correct_count += 1
      }
    }
    return { ...e, round_points, total, correct_count, max_points: total }
  })
  const sorted = sortStandings(rows)
  const ranks = competitionRanks(sorted)
  return sorted.map((e, i) => ({ ...e, best_rank: ranks[i], worst_rank: ranks[i], podium_locked: ranks[i] <= 3 }))
}
