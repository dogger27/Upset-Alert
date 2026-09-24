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
export function compareRows({ view, surface, left, right, odds }) {
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
  add('overall', view.meetings.length ? 'meetings' : 'record', view.wins[0], view.wins[1])
  const surf = onSurface(view.surfaces, surface)
  if (surf && (surf[0] || surf[1])) {
    add('surface', `on ${String(surface).toLowerCase()}`, surf[0], surf[1])
  }
  /* UA ODDS (owner, 2026-09-24): each side's chance of winning, from the
     same model as the standings' chances, in whole percent. `odds` is
     [left, right] already oriented; the higher one is lit. */
  if (odds && odds[0] != null && odds[1] != null) {
    const l = Math.round(odds[0] * 100), r = 100 - l
    rows.push({ key: 'ua', label: 'UA odds', info: "Upset Alert's estimated winning percentage",
                values: [`${l}%`, `${r}%`], better: betterSide(l, r) })
  }
  add('rank', 'ranking', left?.ranking, right?.ranking, { lowerWins: true })
  add('elo', 'Elo', left?.elo_rank, right?.elo_rank, { lowerWins: true })
  add('age', 'age', ageOf(left?.date_of_birth), ageOf(right?.date_of_birth), { judged: false })
  return rows
}

/* THE FORM GRID: how big a swatch is, and how many go on a row.
 *
 * Five to a row is the shape the owner asked for and the site's own; what is
 * NOT fixed is the size, and fixing it was the mistake. At 18 points the five
 * squares used 102 of the 131 this column has at ordinary text size, and the
 * 29 that were left sat as a gap between them and the word in the middle
 * (owner, 2026-09-23: "make the form pill boxes larger, so they get closer to
 * the 'form' title"). Derived from the column instead, they fill it — and they
 * keep filling it on a wider phone.
 *
 * THE COUNT GIVES WAY BEFORE THE SIZE DOES. On a phone with large text the
 * label column grows and this one shrinks, and below about 85 points five
 * squares cannot be drawn at a size that still holds a letter — the first
 * version clamped the size up and overflowed the column instead, which the
 * suite caught at an 80pt column. So the row drops to four, then three: a
 * shorter line of form is still form, a clipped one is a bug.
 *
 * The ceiling is there because a swatch is a mark, not a button: past thirty
 * points a row of ten reads as ten tiles rather than one line of form. The
 * floor is the smallest square that still holds a letter.
 */
export const FORM_PER_ROW = 5
export const FORM_GAP = 3

export function formGrid(width, { gap = FORM_GAP, min = 14, max = 34,
                                  per = FORM_PER_ROW } = {}) {
  const each = (n) => Math.floor((width - (n - 1) * gap) / n)
  if (!(width > 0)) return { size: min, per }
  let n = per
  while (n > 1 && each(n) < min) n -= 1
  return { size: Math.max(min, Math.min(max, each(n))), per: n }
}

/* The letter inside, which grows with its box rather than sitting in the
   middle of one: fixed at 10 points it was a dot in a 24-point square. */
export function formChipText(size) {
  return Math.max(9, Math.round(size * 0.55))
}

/* TENNIS EXPLORER'S ROUND, IN THE APP'S OWN WORDS (owner, 2026-09-23: "WTF
 * is Q-R16??").
 *
 * That is TE's spelling for the qualifying round of sixteen, and it was being
 * printed raw — source vocabulary straight onto the screen. The app says Q1
 * and Q2 for qualifying rounds and R16 / QF / SF / F for the draw, and this
 * says the same things in those words.
 *
 * WHAT IT WILL NOT DO IS RENUMBER BY POSITION. It is tempting to read Q-R16
 * as Q1 — the round of sixteen IS the first round of a sixteen-player
 * qualifying draw — but a thirty-two-player qualifying draw has an R32 before
 * it, and there the same label is Q2. The draw size is not in a form row, so
 * the round of sixteen stays the round of sixteen: "Q R16" says qualifying
 * and says how deep, and says nothing it cannot know. Where TE numbers the
 * round itself ("Q-1R", from "Qualification - 1. round") the number is used,
 * because then it is stated rather than inferred.
 */
const ROUND_WORD = { F: 'final', FIN: 'final' }

export function roundWord(round) {
  const raw = String(round || '').trim()
  if (!raw) return ''
  const qual = /^q[-\s]/i.test(raw)
  const core = raw.replace(/^q[-\s]/i, '').toUpperCase()
  const ord = /^(\d+)R$/.exec(core)
  if (qual && ord) return `Q${ord[1]}`          // stated by TE, not inferred
  const word = ROUND_WORD[core] || core
  return qual ? `Q ${word}` : word
}

/* "C. SINCLAIR", NOT "SINCLAIR C." (owner, 2026-09-23: "it appears to be
 * writing the opponent with their first initial AFTER the last name").
 *
 * That is Tennis Explorer's own order, and it is the order a RESULTS TABLE
 * uses; the app writes a person the way a person is introduced, initials
 * first — mobile/names.js builds "B. van de Zandschulp" for exactly this
 * reason. Only a trailing single initial moves: a name that is already the
 * other way round, or has no initial at all, is left alone.
 *
 * Each half of a doubles pair is flipped on its own, so "Fancutt T. /
 * Watanabe S." becomes "T. Fancutt / S. Watanabe" rather than one name
 * swapping and the other not.
 */
export function teName(name) {
  return String(name || '')
    .split('/')
    .map(part => part.trim().replace(/^(.+?)\s+([A-Z][a-z]?\.)$/, '$2 $1'))
    .filter(Boolean)
    .join(' / ')
}

/* A SINGLES MATCH'S FORM IS SINGLES (owner, 2026-09-23). The form reads the
 * whole ladder on purpose — a qualifier's month is Challengers and Futures —
 * but a doubles result in a singles preview answers a question nobody asked:
 * two players' serve against two others tells you nothing about the singles
 * match being previewed, and it pushes a real result off the end of the row.
 */
export function singlesOnly(form) {
  return (form || []).filter(m => !m.doubles)
}

/* "CH", NOT "CHALLENGER" (owner, 2026-09-23). Tennis Explorer prints the rung
 * into the event's own name — "Guangzhou 2 challenger", "Mallorca challenger"
 * — and spelled out it takes a third of the line, which is how a detail line
 * ended up truncated. The tour's own shorthand is two letters.
 *
 * For a line that has NO field of its own for the rung: a previous meeting
 * carries no level, so taking the word out of its name would quietly promote
 * a Challenger to the tour.
 */
/* THE TOUR IS NOT PART OF THE NAME (owner, 2026-09-24: "Singapore WTA" in a
   form line). Tennis Explorer writes it in to tell a combined event's two
   halves apart; beside the other player's own result it is noise. Kept where
   the tour IS the event's name — ATP/WTA Finals, the ATP Cup — and never
   stripped to nothing. */
function dropTour(name) {
  const out = String(name || '')
    .replace(/\b(?:ATP|WTA)\b(?!\s+(?:Finals|Cup|Elite))/gi, ' ')
    .replace(/\s{2,}/g, ' ').trim()
  return out || String(name || '').trim()
}

export function shortEvent(name) {
  return dropTour(String(name || '').replace(/\bchallengers?\b/gi, 'CH'))
}

/* THE RUNG IS A FIELD, NOT PART OF THE NAME (owner, 2026-09-23: "when we
 * already put 'challenger' in the tournament type, remove it completely from
 * the tournament title"). Used only where the rung IS printed beside it —
 * "Mallorca · CH · 1R" rather than "Mallorca CH · CH · 1R" — which is why
 * shortEvent above still exists for the lines that have nowhere else to say
 * it.
 */
export function eventTitle(name) {
  return dropTour(String(name || '')
    // Both rung words, because both appear in a name whose level repeats them:
    // "ITF M15 Cancun" beside a rung of ITF said it twice, exactly as
    // "Mallorca challenger" did. What is left — "M15 Cancun" — is the part
    // that tells a reader something the rung does not.
    .replace(/\bchallengers?\b/gi, ' ')
    .replace(/\bitf\b/gi, ' ')
    .replace(/\s{2,}/g, ' ')
    .trim())
}

/* A form line as the sheet draws it: the newest results first, at most `n`,
   each carrying what it was so a screen reader can say it. */
export function formChips(form, n = 5) {
  return (form || []).slice(0, n).map(m => ({
    result: m.result,
    // What a tap opens, and what a screen reader hears without tapping.
    said: [m.result === 'W' ? 'beat' : 'lost to', teName(m.opponent),
           m.score, m.event, roundWord(m.round)].filter(Boolean).join(' '),
    match: m,
  }))
}

/* WHAT A TAPPED SWATCH SAYS, in two lines: the result and the score, then
   where it happened. The same shape as a meeting card below it, because it is
   the same kind of fact — one match, read in one glance — and the app should
   not have two ways of printing that.
 */
export function formDetail(m) {
  if (!m) return null
  /* The rung is said ONCE, as its own field, and the name gives it up: TE
     writes it into both ("Mallorca challenger", level "challenger") and
     printing both read the same fact twice on the line with no room. */
  const rung = m.level === 'challenger' ? 'CH'
    : m.level === 'itf' ? 'ITF'
      : m.level && m.level !== 'tour' ? String(m.level).toUpperCase() : null
  const event = rung ? eventTitle(m.event) : shortEvent(m.event)
  return {
    won: m.result === 'W',
    line: [m.result === 'W' ? `beat ${teName(m.opponent)}` : `lost to ${teName(m.opponent)}`,
           m.score].filter(Boolean).join(' · '),
    // The type sits with the tournament it types, before the round.
    meta: [event, rung, roundWord(m.round), m.doubles ? 'doubles' : null,
           m.surface].filter(Boolean).join(' · '),
  }
}
