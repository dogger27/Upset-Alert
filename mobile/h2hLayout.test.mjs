/* node h2hLayout.test.mjs — the H2H spine holds its content at any text size.

   THE INCIDENT (owner, 2026-09-23, with a screenshot): the middle column read
   "meetings…" and the form chips were cut off against both edges of the sheet.
   Both were the same mistake — a column fixed in POINTS holding content that
   grows with the reader's text setting. On the phone that took the screenshot
   everything inside had grown and the columns had not.

   So the budget is checked here at the scales a reader actually uses, rather
   than at the one the developer happens to have. Run per scale in its own
   process, because FONT_SCALE is read once at module load.
*/
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { FORM_GAP, formChipText, formGrid } from './h2hView.js'

const SRC = readFileSync(new URL('./h2h.jsx', import.meta.url), 'utf8')

/* A swatch is not a line of text: it must not take the text scale, or five of
   them outgrow the column they sit in. */
assert.doesNotMatch(SRC, /^const CHIP = /m,
  'the swatch must be measured from its row, not fixed')
assert.match(SRC, /formGrid\(width\)/,
  'the swatch size must come from the measured width')
assert.doesNotMatch(SRC, /chipText: \{[^}]*fontSize: \d/,
  'the letter grows with its box, so it cannot carry a fixed size')
assert.match(SRC, /width: leading\(74\)/,
  'the label column must grow with the text, or a long label truncates')
assert.doesNotMatch(SRC, /numberOfLines=\{1\}>\{r\.label\}/,
  'the label must shrink through FitText, never truncate')

const PROBE = `
globalThis.__UA_FONT_SCALE = __SCALE__
const { textWidth } = await import('./measure.js')
const { leading } = await import('./fontScale.js')
const spine = 375 - 24 - 16              // a 375pt phone, the sheet's padding, the spine's
const label = leading(74)
const column = (spine - label) / 2
const words = ['meetings', 'record', 'on hard', 'ranking', 'Elo', 'age', 'form']
process.stdout.write(JSON.stringify({
  label,
  longest: Math.max(...words.map(w => textWidth(w, 'Archivo_500Medium', 11))),
  column,
  // "#258" is the widest figure the spine draws: a three-digit Elo place.
  plate: textWidth('#258', 'Archivo_700Bold', 15) + 14 + 2,
  chips: 5 * 18 + 4 * 3,
}))
`

for (const scale of [1, 1.35, 1.7, 2]) {
  const out = execFileSync(process.execPath,
    ['--input-type=module', '-e', PROBE.replace('__SCALE__', String(scale))],
    { cwd: fileURLToPath(new URL('.', import.meta.url)), encoding: 'utf8' })
  const m = JSON.parse(out)
  assert.ok(m.longest <= m.label - 1,
    `at ${scale}x the longest label (${m.longest.toFixed(0)}) does not fit its column (${m.label.toFixed(0)})`)
  assert.ok(m.plate <= m.column,
    `at ${scale}x a three-digit figure (${m.plate.toFixed(0)}) does not fit its column (${m.column.toFixed(0)})`)
  /* Five to a row, sized from the row: what this checks is that they FILL the
     column without overflowing it, at every text size — the gap between the
     squares and the word in the middle is what the owner saw. */
  const { size, per } = formGrid(m.column)
  const used = size * per + (per - 1) * FORM_GAP
  assert.ok(used <= m.column,
    `at ${scale}x ${per} ${size}pt swatches (${used}) overflow their column (${m.column.toFixed(0)})`)
  assert.ok(used >= m.column - per,
    `at ${scale}x they leave ${(m.column - used).toFixed(0)}pt of the column empty`)
  assert.ok(per >= 4, `at ${scale}x a form row is down to ${per} swatches`)
  assert.ok(size >= 14 && formChipText(size) >= 9,
    `at ${scale}x a ${size}pt swatch is too small to hold a letter`)
}

console.log('ok — h2hLayout')
