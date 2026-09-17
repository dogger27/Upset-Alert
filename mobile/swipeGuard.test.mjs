/* node swipeGuard.test.mjs */
import assert from 'node:assert/strict'
import { beginSwipe, endSwipe, swiping, unlessSwiping } from './swipeGuard.js'

assert.equal(swiping(), false)
beginSwipe(); assert.equal(swiping(), true)
endSwipe()
assert.equal(swiping(), true)                       // a beat after the release, still a swipe
assert.equal(swiping(Date.now() + 251), false)      // then a tap is a tap again
let opened = 0
const open = unlessSwiping(() => { opened += 1 })
beginSwipe(); open(); assert.equal(opened, 0)
endSwipe(); open(); assert.equal(opened, 0)
until_after(); open(); assert.equal(opened, 1)
function until_after() { const t = Date.now() + 300; while (Date.now() < t) { /* wait out the window */ } }
console.log('ok — swipeGuard')
