/* node h2hView.test.mjs — the reading of a head-to-head.

   The half that can be wrong without looking wrong. The endpoint answers in
   its own order (slug_a / wins_a) and that order is NOT the order the two
   players appear in the bracket, so a 6-0 record can point at the wrong man
   and look perfectly plausible doing it.
*/
import assert from 'node:assert/strict'
import { ageOf, betterSide, compareRows, formChips, formCount, formDetail, onSurface, orient } from './h2hView.js'

const PAYLOAD = {
  slug_a: 'shapovalov', slug_b: 'van-de-zandschulp',
  wins_a: 1, wins_b: 2,
  surface_wins: { Hard: [1, 2], Clay: [0, 0] },
  matches: [
    { year: 2026, tournament: 'Miami', round: '1R', surface: 'Hard', score: '5-7, 3-6', winner: 'b' },
    { year: 2024, tournament: 'US Open', round: '1R', surface: 'Hard', score: '4-6, 5-7, 4-6', winner: 'b' },
    { year: 2024, tournament: 'Indian Wells', round: '1R', surface: 'Hard', score: '6-1, 6-4', winner: 'a' },
  ],
}

/* ── the flip, which is the whole risk ───────────────────────────────────── */

function readBothWays() {
  return [orient(PAYLOAD, 'shapovalov'), orient(PAYLOAD, 'van-de-zandschulp')]
}

const [asShapo, asBotic] = readBothWays()

assert.deepEqual(asShapo.wins, [1, 2], 'read from the payload order, it is 1-2')
assert.deepEqual(asBotic.wins, [2, 1], 'read from the other side, the same record is 2-1')

assert.deepEqual(asShapo.surfaces.Hard, [1, 2])
assert.deepEqual(asBotic.surfaces.Hard, [2, 1], 'the surface split flips with everything else')

assert.deepEqual(asShapo.meetings.map(m => m.side), [1, 1, 0],
  'Botic won the first two; Shapovalov the third')
assert.deepEqual(asBotic.meetings.map(m => m.side), [0, 0, 1],
  'and from his own side, those are his wins')

assert.equal(orient(null, 'anyone'), null, 'no payload is no view, not an empty one')

/* A slug the payload does not name at all reads as flipped — which is the
   caller's bug, not this function's, and it must not throw. */
assert.deepEqual(orient(PAYLOAD, 'nobody').wins, [2, 1])

/* ── the surface, as the tour spells it ──────────────────────────────────── */

assert.deepEqual(onSurface({ Hard: [1, 2] }, 'Hard'), [1, 2])
assert.deepEqual(onSurface({ hard: [1, 2] }, 'Hard'), [1, 2], 'case is not a surface')
assert.deepEqual(onSurface({ 'I.hard': [3, 0] }, 'Hard'), [3, 0],
  'indoors is hard court to a reader — feedback_te_surface_indoors')
assert.equal(onSurface({ Clay: [1, 1] }, 'Hard'), null, 'and a different surface is not it')
assert.equal(onSurface({ Hard: [1, 2] }, null), null)

/* ── which side leads a row, and when neither does ───────────────────────── */

assert.equal(betterSide(2, 1), 0, 'more wins is better')
assert.equal(betterSide(1, 2), 1)
assert.equal(betterSide(48, 59, { lowerWins: true }), 0, 'a lower ranking is better')
assert.equal(betterSide(59, 48, { lowerWins: true }), 1)
assert.equal(betterSide(2, 2), null, 'a tie is not a lead')
assert.equal(betterSide(48, null, { lowerWins: true }), null,
  'a player we hold no Elo for has not lost that row, so nobody has won it')
assert.equal(betterSide(null, null), null)
assert.equal(betterSide('48', 59), null, 'a string is not a number we can compare')

/* ── the rows themselves ─────────────────────────────────────────────────── */

const LEFT = { ranking: 48, elo_rank: 69, date_of_birth: '1999-04-15' }
const RIGHT = { ranking: 59, elo_rank: 78, date_of_birth: '1996-10-04' }
const rows = compareRows({ view: asShapo, surface: 'Hard', left: LEFT, right: RIGHT })
const byKey = Object.fromEntries(rows.map(r => [r.key, r]))

assert.deepEqual(rows.map(r => r.key), ['overall', 'surface', 'rank', 'elo', 'age'],
  'the two numbers they came for lead; age is last because it decides nothing')
assert.deepEqual(byKey.overall.values, [1, 2])
assert.equal(byKey.overall.better, 1)
assert.equal(byKey.surface.label, 'on hard')
assert.equal(byKey.rank.better, 0, '#48 leads #59')
assert.equal(byKey.elo.better, 0)
assert.equal(byKey.age.better, null, 'thirty is not better or worse than twenty-seven')

const noStats = compareRows({ view: asShapo, surface: 'Hard', left: {}, right: {} })
assert.deepEqual(noStats.map(r => r.key), ['overall', 'surface'],
  'a row with nothing to say is dropped rather than shown empty')

const neverMet = compareRows({
  view: orient({ slug_a: 'x', slug_b: 'y', wins_a: 0, wins_b: 0, surface_wins: {}, matches: [] }, 'x'),
  surface: 'Hard', left: LEFT, right: RIGHT,
})
assert.equal(neverMet[0].label, 'record', 'with no meetings the first row is not "meetings won"')
assert.ok(!neverMet.some(r => r.key === 'surface'), 'and 0-0 on a surface is not a row')

assert.deepEqual(compareRows({ view: null, surface: 'Hard', left: LEFT, right: RIGHT }), [])

/* ── ages ────────────────────────────────────────────────────────────────── */

assert.equal(ageOf('1999-04-15', new Date('2026-09-23')), 27)
assert.equal(ageOf('1996-10-04', new Date('2026-09-23')), 29, 'a birthday still to come this year')
assert.equal(ageOf('1996-09-23', new Date('2026-09-23')), 30, 'and one that is today')
assert.equal(ageOf(null), null)
assert.equal(ageOf('not a date'), null)

/* ── the form line ───────────────────────────────────────────────────────── */

const form = [
  { result: 'W', opponent: 'Pavlovic L.', score: '6-4, 6-7(6), 6-3', event: 'Chengdu', round: 'Q-R16' },
  { result: 'L', opponent: 'Balshaw F.', score: '7-5, 6-2', event: 'Mallorca challenger', round: 'R16' },
]
const chips = formChips(form.concat(form, form), 5)
assert.equal(chips.length, 5, 'five is what a phone row holds')
assert.deepEqual(chips.map(c => c.result), ['W', 'L', 'W', 'L', 'W'], 'newest first, in order')
assert.match(chips[0].said, /^beat Pavlovic L\. 6-4, 6-7\(6\), 6-3 Chengdu Q-R16$/,
  'each square says what it was, for a reader who cannot see the colour')
assert.match(chips[1].said, /^lost to Balshaw F\./)
assert.deepEqual(formChips(null), [])

/* ── how many swatches a row holds, and what a tap on one says ─────────── */

// Ten results in two rows: what fits a row is measured, the depth is not.
assert.equal(formCount(131), 5, 'a phone column at ordinary text size holds five')
assert.equal(formCount(94), 4, 'and four when large text has taken the room')
assert.equal(formCount(40), 2, 'two 18pt swatches and their gap fit 39 of those 40 points')
assert.equal(formCount(12), 1, 'one is the floor, never zero — a swatch narrower than itself')
assert.equal(formCount(null), 5, 'before the row has been measured, draw the cap')
assert.equal(formCount(1000), 5, 'and a tablet does not get a barcode')
assert.equal(formCount(0), 5)

const full = formChips([
  { result: 'W', opponent: 'Pavlovic L.', score: '6-4, 6-3', event: 'Chengdu',
    round: 'Q-R16', surface: 'Hard', date: '2026-09-22', level: 'tour', doubles: false },
], 10)
assert.equal(full.length, 1)
assert.ok(full[0].match, 'a chip carries its match, because a tap opens it')

const det = formDetail(full[0].match)
assert.equal(det.won, true)
assert.equal(det.line, 'beat Pavlovic L. · 6-4, 6-3')
assert.equal(det.meta, 'Chengdu · Q-R16 · Hard', 'an ordinary tour singles needs no label')

const lower = formDetail({ result: 'L', opponent: 'Someone A.', score: '6-1, 6-1',
                           event: 'Cancun challenger', round: '1R', surface: 'Hard',
                           level: 'challenger', doubles: true })
assert.equal(lower.line, 'lost to Someone A. · 6-1, 6-1')
assert.equal(lower.meta, 'Cancun challenger · 1R · challenger · doubles · Hard',
  'a Challenger and a doubles result say so — that is why the ladder is in the form')
assert.equal(formDetail(null), null)

console.log('ok — h2hView')
