/*
 * Every design token referenced anywhere must actually exist.
 *
 * WHY THIS IS WORTH A TEST: an undefined token is SILENT. `color: C.error`
 * where the palette calls it `bad` does not throw, does not warn, and does not
 * fall back to something readable — React Native renders the default, which is
 * black, on a near-black card. It shipped in six places, including the sign-in
 * screen's error message: someone typing the wrong password saw no feedback at
 * all, and nothing anywhere said why.
 *
 * Deliberately a grep rather than a type system: these files are plain JSX and
 * the check has to be cheap enough to run every time.
 *
 *   node theme.test.mjs
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, extname } from 'node:path'
import * as theme from './theme.js'

const NAMESPACES = ['C', 'T', 'R', 'S', 'BADGE', 'PICK', 'TOUR']
const known = Object.fromEntries(
  NAMESPACES.map(n => [n, new Set(Object.keys(theme[n] ?? {}))]),
)

for (const n of NAMESPACES) {
  if (!theme[n]) { console.error(`theme.js exports no ${n}`); process.exit(1) }
}

function walk(dir, out = []) {
  for (const e of readdirSync(dir)) {
    if (e === 'node_modules' || e === '.expo' || e === 'dist' || e.startsWith('.')) continue
    const p = join(dir, e)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (['.js', '.jsx'].includes(extname(p)) && !p.endsWith('.test.mjs')) out.push(p)
  }
  return out
}

const bad = []
for (const file of walk('.')) {
  const src = readFileSync(file, 'utf8')
  for (const ns of NAMESPACES) {
    // C.foo but not C.foo( and not a longer identifier ending in C
    const re = new RegExp(`(?<![A-Za-z0-9_$.])${ns}\\.([A-Za-z_$][A-Za-z0-9_$]*)`, 'g')
    for (const m of src.matchAll(re)) {
      if (!known[ns].has(m[1])) {
        const line = src.slice(0, m.index).split('\n').length
        bad.push(`${file}:${line}  ${ns}.${m[1]}`)
      }
    }
  }
}

if (bad.length) {
  console.error(`${bad.length} reference(s) to a token that does not exist:\n` +
                bad.map(b => '  ' + b).join('\n'))
  process.exit(1)
}
console.log(`ok — every token reference resolves (${NAMESPACES.map(n => `${n}:${known[n].size}`).join(' ')})`)
