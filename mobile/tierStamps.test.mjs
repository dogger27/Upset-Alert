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

/* THE TWO TOURS ARE ONE LINE. Both stamps carry the ATP's numerals — the WTA
   draws its own condensed, and stretching them to match was tried and did not
   survive the phone — and the WTA wordmark is fitted to the ATP wordmark's
   exact box. So the only thing the pair does not share is the shape of three
   letters, and their lines, plates and margins must come out identical. A
   difference of even a percent here means the generator's last pass silently
   stopped pairing them. */
for (const tier of TIERS) {
  const a = pngSize(FILES.atp(tier)), w = pngSize(FILES.wta(tier))
  ok(`${tier}: both tours are the same line`, a.w === w.w && a.h === w.h,
     `(atp ${a.w}x${a.h}, wta ${w.w}x${w.h})`)
}

console.log(fail ? `\n${fail} failed` : '\n  all passed')
process.exit(fail ? 1 : 0)
