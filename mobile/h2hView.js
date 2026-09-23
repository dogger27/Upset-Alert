/* THE READING OF A HEAD-TO-HEAD, kept apart from its drawing.
 *
 * Everything in this file is the arithmetic a reader does in their head when
 * they look at two names: whose number is whose, who is ahead, who is younger,
 * who won each meeting. It is here rather than in the sheet because it is the
 * half that can be wrong without looking wrong — and because a phone is a poor
 * place to discover that.
 *
 * WHOSE NUMBER IS WHICH is the whole risk. The endpoint answers in its own
 * order — slug_a / wins_a — and that order is NOT the order the two players
 * appear in the bracket. Reading wins_a as "the player on the left" is wrong
 * roughly half the time, and wrong in a way that looks perfectly plausible: a
 * 6-0 record simply points at the wrong man. So the payload is oriented ONCE,
 * here, and nothing downstream sees a/b again.
 */

/* One side's view of the pair, in the reader's own left-to-right order. */
export function orient(payload, leftSlug) {
  if (!payload) return null
  const flipped = payload.slug_a !== leftSlug
  const pick = (x, y) => (flipped ? [y, x] : [x, y])
  const [wins, theirs] = pick(payload.wins_a, payload.wins_b)
  const surfaces = {}
  for (const [surface, pair] of Object.entries(payload.surface_wins || {})) {
    const [l, r] = pick(pair?.[0], pair?.[1])
    surfaces[surface] = [l ?? 0, r ?? 0]
  }
  return {
    wins: [wins ?? 0, theirs ?? 0],
    surfaces,
    /* A meeting, with the winner named by SIDE rather than by the payload's
       letter. `side` is 0 for the reader's left player and 1 for their right,
       which is what the sheet aligns on. */
    meetings: (payload.matches || []).map(m => ({
      ...m,
      side: (flipped ? m.winner === 'b' : m.winner === 'a') ? 0 : 1,
    })),
  }
}

/* The wins on ONE surface, by the name the tournament calls it.
 *
 * The payload keys its splits however Tennis Explorer prints them ("Hard",
 * "hard", "I.hard" for indoors — feedback_te_surface_indoors), and the draw
 * states its own surface separately. Matching case-insensitively on the first
 * word is what makes "I.hard" answer a hard-court question, which is the
 * reading a person gives it.
 */
export function onSurface(surfaces, surface) {
  if (!surface) return null
  const want = String(surface).trim().toLowerCase()
  for (const [key, pair] of Object.entries(surfaces || {})) {
    const k = String(key).trim().toLowerCase()
    if (k === want || k.replace(/^i\./, '') === want) return pair
  }
  return null
}

/* Years old, from a date of birth. Whole years, because that is how tennis
   states an age — nobody is 30.4 in a preview. */
export function ageOf(dob, today = new Date()) {
  if (!dob) return null
  const d = new Date(dob)
  if (Number.isNaN(d.getTime())) return null
  let age = today.getFullYear() - d.getFullYear()
  const m = today.getMonth() - d.getMonth()
  if (m < 0 || (m === 0 && today.getDate() < d.getDate())) age -= 1
  return age >= 0 && age < 120 ? age : null
}

/* WHICH SIDE OF A ROW IS THE BETTER ONE, or neither.
 *
 * Returns 0, 1 or null — and null is the answer far more often than a
 * comparison function usually admits:
 *
 *   a tie            two players on the same ranking are not one ahead of the
 *                    other, and lighting both would say the opposite
 *   a missing value  a qualifier we hold no Elo for has not LOST that row, so
 *                    the player who has one has not won it either
 *   an age           thirty is not better or worse than twenty-seven. The row
 *                    is there because it is worth knowing, not to be won
 *
 * `lowerWins` is for the ranking rows, where #48 beats #59.
 */
export function betterSide(left, right, { lowerWins = false } = {}) {
  const l = typeof left === 'number' && Number.isFinite(left) ? left : null
  const r = typeof right === 'number' && Number.isFinite(right) ? right : null
  if (l == null || r == null || l === r) return null
  const leftWins = lowerWins ? l < r : l > r
  return leftWins ? 0 : 1
}

/* The rows of the comparison, in reading order, each already judged.
 *
 * The order is an argument, not a list: the two numbers a reader came for
 * (the record, and the record on the surface being played) lead; the standings
 * follow; the age is last because it colours the others rather than deciding
 * anything. Rows with nothing to say are dropped rather than shown empty —
 * "Elo —— Elo" is a row that costs height and answers nothing.
 */
export function compareRows({ view, surface, left, right }) {
  if (!view) return []
  const rows = []
  /* `judged: false` is a row with no winner. betterSide's own comment says an
     age has none — and then the first version handed the age row to it
     anyway, which lit thirty over twenty-seven as though the older player
     were ahead. A row can be worth showing and still not be a contest. */
  const add = (key, label, l, r, opts = {}) => {
    if (l == null && r == null) return
    rows.push({
      key, label, values: [l, r],
      better: opts.judged === false ? null : betterSide(l, r, opts),
    })
  }
  add('overall', view.meetings.length ? 'meetings won' : 'record', view.wins[0], view.wins[1])
  const surf = onSurface(view.surfaces, surface)
  if (surf && (surf[0] || surf[1])) {
    add('surface', `on ${String(surface).toLowerCase()}`, surf[0], surf[1])
  }
  add('rank', 'ranking', left?.ranking, right?.ranking, { lowerWins: true })
  add('elo', 'Elo', left?.elo_rank, right?.elo_rank, { lowerWins: true })
  add('age', 'age', ageOf(left?.date_of_birth), ageOf(right?.date_of_birth), { judged: false })
  return rows
}

/* A form line as the sheet draws it: the newest results first, at most `n`,
   each carrying what it was so a screen reader can say it. */
export function formChips(form, n = 5) {
  return (form || []).slice(0, n).map(m => ({
    result: m.result,
    said: [m.result === 'W' ? 'beat' : 'lost to', m.opponent,
           m.score, m.event, m.round].filter(Boolean).join(' '),
  }))
}
