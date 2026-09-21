/*
 * Run EVERY *.test.mjs in this directory.
 *
 *     npm test
 *
 * WHY THIS EXISTS. `npm test` used to be a hand-written chain of
 * `node a.test.mjs && node b.test.mjs && …`, and on 2026-09-21 it listed 12 of
 * the 29 suites that existed. The other 17 all passed — they had simply never
 * been run since somebody forgot to add them, and nothing said so. A change to
 * dayLabels.js broke dayLabels.test.mjs that day and `npm test` stayed green;
 * the break was found by running that file by hand.
 *
 * A chain also stops at the first failure, so one red suite hid the state of
 * every suite after it. This runs them all and reports the lot.
 *
 * Discovery, not a list, because a list is the thing that went wrong: a new
 * suite is run the moment it is saved, with nothing to remember.
 */
import { readdirSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const suites = readdirSync(here).filter(f => f.endsWith('.test.mjs')).sort()

const failed = []
for (const f of suites) {
  const r = spawnSync(process.execPath, [join(here, f)],
                      { stdio: ['ignore', 'pipe', 'pipe'], encoding: 'utf8' })
  const ok = r.status === 0
  if (!ok) {
    failed.push(f)
    // Only a failure's output is worth the scrollback; a pass says so in a word.
    process.stdout.write(`\n\x1b[31mFAIL\x1b[0m ${f}\n`)
    process.stdout.write((r.stdout || '').trimEnd() + '\n')
    process.stderr.write((r.stderr || '').trimEnd() + '\n')
  } else {
    process.stdout.write(`  ok   ${f}\n`)
  }
}

console.log(`\n${suites.length - failed.length}/${suites.length} suites passed`
  + (failed.length ? `\nFAILED: ${failed.join(', ')}` : ''))
process.exit(failed.length ? 1 : 0)
