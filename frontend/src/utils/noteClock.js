/* The clock inside a printed slot note, replaced by the same moment in the
 * reader's zone.
 *
 * Found by its DIGITS and whatever meridiem follows them, not by the stored
 * clock verbatim. start_time_local is usually the note's own substring, but
 * not when the sheet left the meridiem off: SP Open 2026-09-17 printed "NB
 * 2:30 possible court change" and the ingest stores the clock it means,
 * "2:30 PM" (backend oop_parser.settle_meridiems) — so a plain replace found
 * nothing and a "my time" page kept the venue's clock. Matched whole, so 2:30
 * never rewrites the tail of a 12:30. The app's mobile/schedule.js carries the
 * same rule.
 */
export function rewriteNoteClock(note, clock, replacement) {
  const digits = (clock || '').match(/^\d{1,2}[:.]\d{2}/)?.[0]
  if (!digits) return note.replace(clock, replacement)
  const re = new RegExp(`(^|[^\\d:.])${digits.replace('.', '\\.')}(?:\\s*[AP]\\.?M\\.?)?(?!\\d)`, 'i')
  return note.replace(re, (_m, lead) => lead + replacement)
}
