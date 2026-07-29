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
