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
  const parts = (clock || '').match(/^(\d{1,2})[:.](\d{2})/)
  if (!parts) return note.replace(clock, replacement)
  const [digits, hour, minute] = parts
  // A BARE HOUR is the same moment and not the same text. SP Open 2026-09-18
  // printed "After suitable rest - NB 4pm"; the row stores the canonical
  // "4:00 PM" (backend oop_parser._canonical_clock), so there is no "4:00" in
  // the note to find and a "my time" page kept the venue's clock — the same
  // failure the missing meridiem above caused. On the hour, the hour alone is
  // also the clock, and only ever WITH a meridiem: a lone number in a note is
  // a court or a round far more often than a time.
  const alt = minute === '00' ? `|${hour}\\s*[AP]\\.?M\\.?` : ''
  const re = new RegExp(
    `(^|[^\\d:.])(?:${digits.replace('.', '\\.')}(?:\\s*[AP]\\.?M\\.?)?${alt})(?!\\d)`, 'i')
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
  return /\d{1,2}(?:[:.]\d{2}|\s*[AP]\.?M\.?)/i.test(note || '')
}
