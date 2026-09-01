import { nameForms, pairForms } from './names.js'

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

console.log(fail ? `\n${fail} failed` : '\n  all passed')
process.exit(fail ? 1 : 0)
