/* node h2hView.test.mjs — the reading of a head-to-head.

   The half that can be wrong without looking wrong. The endpoint answers in
   its own order (slug_a / wins_a) and that order is NOT the order the two
   players appear in the bracket, so a 6-0 record can point at the wrong man
   and look perfectly plausible doing it.
*/
import assert from 'node:assert/strict'
import { ageOf, betterSide, compareRows, eventTitle, roundWord, formChipText, formChips, formDetail, formGrid, onSurface, orient, shortEvent, singlesOnly } from './h2hView.js'

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

/* Five to a row, and the SQUARE is what is measured: they fill the column
   they are given rather than leaving a gap beside the word in the middle. */
assert.deepEqual(formGrid(131), { size: 23, per: 5 }, 'a phone column at ordinary text size')
assert.deepEqual(formGrid(94), { size: 16, per: 5 }, 'narrower squares when large text takes the room')
assert.deepEqual(formGrid(160), { size: 29, per: 5 }, 'a wider phone gets bigger squares, not a wider gap')
assert.deepEqual(formGrid(1000), { size: 30, per: 5 }, 'but a swatch is a mark, not a button')
assert.deepEqual(formGrid(null), { size: 14, per: 5 }, 'before it is measured, the floor')

/* THE COUNT GIVES WAY BEFORE THE SIZE DOES: below about 85 points five
   squares cannot hold a letter, and clamping the size up overflowed the
   column — which is what an 80pt column proved. */
assert.deepEqual(formGrid(80), { size: 17, per: 4 }, 'four bigger squares, not five clipped ones')
/* And it stops at the FIRST count that clears the floor, so a cramped column
   keeps as many results as it can rather than drawing two big squares: the
   information here is the run of results, not the size of the tiles. */
assert.deepEqual(formGrid(50), { size: 14, per: 3 })
for (const w of [50, 60, 70, 80, 94, 105, 118, 131, 160, 300]) {
  const { size, per } = formGrid(w)
  const used = size * per + (per - 1) * 3
  assert.ok(used <= w, `${per} ${size}pt swatches overflow a ${w}pt column`)
  // They fill the column unless the CEILING is what decided the size — on a
  // tablet the row deliberately stops growing and the slack is the point.
  if (size < 30) {
    assert.ok(w - used < per + 1, `${per} ${size}pt swatches leave ${w - used}pt of ${w} empty`)
  }
}
// The letter grows with its box: fixed at 10 it was a dot in a 24pt square.
assert.equal(formChipText(23), 13)
assert.equal(formChipText(14), 9, 'and never smaller than nine, whatever the box')

const full = formChips([
  { result: 'W', opponent: 'Pavlovic L.', score: '6-4, 6-3', event: 'Chengdu',
    round: 'Q-R16', surface: 'Hard', date: '2026-09-22', level: 'tour', doubles: false },
], 10)
assert.equal(full.length, 1)
assert.ok(full[0].match, 'a chip carries its match, because a tap opens it')

const det = formDetail(full[0].match)
assert.equal(det.won, true)
assert.equal(det.line, 'beat Pavlovic L. · 6-4, 6-3')
assert.equal(det.meta, 'Chengdu · Q R16 · Hard', 'an ordinary tour singles needs no rung label')

const lower = formDetail({ result: 'L', opponent: 'Someone A.', score: '6-1, 6-1',
                           event: 'Cancun challenger', round: '1R', surface: 'Hard',
                           level: 'challenger', doubles: true })
assert.equal(lower.line, 'lost to Someone A. · 6-1, 6-1')
assert.equal(lower.meta, 'Cancun · CH · 1R · doubles · Hard',
  'a Challenger and a doubles result still say so — abbreviated, and the rung once')
assert.equal(formDetail(null), null)

/* ── a singles preview shows singles form ───────────────────────────────── */

const mixed = [
  { result: 'W', opponent: 'A', doubles: false },
  { result: 'L', opponent: 'B / C', doubles: true },
  { result: 'W', opponent: 'D', doubles: false },
]
assert.deepEqual(singlesOnly(mixed).map(m => m.opponent), ['A', 'D'],
  'two players\' serve against two others says nothing about a singles match')
assert.deepEqual(singlesOnly(null), [])

/* ── "CH", not "Challenger" ──────────────────────────────────────────────── */

assert.equal(shortEvent('Guangzhou 2 challenger'), 'Guangzhou 2 CH')
assert.equal(shortEvent('Mallorca Challenger'), 'Mallorca CH', 'whatever the case')
assert.equal(shortEvent('US Open'), 'US Open', 'and nothing else is touched')
assert.equal(shortEvent(null), '')

/* THE RUNG IS A FIELD AND THE NAME GIVES IT UP (owner: "when we already put
   'challenger' in the tournament type, remove it completely from the
   tournament title"). TE writes it into both. */
assert.equal(eventTitle('Guangzhou 2 challenger'), 'Guangzhou 2')
assert.equal(eventTitle('Mallorca Challenger'), 'Mallorca')
assert.equal(eventTitle('ITF M15 Cancun'), 'M15 Cancun',
  'both rung words, and what is left is the part the rung does not say')
assert.equal(eventTitle('US Open'), 'US Open')

const ch = formDetail({ result: 'W', opponent: 'Sesko Z.', score: '6-4, 6-2',
                        event: 'Mallorca challenger', round: '1R', surface: 'Hard',
                        level: 'challenger', doubles: false })
assert.equal(ch.meta, 'Mallorca · CH · 1R · Hard', 'the type sits with the tournament')

const itf = formDetail({ result: 'L', opponent: 'X Y.', score: '6-0, 6-0',
                         event: 'ITF M15 Cancun', round: 'QF', surface: 'Hard',
                         level: 'itf', doubles: false })
assert.equal(itf.meta, 'M15 Cancun · ITF · QF · Hard', 'and is never said twice')

const tour = formDetail({ result: 'W', opponent: 'Sonego L.', score: '7-5, 6-3',
                          event: 'Winston Salem', round: 'R16', surface: 'Hard',
                          level: 'tour', doubles: false })
assert.equal(tour.meta, 'Winston Salem · R16 · Hard', 'the tour needs no label')

/* A rung we hold NO level for keeps the word in its name, abbreviated —
   stripping it there would quietly promote a Challenger to the tour. */
const unknown = formDetail({ result: 'W', opponent: 'A B.', score: '6-1, 6-1',
                             event: 'Cancun challenger', round: '1R', surface: 'Hard',
                             level: null, doubles: false })
assert.equal(unknown.meta, 'Cancun CH · 1R · Hard')

/* ── the round, in the app's words and not the source's ─────────────────── */

assert.equal(roundWord('Q-R16'), 'Q R16', 'the owner: "WTF is Q-R16??"')
assert.equal(roundWord('Q-QF'), 'Q QF')
assert.equal(roundWord('Q-F'), 'Q final')
assert.equal(roundWord('F'), 'final', 'an initial alone reads as an initial')
assert.equal(roundWord('R16'), 'R16', 'and what the app already says is left alone')
assert.equal(roundWord('1R'), '1R')
assert.equal(roundWord(''), '')
assert.equal(roundWord(null), '')

/* WHERE TE NUMBERS THE ROUND, the number is used — it is stated. */
assert.equal(roundWord('Q-1R'), 'Q1')
assert.equal(roundWord('Q-2R'), 'Q2')

/* WHERE IT NAMES A POSITION, the position is kept. Reading Q-R16 as "Q1" is
   right for a sixteen-player qualifying draw and wrong for a thirty-two, and
   a form row does not carry the draw size — so it says how deep and nothing
   it cannot know. */
assert.notEqual(roundWord('Q-R16'), 'Q1')

console.log('ok — h2hView')
