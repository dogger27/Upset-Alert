import assert from 'node:assert/strict'
import { MIN_THUMB, barRange, thumbSize } from './scrollBar.js'

/* Nothing to scroll: no bar. */
assert.equal(thumbSize({ viewH: 400, contentH: 400 }), 0, 'content that fits draws nothing')
assert.equal(thumbSize({ viewH: 400, contentH: 300 }), 0, 'content shorter than the pane draws nothing')
assert.equal(thumbSize({ viewH: 400, contentH: 401 }), 0, 'a rounding fraction is not a scroll')
assert.equal(thumbSize({ viewH: 0, contentH: 900 }), 0, 'an unmeasured pane draws nothing')

/* The thumb is the share of the content on screen. */
assert.equal(thumbSize({ viewH: 400, contentH: 800 }), 200, 'half the content, half the track')
assert.equal(thumbSize({ viewH: 300, contentH: 1200 }), 75, 'a quarter on screen, a quarter of the track')

/* …until that share is too small to see, when it is floored instead. */
assert.equal(thumbSize({ viewH: 200, contentH: 40000 }), MIN_THUMB, 'a very long page keeps a grabbable thumb')

/* The travel is measured from the thumb ACTUALLY drawn, so a floored thumb
   still reaches the bottom of its track rather than overshooting it. */
const floored = thumbSize({ viewH: 200, contentH: 40000 })
assert.deepEqual(barRange({ viewH: 200, contentH: 40000, thumb: floored }),
                 { max: 39800, travel: 200 - MIN_THUMB }, 'a floored thumb travels the rest of the track')
assert.deepEqual(barRange({ viewH: 400, contentH: 800, thumb: 200 }),
                 { max: 400, travel: 200 }, 'half a track of travel for half a page of scroll')

/* The divisor is never zero, whatever it is handed. */
assert.equal(barRange({ viewH: 400, contentH: 400, thumb: 0 }).max, 1, 'max is never zero')
assert.equal(barRange({ viewH: 100, contentH: 200, thumb: 400 }).travel, 0, 'a thumb bigger than its track does not travel backwards')

console.log('ok   scrollBar.test.mjs')
