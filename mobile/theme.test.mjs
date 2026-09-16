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

/* A CARD-SKINNING TOUR MUST CARRY ITS OWN INK, AND THE INK MUST READ ON IT.
 *
 * The grep above proves `TOUR.M` exists; it cannot see that `TOUR.M.faint` is
 * missing, and a missing one is the same silent failure one level down —
 * `color: undefined` renders black, here on a mid-blue card.
 *
 * The contrast floors are the other half, and they are what actually broke:
 * the C.* ramp was authored against the near-black card and reused verbatim
 * when the cards were tinted, which left C.faint at 2.77:1 on the ATP card
 * (see the derivation in theme.js). Lightening a tint or deepening an ink
 * without the other is the mistake this catches — the numbers stop agreeing
 * before anyone looks at a phone.
 */
const SURFACE_KEYS = ['card', 'plate', 'line', 'text', 'ink', 'inkBody', 'muted', 'faint', 'rule']
// WCAG 2.x relative luminance. sRGB in, 0..1 out.
const lum = hex => {
  const ch = i => {
    const c = parseInt(hex.slice(1 + i * 2, 3 + i * 2), 16) / 255
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * ch(0) + 0.7152 * ch(1) + 0.0722 * ch(2)
}
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p)
  return (x + 0.05) / (y + 0.05)
}
// ink is held at the 7:1 the palette claims (6.88 measured — the floor allows
// for rounding); the rest are the AA text floors the ramp was lifted back to.
const FLOOR = { ink: 6.5, inkBody: 4.5, muted: 4.5, faint: 4.0 }

for (const [key, t] of Object.entries(theme.TOUR)) {
  if (!t.card) continue                 // TOUR.X names a tour but skins no card
  for (const k of SURFACE_KEYS) {
    if (!t[k]) bad.push(`theme.js  TOUR.${key} skins a card but has no ${k}`)
  }
  if (SURFACE_KEYS.some(k => !t[k])) continue
  for (const [k, floor] of Object.entries(FLOOR)) {
    const r = ratio(t[k], t.card)
    if (r < floor) {
      bad.push(`theme.js  TOUR.${key}.${k} ${t[k]} is ${r.toFixed(2)}:1 on its own `
               + `card ${t.card} — under ${floor}:1`)
    }
  }
  /* THE HAIRLINE LIFTS OFF ITS CARD. C.border is lighter than C.card, so the
     footer's rule reads as a seam catching the light; the tinted cards used to
     borrow `plate` for it, which is darker than the card and therefore a
     groove cut into it — the same detail with its sign flipped. */
  if (lum(t.rule) <= lum(t.card)) {
    bad.push(`theme.js  TOUR.${key}.rule ${t.rule} is no lighter than its card ${t.card} `
             + `— a hairline that cuts in rather than lifts off`)
  }
}
if (lum(theme.C.border) <= lum(theme.C.card)) {
  bad.push('theme.js  C.border is no lighter than C.card — the rule above assumes it is')
}

if (bad.length) {
  console.error(`${bad.length} reference(s) to a token that does not exist:\n` +
                bad.map(b => '  ' + b).join('\n'))
  process.exit(1)
}
console.log(`ok — every token reference resolves (${NAMESPACES.map(n => `${n}:${known[n].size}`).join(' ')})`)
