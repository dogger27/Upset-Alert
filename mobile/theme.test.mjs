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

/* ANCHORED TO THIS FILE, NOT THE SHELL'S CWD. `walk('.')` scanned whatever
 * directory the runner happened to be in: from mobile/ that is right, but from
 * the repo root it walks the WEB app too, where `R` is a local array of rounds
 * and `R.length` reads as a missing token. It reported two every time and was
 * therefore permanently red from the root — which is how a real failure hides,
 * so the check now scans the mobile tree wherever it is invoked from. */
const ROOT = new URL('.', import.meta.url).pathname

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
for (const file of walk(ROOT)) {
  const src = readFileSync(file, 'utf8')
  for (const ns of NAMESPACES) {
    // C.foo but not C.foo( and not a longer identifier ending in C
    const re = new RegExp(`(?<![A-Za-z0-9_$.])${ns}\\.([A-Za-z_$][A-Za-z0-9_$]*)`, 'g')
    for (const m of src.matchAll(re)) {
      if (!known[ns].has(m[1])) {
        const line = src.slice(0, m.index).split('\n').length
        bad.push(`mobile/${file.slice(ROOT.length)}:${line}  ${ns}.${m[1]}`)
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
  /* THE CONTROL PAIR IS A BUTTON AND ITS LABEL. `text` is the fill of an
     available control and `plate` the label on it (see the skin in cards.jsx),
     so the two have to clear AA against EACH OTHER — a pairing nothing else
     in this palette was checking, because until the cards were tinted the
     only filled control was C.raised with a green label. */
  const pair = ratio(t.plate, t.text)
  if (pair < 4.5) {
    bad.push(`theme.js  TOUR.${key} control pair ${t.text} / ${t.plate} is `
             + `${pair.toFixed(2)}:1 — a filled Schedule pill and its label, under 4.5:1`)
  }
  /* AND IT HAS TO GO THE RIGHT WAY OFF THE CARD. The available control is a
     RECESSED chip and the unavailable one is lifted; if `plate` ever went
     lighter than `card` the two states would swap polarity and the pill with a
     sheet behind it would be the one that looks empty. Direction, not
     magnitude — the chip's shape comes from its border, because on the neutral
     card the fill is only 1.17:1 off and there is nowhere darker to go. */
  if (lum(t.plate) >= lum(t.card)) {
    bad.push(`theme.js  TOUR.${key} control fill ${t.plate} is no darker than its card `
             + `${t.card} — the pressable state is the recessed one`)
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
