/* node seedDeps.test.mjs — the wizard must stay answerable.

   THE INCIDENT (owner, 2026-09-23): "It's not letting me change from 2 sets
   to 3 sets." The duration ceiling had just become a function of the set
   count — the far end of the track is the longest match of the length being
   predicted — and the effect that SEEDS the set count still listed that
   ceiling as a dependency. So tapping 3 moved the ceiling, the ceiling re-ran
   the seeder, and the seeder put the answer back to 2. The control looked
   broken; nothing was, except a dependency array.

   A unit test cannot press the button, but it can read the source: an effect
   that assigns an answer must not depend on anything derived from that
   answer. Both clients are checked, because both had it.
*/
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

/* The dependency array of the useEffect that contains `setSets(`. */
function seedDeps(src) {
  const at = src.indexOf('setSets(')
  assert.ok(at > 0, 'no setSets call found — has the wizard been renamed?')
  const close = src.indexOf('}, [', at)
  assert.ok(close > 0, 'the seeding effect has no dependency array')
  const end = src.indexOf('])', close)
  return src.slice(close + 4, end).split(',').map(s => s.trim()).filter(Boolean)
}

for (const [label, path] of [
  ['mobile', new URL('./finalGuess.jsx', import.meta.url)],
  ['web', new URL('../frontend/src/components/FinalGuessModal.jsx', import.meta.url)],
]) {
  const src = readFileSync(path, 'utf8')
  const deps = seedDeps(src)

  // The trap is only a trap while this holds — if the ceiling stops depending
  // on the answer, this test has stopped describing the code and should be
  // read again rather than deleted.
  assert.match(src, /duration_max_by_sets\?\.\[String\(sets\)\]/,
    `${label}: the duration ceiling no longer reads the set count`)

  for (const derived of ['durMax', 'acesMax', 'sets']) {
    assert.ok(!deps.includes(derived),
      `${label}: the effect that seeds the answers depends on ${derived}, ` +
      `which is derived from an answer it sets — that is the 2-sets-to-3 bug`)
  }
  assert.ok(deps.length >= 1 && /^(data|ctx)$/.test(deps[0]),
    `${label}: the seeding should run once per draw, not per ${deps[0]}`)
}

console.log('ok — seedDeps')
