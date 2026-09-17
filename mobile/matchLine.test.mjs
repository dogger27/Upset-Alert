/* node matchLine.test.mjs */
import assert from 'node:assert/strict'
import { matchLine, sideSurnames } from './matchLine.js'

const P = (side, entry_name) => ({ side, entry_name })
const singles = (a, b, extra = {}) => ({ discipline: 'singles', round_label: 'R128', status: 'scheduled',
  players: [P('a', a), P('b', b)], ...extra })

// Still to play: sheet order, "vs", no score.
let l = matchLine(singles('Francisco Comesaña', 'Flavio Cobolli'))
assert.equal(l.names, 'Comesaña vs Cobolli'); assert.equal(l.score, ''); assert.equal(l.decided, false)
assert.equal(l.round, 'R128')

// Decided: the winner first, "def.", the sets on one line with the loser's tiebreak.
l = matchLine(singles('Francisco Comesaña', 'Flavio Cobolli', {
  status: 'completed', winner_side: 1, scores: [['6', '6', '3', '4', '4'], ['3', '2', '6', '6', '6']] }))
assert.equal(l.names, 'Cobolli def. Comesaña'); assert.equal(l.decided, true)
// Side b won, so the sets read from Cobolli's side.
assert.equal(l.score, '3-6 2-6 6-3 6-4 6-4')
l = matchLine(singles('Gabriela Knutson', 'Eva Lys', { status: 'completed', winner_side: 1, scores: [['3', '3'], ['6', '6']] }))
assert.equal(l.names, 'Lys def. Knutson'); assert.equal(l.score, '6-3 6-3')
// A side-a winner's sets are already in the right order — and a tiebreak stays with its loser.
l = matchLine(singles('Alexander Zverev', 'Lorenzo Sonego', { status: 'completed', winner_side: 0, scores: [['6', '3', '6(7)', '7', '6'], ['4', '6', '7(9)', '5', '4']] }))
assert.equal(l.score, '6-4 3-6 6⁷-7 7-5 6-4')
l = matchLine(singles('Dane Sweeny', 'Corentin Moutet', {
  status: 'completed', winner_side: 0, scores: [['7(7)', '6', '3r'], ['6(4)', '4', '0']] }))
assert.equal(l.names, 'Sweeny def. Moutet')
assert.ok(l.score.startsWith('7-6'), l.score)
assert.ok(l.score.endsWith('(ret.)'), l.score)

// Particles stay with the surname.
assert.equal(sideSurnames([P('a', 'Juan Martín del Potro')], 'a'), 'del Potro')

// Doubles: slashes between the surnames, both sides.
const doubles = { discipline: 'doubles', round_label: 'SF', status: 'scheduled',
  players: [P('a', 'Su-Wei Hsieh'), P('a', 'Jelena Ostapenko'), P('b', 'Julia Kempen'), P('b', 'Alexandra Panova')] }
l = matchLine(doubles)
assert.equal(l.names, 'Hsieh/Ostape vs Kempen/Panova'); assert.equal(l.round, 'SF')
// Six letters of each doubles surname; singles keeps the whole name.
assert.equal(sideSurnames([P('a', 'Timea Babos'), P('a', 'Kristina Mladenovic')], 'a'), 'Babos/Mladen')
assert.equal(sideSurnames([P('a', 'Kristina Mladenovic')], 'a'), 'Mladenovic')

// A walkover is decided, and says so where the score goes.
l = matchLine(singles('Marta Kostyuk', 'Taylor Townsend', { status: 'completed', winner_side: 0, scores: [['w/o'], ['']] }))
assert.equal(l.names, 'Kostyuk def. Townsend'); assert.equal(l.score, 'walkover')

// A live match: "vs", and the sets so far.
l = matchLine(singles('Madison Keys', 'Alina Korneeva', { status: 'live', live_scores: [['7', '3'], ['5', '2']] }))
assert.equal(l.names, 'Keys vs Korneeva'); assert.equal(l.score, '7-5 3-2')

// A side not yet known.
assert.equal(matchLine(singles('Madison Keys', undefined, { players: [P('a', 'Madison Keys')] })).names, 'Keys vs TBD')
console.log('ok — matchLine')
