// node scrubGeometry.test.mjs — the scrub's arithmetic, checked against the
// bracket's own structure. Run by `npm test`.
import assert from 'node:assert/strict'
import {
  anchorY, boxOffset, contentHeightAt, rowIndexAt, rowShift, scrollLimitAt, settleTarget,
  COMMIT_PX, FLICK_PX_PER_S,
} from './scrubGeometry.js'

const P = 12, H = 100, G = 114   // paddingTop, a group's height, group pitch
const E = 33                     // half the distance between a group's two boxes
const centre = (i, s) => P + H / 2 + i * G + rowShift(i, s, G, E)
const near = (a, b, msg) => assert.ok(Math.abs(a - b) < 1e-9, `${msg}: ${a} vs ${b}`)

// At rest nothing moves; past a round either way the shift saturates.
for (let i = 0; i < 8; i++) {
  assert.equal(rowShift(i, 0, G, E), 0)
  assert.equal(rowShift(i, 1, G, E), rowShift(i, 3, G, E))
  assert.equal(rowShift(i, -1, G, E), rowShift(i, -2, G, E))
}

// Condensed: rows 2k and 2k+1 land on row k's TOP and BOTTOM box.
for (let k = 0; k < 4; k++) {
  near(centre(2 * k, 1), centre(k, 0) - E, `row ${2 * k} condenses onto ${k}'s top box`)
  near(centre(2 * k + 1, 1), centre(k, 0) + E, `row ${2 * k + 1} condenses onto ${k}'s bottom box`)
}

// The boxes: settled e apart from the centre; spread to G/2, so they sit on
// the feeders' centres; condensed to nothing.
assert.equal(boxOffset(0, G, E), E)
near(boxOffset(-1, G, E), G / 2, 'spread boxes sit a full pitch apart')
assert.equal(boxOffset(1, G, E), 0)
assert.equal(boxOffset(-3, G, E), boxOffset(-1, G, E))

// Spread: row k opens onto the midpoint of rows 2k and 2k+1.
for (let k = 0; k < 4; k++) {
  near(centre(k, -1), (centre(2 * k, 0) + centre(2 * k + 1, 0)) / 2, `row ${k} spreads onto its feeders`)
}

// COHERENCE, the property that keeps the bracket true mid-gesture: at every
// pos between two rounds, the incoming successor k sits exactly on the
// midpoint of its two condensing feeders in the outgoing column — and more
// than that, its TOP box sits on feeder 2k's centre and its BOTTOM box on
// feeder 2k+1's, so the feed lines run straight into the boxes throughout.
for (const t of [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1]) {
  for (let k = 0; k < 4; k++) {
    const feeders = (centre(2 * k, t) + centre(2 * k + 1, t)) / 2
    near(centre(k, t - 1), feeders, `successor ${k} rides its feeders at t=${t}`)
    const off = boxOffset(t - 1, G, E)
    near(centre(k, t - 1) - off, centre(2 * k, t), `successor ${k}'s top box is on feeder ${2 * k} at t=${t}`)
    near(centre(k, t - 1) + off, centre(2 * k + 1, t), `successor ${k}'s bottom box is on feeder ${2 * k + 1} at t=${t}`)
  }
}

// THE ANCHOR: a finger on row i (integer or not) is held where that row is.
for (const idx of [0, 1, 2.5, 3, 3.4, 6, 7]) {
  for (const s of [-1, -0.6, -0.2, 0, 0.3, 0.7, 1]) {
    // For integer rows the anchor IS the row's moving centre.
    if (Number.isInteger(idx)) near(anchorY(idx, s, P, H, G, E), centre(idx, s), `anchor holds row ${idx} at s=${s}`)
    // For fractional ones it lies between the two rows either side, moving
    // linearly with them.
    else {
      const lo = Math.floor(idx), f = idx - lo
      near(anchorY(idx, s, P, H, G, E), centre(lo, s) * (1 - f) + centre(lo + 1, s) * f,
           `anchor ${idx} interpolates its neighbours at s=${s}`)
    }
  }
}
// The index round-trips: the finger's content y names an index whose anchor
// at rest is that y, and it is clamped to the rows that exist.
near(anchorY(rowIndexAt(P + H / 2 + 2.3 * G, P, H, G, 8), 0, P, H, G, E), P + H / 2 + 2.3 * G, 'index round-trips')
assert.equal(rowIndexAt(-500, P, H, G, 8), 0)
assert.equal(rowIndexAt(1e6, P, H, G, 8), 7)
assert.equal(rowIndexAt(300, P, H, G, 0), 0)

// Heights and limits: the taller column while between rounds, the landed
// column's own at an integer — and the limit is continuous through both.
const heights = [0, 2000, 1000, 500]
assert.equal(contentHeightAt(2, heights, 800), 1000)
assert.equal(contentHeightAt(2.5, heights, 800), 1000)
assert.equal(contentHeightAt(1.5, heights, 800), 2000)
assert.equal(contentHeightAt(0.5, heights, 800), 2000)   // unmeasured column: fallback loses to a real one
assert.equal(contentHeightAt(0, heights, 800), 800)
near(scrollLimitAt(2, heights, 800, 600), 400, 'limit at an integer is that column\'s')
near(scrollLimitAt(3, heights, 800, 600), 0, 'a short column cannot scroll')
near(scrollLimitAt(2.5, heights, 800, 600), 200, 'limit blends between neighbours')
near(scrollLimitAt(2.999, heights, 800, 600), 0.4, 'limit is continuous into the landing')

// Release rules. pos in rounds, r0 the round the drag started on, lo/hi the
// draw's first and last round index.
const T = (pos, r0, vx, drag) => settleTarget(pos, r0, vx, drag, 0, 6)
assert.equal(T(2, 2, 0, 0), 2, 'no movement settles home')
assert.equal(T(2.6, 2, 0, 170), 3, 'past halfway lands')
assert.equal(T(1.4, 2, 0, -170), 1, 'past halfway back lands back')
assert.equal(T(2.2, 2, 0, 60), 3, `a slow drag of ${COMMIT_PX}px counts`)
assert.equal(T(2.1, 2, 0, 30), 2, 'a nudge does not')
assert.equal(T(2.2, 2, 200, 60), 2, 'a slow drag already coming back settles home')
assert.equal(T(2.2, 2, -100, 60), 3, 'still going forward lands')
assert.equal(T(2.1, 2, -FLICK_PX_PER_S, 20), 3, 'a flick lands however short')
assert.equal(T(1.9, 2, -FLICK_PX_PER_S, -20), 2, 'a flick back across the origin settles home')
assert.equal(T(2.7, 2, FLICK_PX_PER_S, 200), 2, 'a flick the other way past halfway comes home')
assert.equal(settleTarget(6.4, 6, -900, 100, 0, 6), 6, 'the last round has nothing past it')
assert.equal(settleTarget(-0.4, 0, 900, -100, 0, 6), 0, 'nor the first before it')
assert.equal(settleTarget(2.9, 2, -900, 300, 0, 6), 3, 'never more than one round per swipe')

console.log('scrubGeometry: ok')
