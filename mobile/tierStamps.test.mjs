/*
 * The generated aspect ratios must match the artwork they describe.
 *
 * WHY THIS IS WORTH A TEST: TierBadge draws each tier stamp CAP tall and
 * `aspect x CAP` wide, so these six numbers ARE the badge's geometry. It
 * cannot ask the runtime for them (Image.resolveAssetSource exists on iOS but
 * not in react-native-web, where it red-boxed the harness), so they are
 * generated into tierStampAspect.js — and a generated file next to the thing
 * it describes is a file that can silently fall out of step with it. Re-crop
 * one PNG by hand, or run the generator and commit only half of what it
 * writes, and the stamp stretches or letterboxes on the phone with nothing
 * anywhere saying why.
 *
 * Read straight from the PNG header rather than from a library: width and
 * height are two big-endian 32-bit integers at a fixed offset in IHDR, which
 * is always the first chunk.
 *
 *   node tierStamps.test.mjs
 */
import { readFileSync } from 'node:fs'
import ASPECT from './tierStampAspect.js'

const FILES = {
  atp: t => `assets/logos/atp-${t}-inline.png`,
  wta: t => `assets/logos/${t}k-tag-plate.png`,
}
const TIERS = ['250', '500', '1000']

function pngSize(path) {
  const b = readFileSync(path)
  if (b.readUInt32BE(0) !== 0x89504e47) throw new Error(`${path} is not a PNG`)
  if (b.toString('ascii', 12, 16) !== 'IHDR') throw new Error(`${path}: no IHDR first`)
  return { w: b.readUInt32BE(16), h: b.readUInt32BE(20) }
}

let fail = 0
const ok = (label, cond, detail = '') => {
  if (!cond) fail++
  console.log(`  ${cond ? 'ok ' : 'FAIL'} ${label} ${detail}`)
}

for (const tour of ['atp', 'wta']) {
  for (const tier of TIERS) {
    const path = FILES[tour](tier)
    const { w, h } = pngSize(path)
    const real = w / h
    const said = ASPECT[tour][tier]
    ok(`${tour} ${tier} aspect`, said != null && Math.abs(real - said) / real < 0.01,
       `(art ${w}x${h} = ${real.toFixed(3)}, table says ${said})`)
  }
}

// One cap height across both tours is the whole point of the generator's last
// pass, and it is what makes "aspect x CAP" a fair width: every stamp is
// cropped to lettering of the SAME height, so the heights must agree exactly.
const heights = new Set()
for (const tour of ['atp', 'wta']) for (const t of TIERS) heights.add(pngSize(FILES[tour](t)).h)
ok('one cap height across all six', heights.size === 1, `(${[...heights].join(', ')}px)`)

// The tier number is set to the same width on both tours (a condensed WTA
// numeral against a wide ATP italic reads as the smaller of the two at equal
// height), so a WTA line differs from its ATP twin only by its wordmark.
for (const tier of TIERS) {
  const d = ASPECT.atp[tier] - ASPECT.wta[tier]
  ok(`${tier}: WTA line is narrower only by its wordmark`, d > 0.5 && d < 1.3,
     `(atp ${ASPECT.atp[tier]} - wta ${ASPECT.wta[tier]} = ${d.toFixed(2)})`)
}

console.log(fail ? `\n${fail} failed` : '\n  all passed')
process.exit(fail ? 1 : 0)
