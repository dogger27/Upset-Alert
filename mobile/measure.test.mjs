import { textWidth } from './measure.js'
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
console.log(fail ? `\n${fail} failed` : '\n  all passed'); process.exit(fail ? 1 : 0)
