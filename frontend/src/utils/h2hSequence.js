/**
 * The order the H2H panel's ‹ › arrows step through.
 *
 * Bracket order (round, then match number) — the same order the draw is read
 * in, so "next" means what it looks like it means on screen.
 *
 * Byes are skipped (not a contest), and so is any match where a side has no
 * name yet — an empty qualifier slot or an unreached round has no opponents to
 * compare. A missing Tennis Explorer slug does NOT disqualify a match: rank,
 * Elo, age and the pick control all come from our own draw data, and the panel
 * says plainly which player it has no TE profile for. Requiring a slug here
 * made the button vanish from real matches the moment an unmatched player
 * reached them, which is when it is most wanted.
 *
 * Resolution is passed in rather than recomputed so the sequence follows
 * whatever the caller is already showing.
 */
export function buildH2HSequence(matches, resolved, playerById) {
  return matches
    .filter(m => !m.is_bye)
    .map(m => {
      const { p1: aId, p2: bId } = resolved[m.id] || {}
      const p1 = aId != null ? playerById[aId] : null
      const p2 = bId != null ? playerById[bId] : null
      return p1?.name && p2?.name ? { match: m, p1, p2 } : null
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

/**
 * Resolution for the H2H panel: the players who ACTUALLY met, falling back to
 * the picks cascade only where the match hasn't been played.
 *
 * The panel was fed the same cascade the bracket draws, which in picks mode is
 * the user's own predictions. Once a round is played that cascade still names
 * whoever they picked — including players who lost — so opening H2H on a
 * finished match could compare two people who never played each other, or a
 * player already out of the draw. Real entrants win wherever they exist; the
 * cascade still covers rounds not yet played, where a predicted matchup is the
 * only thing there is to show.
 */
export function resolveRealFirst(matches, resolved) {
  const out = {}
  for (const m of matches) {
    const r = resolved[m.id] || {}
    out[m.id] = {
      p1: m.player1?.id ?? r.p1 ?? null,
      p2: m.player2?.id ?? r.p2 ?? null,
    }
  }
  return out
}
