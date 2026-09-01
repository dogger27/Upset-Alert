/*
 * Tennis score formatting, ported from frontend/src/utils/score.jsx.
 *
 * Copied rather than reinvented, and that file says why: the tiebreak rule —
 * show the points only for the set's LOSER — is exactly the detail that drifts
 * between two copies. The web's own schedule page got it wrong the first time
 * by inventing its own.
 *
 * ONE LINE, NOT COLUMNS. The first version of the app's match box put each set
 * in a fixed 15pt cell, so "6(7)" had nowhere to go and wrapped one character
 * per line — a box six hundred points tall with a lone bracket on its own row.
 * Sets are a sentence, not a table.
 *
 * RN has no <sup>, so the tiebreak uses Unicode superscript digits. They are
 * real characters, so they never wrap away from their game count.
 */

const SUP = { 0: '⁰', 1: '¹', 2: '²', 3: '³', 4: '⁴', 5: '⁵', 6: '⁶', 7: '⁷', 8: '⁸', 9: '⁹' }
const sup = n => String(n).split('').map(c => SUP[c] ?? c).join('')

function parseSet(cell) {
  const s = String(cell ?? '').trim()
  const g = s.match(/^(\d+)/)
  const tb = s.match(/\((\d+)\)/)
  return { g: g ? g[1] : '', tb: tb ? tb[1] : null }
}

/** "6-4 7-5 6⁷-7 6-1", or null when there is nothing to show. */
export function scoreLine(scores) {
  if (!scores || scores.length < 2) return null
  const [a, b] = scores

  // A walkover has no games to format — the withdrawing side's only cell is the
  // literal "w/o". Without this the set loop skips everything and a completed
  // match shows no score and no reason.
  if ([a, b].some(arr => arr?.some(v => /^w\/?o$/i.test(String(v ?? '').trim())))) {
    return 'walkover'
  }

  const n = Math.max(a?.length ?? 0, b?.length ?? 0)
  const sets = []
  let retired = false

  for (let i = 0; i < n; i++) {
    if (/r$/i.test(a?.[i] ?? '') || /r$/i.test(b?.[i] ?? '')) retired = true
    const A = parseSet(a?.[i]), B = parseSet(b?.[i])
    if (A.g === '' && B.g === '') continue
    const gA = Number(A.g), gB = Number(B.g)
    // The tiebreak loser is the side with fewer games; only their points show.
    const loserIsA = A.tb != null && (B.tb == null || gA < gB)
    if (A.tb != null && loserIsA) sets.push(`${A.g}${sup(A.tb)}-${B.g}`)
    else if (B.tb != null && !loserIsA) sets.push(`${A.g}-${B.g}${sup(B.tb)}`)
    else sets.push(`${A.g}-${B.g}`)
  }

  if (!sets.length) return null
  return sets.join('  ') + (retired ? ' (ret.)' : '')
}
