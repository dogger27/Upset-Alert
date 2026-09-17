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

/* Does the printed note carry a clock of its own?
 *
 * Not when the clock was printed over the BLANK box above the slot: SP Open
 * 2026-09-17 left QUADRA 2's first box empty under "Starting at 12:00 PM" and
 * printed the court's first match "Followed by". The ingest hands the noon
 * down to that match (backend oop_parser._carried_clock) and start_note keeps
 * "Followed by" — so a line built from the note alone says "Followed by" on a
 * court's opener, followed by nothing, with no time. Where the note has no
 * clock and the row has one, the clock is the line. mobile/schedule.js keeps
 * the same rule.
 */
export function noteHasClock(note) {
  return /\d{1,2}[:.]\d{2}/.test(note || '')
}
