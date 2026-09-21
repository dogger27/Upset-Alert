import { fitPillSize, textWidth } from './measure.js'
let fail = 0
const ok = (label, cond, detail = '') => { if (!cond) fail++; console.log(`  ${cond ? 'ok ' : 'FAIL'} ${label} ${detail}`) }

const w = (s, f = 'Archivo_500Medium', z = 15) => textWidth(s, f, z)
ok('empty is zero', w('') === 0)
ok('longer is wider', w('Basavareddy') > w('Basavareddy'.slice(0, 5)))
ok('bold is wider than medium', w('Cerúndolo', 'Archivo_700Bold') > w('Cerúndolo', 'Archivo_500Medium'))
ok('scales with size', Math.abs(w('Monfils', 'Archivo_500Medium', 30) / w('Monfils', 'Archivo_500Medium', 15) - 2) < 1e-9)
// Sanity against reality: 15pt Archivo Medium averages ~8.4pt per letter, so a
// 19-character name should land in the 130-170pt band, not 50 or 400.
const full = w('Nishesh Basavareddy')
ok('plausible absolute width', full > 130 && full < 170, `(${full.toFixed(1)}pt)`)
// A three-digit badge at 11pt bold must fit a 26pt inner box at scale 1.
const badge = w('112', 'Archivo_700Bold', 11)
ok('three digits fit the badge', badge < 26, `(${badge.toFixed(1)}pt)`)
// Diacritics have real widths, not fallbacks — ú is not narrower than u.
ok('diacritics measured', w('ú') >= w('u'))
/* THE TITLE FACE IS IN THE TABLES. An unknown family falls back to Archivo
   silently, and Saira Condensed is ~34% narrower — so the dashboard's title,
   which shrinks itself to the width this reports, would shrink to fit room it
   already had. This fails if the generator is ever re-run without it. */
const saira = w('Guadalajara Open', 'SairaCondensed_700Bold', 19)
const archivo = w('Guadalajara Open', 'Archivo_500Medium', 19)
ok('condensed title face measured, not fallen back', saira < archivo * 0.85,
   `(${saira.toFixed(1)}pt vs ${archivo.toFixed(1)}pt)`)
/* ── fitPillSize ─────────────────────────────────────────────────────────
 * The Schedule's tournament pills must fit on ONE line (owner, 2026-09-21),
 * and share one text size while doing it.
 */
const PILLS = [
  { name: 'Chengdu', tier: '250' }, { name: 'Hangzhou', tier: '250' },
  { name: 'Korea', tier: '250' }, { name: 'SP', tier: '500' },
  { name: 'Singapore', tier: '500' },
]
const FIT = { family: 'Archivo_700Bold', size: 11, chrome: 30, gap: 6, min: 7 }
const fit = (pills, avail, over = {}) =>
  fitPillSize(pills, { ...FIT, ...over, avail })

// The row this was asked for: five pills on a 390pt phone, ~360pt of content.
const five = fit(PILLS, 360)
ok('five pills shrink to fit a phone', five < 11 && five > 7, `(${five.toFixed(2)}pt)`)

// Having actually fitted is the whole point, so check the arithmetic closes.
const widthAt = (pills, size, o = FIT) => pills.reduce((sum, p) => sum + Math.max(
  textWidth(p.name, o.family, size), textWidth(p.tier, o.family, size * 0.8),
) + o.chrome, 0) + o.gap * (pills.length - 1)
ok('the fitted row really fits', widthAt(PILLS, five) <= 360 + 1e-6,
   `(${widthAt(PILLS, five).toFixed(1)} <= 360)`)

// Room to spare keeps the intended size: never inflate to fill the bar.
ok('never larger than asked', fit(PILLS, 4000) === 11)
ok('two pills on a wide bar stay at size', fit(PILLS.slice(0, 2), 4000) === 11)

// The floor holds even when the width is absurd, so text never vanishes.
ok('floored, not vanished', fit(PILLS, 10) === 7)
ok('a negative room still floors', fit(PILLS, -100) === 7)

// A pill is as wide as the WIDER of its two lines: "SP" under "1000" is
// measured by the NUMBER, so a short name cannot let the row overflow. At a
// width tight enough for either to bind, the one carrying the number must
// come out smaller.
const withNum = fit([{ name: 'SP', tier: '1000' }], 45)
const noNum = fit([{ name: 'SP', tier: '' }], 45)
ok('the wider of the two lines drives the pill', withNum < noNum,
   `(with 1000: ${withNum.toFixed(2)}pt, without: ${noNum.toFixed(2)}pt)`)

// Degenerate input must not divide by zero or return NaN.
ok('no pills, no change', fit([], 360) === 11)
ok('null pills, no change', fit(null, 360) === 11)
ok('no width, no change', fitPillSize(PILLS, { ...FIT, avail: 0 }) === 11)
ok('empty labels do not divide by zero',
   Number.isFinite(fit([{ name: '', tier: '' }], 360)))

console.log(fail ? `\n${fail} failed` : '\n  all passed'); process.exit(fail ? 1 : 0)
