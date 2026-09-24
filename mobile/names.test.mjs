import { nameForms, nameLines, pairForms, sheetName } from './names.js'
import { flagEmoji } from './flags.js'

let fail = 0
const eq = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want)
  if (!ok) fail++
  console.log(`  ${ok ? 'ok ' : 'FAIL'} ${label}`)
  if (!ok) console.log(`       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`)
}

eq('two names', nameForms('Arthur Géa'), ['Arthur Géa', 'A. Géa', 'Géa'])
eq('two given names', nameForms('Juan Manuel Cerúndolo'),
   ['Juan Manuel Cerúndolo', 'J. M. Cerúndolo', 'Cerúndolo'])
eq('particles stay words', nameForms('Botic van de Zandschulp'),
   ['Botic van de Zandschulp', 'B. van de Zandschulp', 'van de Zandschulp'])
eq('single token has no shorter form', nameForms('Monfils'), ['Monfils'])
eq('empty', nameForms(''), [''])
eq('diacritics survive', nameForms('Gaël Monfils'), ['Gaël Monfils', 'G. Monfils', 'Monfils'])
// A rung that saves nothing is dropped: "Bu" -> "B." is the same width, so
// the initials form buys no space and only costs the reader the given name.
eq('a rung that saves nothing is dropped', nameForms('Bu Yunchaokete'),
   ['Bu Yunchaokete', 'Yunchaokete'])
eq('doubles collapse together', pairForms('Jean Julien Rojer / Horia Tecau'),
   ['Jean Julien Rojer / Horia Tecau', 'J. J. Rojer / H. Tecau', 'Rojer / Tecau'])

// Singapore's ISO code, as the WTA's own Singapore Open sheet printed it for
// both wildcards (2026-09-19). sheetName only reads a code the flag table
// knows, so until it did, "SGP" stayed on as the last word of her name.
eq('SGP is a country', sheetName('[WC] Kai Ning Chanya NG SGP'),
   { name: 'Kai Ning Chanya NG', nat: 'SGP' })
eq('SIN and SGP fly the same flag', [flagEmoji('SIN'), flagEmoji('SGP')], ['🇸🇬', '🇸🇬'])
eq('a three-letter surname is still a name', sheetName('Orlando LUZ'),
   { name: 'Orlando LUZ', nat: null })

console.log(fail ? `\n${fail} failed` : '\n  all passed')
process.exit(fail ? 1 : 0)

// Two lines for the H2H headline: particles and a trailing "Jr" stay with the surname.
assert.deepEqual(nameLines('Martin Damm Jr'), ['Martin', 'Damm Jr'])
assert.deepEqual(nameLines('Botic van de Zandschulp'), ['Botic', 'van de Zandschulp'])
assert.deepEqual(nameLines('Shintaro Mochizuki'), ['Shintaro', 'Mochizuki'])
assert.deepEqual(nameLines('Alex de Minaur'), ['Alex', 'de Minaur'])
assert.deepEqual(nameLines('Rafa'), ['', 'Rafa'])
assert.deepEqual(nameLines(null), ['', ''])
