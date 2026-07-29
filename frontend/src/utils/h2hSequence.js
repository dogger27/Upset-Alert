/**
 * The order the H2H panel's ‹ › arrows step through.
 *
 * Bracket order (round, then match number) — the same order the draw is read
 * in, so "next" means what it looks like it means on screen.
 *
 * Byes are skipped (not a contest), and so is any match where either side
 * lacks a Tennis Explorer slug: the panel is driven by TE data, and landing on
 * a match it can say nothing about would be a dead end the user has to arrow
 * back out of. Resolution is passed in rather than recomputed so the sequence
 * follows whatever the caller is already showing — in picks mode that is the
 * user's own cascade, not the official draw.
 */
export function buildH2HSequence(matches, resolved, playerById) {
  return matches
    .filter(m => !m.is_bye)
    .map(m => {
      const { p1: aId, p2: bId } = resolved[m.id] || {}
      const p1 = aId != null ? playerById[aId] : null
      const p2 = bId != null ? playerById[bId] : null
      return p1?.te_slug && p2?.te_slug ? { match: m, p1, p2 } : null
    })
    .filter(Boolean)
    .sort((a, b) =>
      a.match.round_number - b.match.round_number ||
      a.match.match_number - b.match.match_number)
}

/**
 * Position of every match within the whole draw, read in bracket order:
 * round 1's first match is 1, the final is the last number.
 *
 * Byes are left out — a bye is a slot, not a contest, so counting them would
 * make the total disagree with "matches in this draw". Unlike
 * buildH2HSequence this does NOT drop matches whose players lack a Tennis
 * Explorer slug: the denominator has to describe the draw, not the subset the
 * H2H panel happens to be able to talk about. That does mean the arrows can
 * step 5 -> 7 where a match in between has no slug on one side.
 */
export function buildMatchIndex(matches) {
  const ordered = matches
    .filter(m => !m.is_bye)
    .sort((a, b) =>
      a.round_number - b.round_number ||
      a.match_number - b.match_number)
  const order = {}
  ordered.forEach((m, i) => { order[m.id] = i + 1 })
  return { order, total: ordered.length }
}

/** Neighbours of `matchId` within a sequence from buildH2HSequence. */
export function h2hNeighbours(seq, matchId) {
  const i = seq.findIndex(e => e.match.id === matchId)
  return {
    prev: i > 0 ? seq[i - 1] : null,
    next: i >= 0 && i < seq.length - 1 ? seq[i + 1] : null,
    position: i,
    total: seq.length,
  }
}
