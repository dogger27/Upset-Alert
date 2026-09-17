/* node swipeDay.test.mjs */
import assert from 'node:assert/strict'
import { SWIPE_PX, SWIPE_VX, swipeStep } from './swipeDay.js'

// A drag left past the distance turns to the next day; right, the one before.
assert.equal(swipeStep(-SWIPE_PX, 0), 1)
assert.equal(swipeStep(SWIPE_PX, 0), -1)
// A flick that did not travel far enough still counts.
assert.equal(swipeStep(-20, -SWIPE_VX), 1)
assert.equal(swipeStep(20, SWIPE_VX), -1)
// Under both thresholds — or a drag that came back — is nothing.
assert.equal(swipeStep(-SWIPE_PX + 1, -SWIPE_VX + 1), 0)
assert.equal(swipeStep(0, 0), 0)
// Distance wins over a contrary residual velocity at release.
assert.equal(swipeStep(-120, 50), 1)
console.log('ok — swipeDay')
