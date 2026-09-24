// A synthetic history through one set: the module is the site's, copied; this
// guards that the copy still reads breaks, sets and the match's end.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { sanitizeSnapshots, timelineMarkers, pointStats } from './scoreTimeline.js'

const snap = (games, point, serving, extra = {}) => ({ games, point, serving, ...extra })

test('a break is a game won off the server, a set is a new column, the end is red', () => {
  const h = [
    snap([['0'], ['0']], ['0', '0'], 1),
    snap([['0'], ['0']], ['0', '40'], 1),
    snap([['0'], ['1']], ['0', '0'], 2),          // side 2 broke side 1
    snap([['0'], ['1']], ['40', '0'], 2),
    snap([['1'], ['1']], ['0', '0'], 1),          // side 1 broke back
    snap([['1', '0'], ['1', '0']], ['0', '0'], 2), // a new column: set over (side... equal games — arbitrary)
  ]
  const m = timelineMarkers(h, { completed: true, winnerSide: 1 })
  assert.deepEqual(m.filter(x => x.kind === 'break').map(x => [x.i, x.side]), [[2, 2], [4, 1]])
  assert.equal(m.some(x => x.kind === 'set' && x.i === 5), true)
  assert.deepEqual(m.find(x => x.kind === 'match'), { i: 6, kind: 'match', side: 1 })
})

test('a premature point is erased, not replayed', () => {
  const h = [
    snap([['0'], ['0']], ['0', '30'], 1),
    snap([['0'], ['0']], ['0', '40'], 1),
    snap([['0'], ['0']], ['0', '30'], 1),   // correction: the 0-40 was early
    snap([['0'], ['0']], ['15', '30'], 1),
  ]
  const s = sanitizeSnapshots(h)
  assert.deepEqual(s.map(x => x.point.join('-')), ['0-30', '15-30'])
})

test('point stats credit the server and the returner', () => {
  const h = [
    snap([['0'], ['0']], ['0', '0'], 1),
    snap([['0'], ['0']], ['15', '0'], 1),
    snap([['0'], ['0']], ['15', '15'], 1),
  ]
  const st = pointStats(h)
  const last = st.at[st.at.length - 1]
  assert.equal(last[0].svcWon, 1); assert.equal(last[0].svcTot, 2)
  assert.equal(last[1].retWon, 1); assert.equal(last[1].retTot, 2)
  assert.equal(st.counted, 2)
})

test('a stale read that contradicts minutes of play is dropped, not the play', () => {
  const at = m => new Date(Date.UTC(2026, 8, 6, 22, m)).toISOString()
  const h = [
    snap([['6'], ['7']], ['0', '0'], 1, { at: at(0) }),
    snap([['6', '0'], ['7', '0']], ['15', '0'], 1, { at: at(1) }),
    snap([['6', '0'], ['7', '0']], ['30', '0'], 1, { at: at(2) }),
    snap([['6', '1'], ['7', '0']], ['0', '0'], 2, { at: at(5) }),
    // A cache node's old copy of the set's end, six minutes on: the column
    // count falls, and popping back to agree with it would erase the set.
    snap([['6'], ['7']], ['0', '0'], 1, { at: at(6) }),
  ]
  const s = sanitizeSnapshots(h)
  assert.equal(s.length, 4)
  assert.deepEqual(s[3].games, [['6', '1'], ['7', '0']])
})

test('a correction seconds later still erases the premature point', () => {
  const at = s => new Date(Date.UTC(2026, 8, 6, 22, 0, s)).toISOString()
  const h = [
    snap([['0'], ['0']], ['0', '30'], 1, { at: at(0) }),
    snap([['0'], ['0']], ['0', '40'], 1, { at: at(10) }),
    snap([['0'], ['0']], ['0', '30'], 1, { at: at(20) }),
    snap([['0'], ['0']], ['15', '30'], 1, { at: at(30) }),
  ]
  assert.deepEqual(sanitizeSnapshots(h).map(x => x.point.join('-')), ['0-30', '15-30'])
})

test('a label on a duplicate state survives the duplicate being dropped', () => {
  const h = [
    snap([['0'], ['0']], ['15', '0'], 1),
    snap([['0'], ['0']], ['15', '0'], 1, { point_label: 'Ace' }),
  ]
  const s = sanitizeSnapshots(h)
  assert.equal(s.length, 1)
  assert.equal(s[0].point_label, 'Ace')
})

test('break points: each chance the receiver holds, numbered per game, never in a tiebreak, opt-in', () => {
  const h = [
    snap([['0'], ['0']], ['0', '0'], 1),
    snap([['0'], ['0']], ['15', '40'], 1),    // receiver (2) holds a BP
    snap([['0'], ['0']], ['30', '40'], 1),    // a second chance
    snap([['0'], ['0']], ['40', '40'], 1),
    snap([['0'], ['0']], ['40', 'A'], 1),     // a third
    snap([['0'], ['0']], ['A', '40'], 1),     // game point, not a BP
    snap([['1'], ['0']], ['0', '0'], 2),
    snap([['6'], ['6']], ['3', '6'], 1, { tiebreak: true }),
  ]
  const bp = timelineMarkers(h, { pressurePoints: true }).filter(x => x.kind === 'bp')
  assert.deepEqual(bp.map(x => [x.i, x.side, x.n]), [[1, 2, 1], [2, 2, 2], [4, 2, 3]])
  assert.equal(timelineMarkers(h).some(x => x.kind === 'bp'), false)
})

test('set and match points: numbered per set per player, and across the match', () => {
  const h = [
    snap([['5'], ['3']], ['0', '0'], 1),
    snap([['5'], ['3']], ['40', '15'], 1),        // SP #1 for 1
    snap([['5'], ['3']], ['40', '30'], 1),        // SP #2
    snap([['5'], ['3']], ['40', '40'], 1),
    snap([['5'], ['3']], ['A', '40'], 1),         // SP #3
    snap([['6', '5'], ['3', '4']], ['40', '0'], 1), // set 2, 5-4: MATCH point #1 (best of 3)
    snap([['6', '6'], ['3', '6']], ['6', '5'], 1, { tiebreak: true }), // TB: MP #2 for 1
    snap([['6', '6'], ['3', '6']], ['6', '6'], 2, { tiebreak: true }),
    snap([['6', '6'], ['3', '6']], ['6', '7'], 2, { tiebreak: true }), // side 2 set point in the TB
  ]
  const m = timelineMarkers(h, { pressurePoints: true, bestOf: 3 })
  const pick = k => m.filter(x => x.kind === k).map(x => [x.i, x.side, x.n])
  assert.deepEqual(pick('sp'), [[1, 1, 1], [2, 1, 2], [4, 1, 3], [8, 2, 1]])
  assert.deepEqual(pick('mp'), [[5, 1, 1], [6, 1, 2]])
  assert.deepEqual(pick('bp'), [])   // the server's own chances are not break points
  // best of five: the same 6-3, 5-4 lead is only a set point
  const m5 = timelineMarkers(h, { pressurePoints: true, bestOf: 5 })
  assert.equal(m5.some(x => x.kind === 'mp'), false)
})

test('aces and double faults count per player through the match', () => {
  const h = [
    snap([['0'], ['0']], ['15', '0'], 1, { point_label: 'Ace' }),
    snap([['0'], ['0']], ['30', '0'], 1, { point_label: 'Ace' }),
    snap([['0'], ['1']], ['0', '15'], 2, { point_label: 'Ace' }),
    snap([['0'], ['1']], ['15', '15'], 2, { point_label: 'Double Fault' }),
  ]
  const m = timelineMarkers(h)
  assert.deepEqual(m.filter(x => x.kind === 'ace' || x.kind === 'df').map(x => [x.kind, x.side, x.n]),
    [['ace', 1, 1], ['ace', 1, 2], ['ace', 2, 1], ['df', 2, 1]])
})
