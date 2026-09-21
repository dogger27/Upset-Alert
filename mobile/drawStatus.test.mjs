/*
 * THE PORT IS STILL A PORT.
 *
 *   node drawStatus.test.mjs
 *
 * drawStatus.js is copied verbatim from frontend/src/utils/drawStatus.js, and
 * its own header says the web one is right if they ever differ. Nothing
 * enforced that. Which bucket a draw belongs in is a product rule with real
 * edge cases — an event's finished half staying Active, "Last Week" being one
 * week rather than one event, the Pacific-midnight boundary — and two
 * implementations would disagree the first time either was touched, putting
 * the same tournament in different places on the phone and the website.
 *
 * So this suite does not test the behaviour: that lives beside the canonical
 * copy, in frontend/src/utils/drawStatus.test.mjs, where the rules are. It
 * tests that this file IS that file.
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const here = readFileSync(new URL('./drawStatus.js', import.meta.url), 'utf8')
const web = readFileSync(
  new URL('../frontend/src/utils/drawStatus.js', import.meta.url), 'utf8')

/* Everything from the first export onward: the header above it is this copy's
   own, and is the only licensed difference. */
const body = s => s.slice(s.indexOf('const ONE_DAY_MS'))

assert.ok(body(here).length > 500, 'the ported body is missing or unrecognisable')
assert.equal(body(here), body(web),
  'mobile/drawStatus.js has drifted from frontend/src/utils/drawStatus.js — '
  + 'the web copy is the canonical one; port it across rather than editing here')

console.log('ok — drawStatus is still a verbatim port of the web rule')
