// node frontend/src/utils/courtRank.test.mjs
//
// The order the schedule's Court view lists a day's courts in. mobile/
// courtGroups.test.mjs pins the app's twin of the same rule.
import assert from 'node:assert/strict'
import { courtsByRank, seedNumber } from './courtRank.js'

let failed = 0
function check(label, fn) {
  try { fn(); console.log(`ok   ${label}`) } catch (e) { failed++; console.log(`FAIL ${label}\n     ${e.message}`) }
}
const courts = rows => courtsByRank(rows).map(([court]) => court)
const row = (id, court, court_order, stage, names, discipline = 'singles') =>
  ({ id, court, court_order, stage, discipline, players: names.map(name => ({ name })) })

/* Hangzhou, 2026-09-23 (doc 421). CENTER COURT carried two qualifying finals
   and then the day's two main-draw R32s, both unseeded; COURT 1 only
   qualifying finals, one with the qualifying [1]. The sheet prints CENTER
   COURT first; an unseeded player ranking at "no seed" put COURT 1 above it. */
const hangzhou = [
  row(1397, 'CENTER COURT', 1, 'qualifying', ['[2] Alex BOLT AUS', '[8] Akira SANTILLAN JPN']),
  row(1416, 'CENTER COURT', 2, 'qualifying', ['[3] Bernard TOMIC AUS', 'Fajing SUN CHN', '[7] Matthew DELLAVEDOVA AUS']),
  row(1398, 'CENTER COURT', 3, 'main', ['Aleksandar VUKIC AUS', 'Kyrian JACQUET FRA']),
  row(1399, 'CENTER COURT', 4, 'main', ['Valentin ROYER FRA', 'Adam WALTON AUS']),
  row(1415, 'COURT 1', 1, 'qualifying', ['[4] Taro DANIEL JPN', '[6] Hayato MATSUOKA JPN']),
  row(1418, 'COURT 1', 2, 'qualifying', ['[1] Dalibor SVRCINA CZE', '[5] Rio NOGUCHI JPN']),
]
check('an unseeded main-draw match outranks every qualifying seed (Hangzhou)', () => {
  assert.deepEqual(courts(hangzhou), ['CENTER COURT', 'COURT 1'])
})
check('each court keeps its own running order', () => {
  const [[, center]] = courtsByRank([...hangzhou].reverse())
  assert.deepEqual(center.map(e => e.id), [1397, 1416, 1398, 1399])
})

/* Chengdu, 2026-09-23 (doc 408). The Q-final [1] and [3] ranked as if they were
   main-draw seeds and put both qualifying courts above CENTER COURT's [8]. */
check('a qualifying seed ranks below every main-draw seed (Chengdu)', () => {
  assert.deepEqual(courts([
    row(1, 'COURT 1', 1, 'qualifying', ['[2] Alexandre MULLER FRA', '[7] Andre ILAGAN USA']),
    row(2, 'COURT 2', 1, 'qualifying', ['[3] Lloyd HARRIS RSA', '[6] Alexis GALARNEAU CAN']),
    row(3, 'CENTER COURT', 1, 'main', ['[8] Sebastian BAEZ ARG', 'Jenson BROOKSBY USA']),
  ]), ['CENTER COURT', 'COURT 1', 'COURT 2'])
})
check('a qualifying-only day still orders its courts by seed', () => {
  assert.deepEqual(courts([
    row(1, 'COURT 2', 1, 'qualifying', ['[3] A ONE', 'B TWO']),
    row(2, 'COURT 1', 1, 'qualifying', ['[5] C THREE', 'D FOUR']),
    row(3, 'COURT 3', 1, 'qualifying', ['E FIVE', 'F SIX']),
  ]), ['COURT 2', 'COURT 1', 'COURT 3'])
})
check('a doubles seed ranks nothing; a court of doubles only goes last', () => {
  assert.deepEqual(courts([
    row(1, 'COURT 2', 1, 'main', ['[1] A ONE / B TWO', 'C THREE / D FOUR'], 'doubles'),
    row(2, 'COURT 1', 1, 'main', ['E FIVE', 'F SIX']),
  ]), ['COURT 1', 'COURT 2'])
})
check('a seed is read off the name when the API sent none, digits only', () => {
  assert.equal(seedNumber({ name: '[WC] [2] Alex BOLT AUS' }), 2)
  assert.equal(seedNumber({ name: '[WC] Rigele TE CHN' }), null)
  assert.equal(seedNumber({ seed: 4, name: 'Taro DANIEL JPN' }), 4)
})

if (failed) { console.log(`\n${failed} failed`); process.exit(1) }
