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
