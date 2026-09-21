// node frontend/src/utils/flags.test.mjs
//
// The sheet-name reader every schedule card, popup and pick table goes
// through. Each case is a name a real sheet printed and this function once
// got wrong.
import assert from 'node:assert/strict'
import { nationalityIso2, seedMark, splitPlayerName } from './flags.js'

let failed = 0
function check(label, fn) {
  try { fn(); console.log(`ok   ${label}`) } catch (e) { failed++; console.log(`FAIL ${label}\n     ${e.message}`) }
}
const last = raw => splitPlayerName(raw).last

check('caps surname, trailing country', () => {
  assert.equal(last('Nuno BORGES POR'), 'BORGES')
  assert.equal(splitPlayerName('Nuno BORGES POR').nat, 'POR')
})
check('three-letter surname is not a country', () => assert.equal(last('Orlando LUZ'), 'LUZ'))
check('every trailing capital stripped', () => {
  const r = splitPlayerName('[6] Dhakshineswar SURESH IND ANY')
  assert.equal(r.last, 'SURESH')
  assert.equal(r.nat, 'IND')
})
check('multi-word caps surname', () => assert.equal(last('David VEGA HERNANDEZ'), 'VEGA HERNANDEZ'))
check('bracket spelling reads the last word', () => {
  const r = splitPlayerName('Frances Tiafoe')
  assert.deepEqual([r.first, r.last], ['Frances', 'Tiafoe'])
})

// Guadalajara 2026-09-16: the WTA's abbreviated teams in an OR slot. "C." is
// uppercase and was taken for the surname, so the "or" line printed every
// printed name and ran off the card.
check('an initial is not a surname', () => {
  const r = splitPlayerName('C. Bucsa')
  assert.deepEqual([r.first, r.last], ['C.', 'Bucsa'])
})
check('an initial before a caps surname', () => {
  const r = splitPlayerName('C. BUCSA')
  assert.deepEqual([r.first, r.last], ['C.', 'BUCSA'])
})
check('hyphenated initials are initials', () => assert.equal(last('J.-L. STRUFF'), 'STRUFF'))
check('abbreviated team reads two surnames', () => {
  assert.equal(last('C. Bucsa / N. Melichar-Martinez'), 'Bucsa / Melichar-Martinez')
  assert.equal(last('S. Cabezas Dominguez / M. Gomez Pezuela Cano'), 'Dominguez / Cano')
})
check('caps team still reads its surnames', () =>
  assert.equal(last('[1] ARRIBAGE FRA / GUINARD FRA'), 'ARRIBAGE / GUINARD'))

check('Singapore under either code (WTA Singapore Open, 2026-09-19)', () => {
  const r = splitPlayerName('[WC] Eva Marie DESVIGNES SGP')
  assert.deepEqual([r.last, r.nat], ['DESVIGNES', 'SGP'])
  assert.equal(nationalityIso2('SGP'), 'SG')
  assert.equal(nationalityIso2('SIN'), 'SG')
})

/* Korea Open 2026-09-22 (doc 383): the sheet printed "[WC] [1] Jelena
   OSTAPENKO LAT", the API sent seed 1, and the card read "OSTAPENKO [1]" — the
   field's number replaced the whole printed mark and the wild card went with it. */
check('a seed from the field keeps the sheet\'s entry tag', () => {
  const printed = splitPlayerName('[WC] [1] Jelena OSTAPENKO LAT').seed
  assert.equal(seedMark(printed, 1), '[WC] [1]')
  assert.equal(seedMark('[1] [WC]', 1), '[WC] [1]')
})
check('the field\'s number wins over the sheet\'s', () => {
  assert.equal(seedMark('[17]', 15), '[15]')
  assert.equal(seedMark(null, 4), '[4]')
})
check('no field: the printed mark as it stands', () => {
  assert.equal(seedMark('[Q]', null), '[Q]')
  assert.equal(seedMark('[WC] [2]', undefined), '[WC] [2]')
  assert.equal(seedMark(null, null), null)
})

if (failed) { console.log(`\n${failed} failed`); process.exit(1) }
console.log('\nall passed')
