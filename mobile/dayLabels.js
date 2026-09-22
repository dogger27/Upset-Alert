/* Day labels for the schedule's strip: Q1, Q2 … for the sheet days before
 * the first main-draw singles match, then 1, 2 … from that day to the last
 * sheet published.
 *
 * The list is the days that EXIST — a day with no sheet is not in it — so
 * a blank Sunday between the last qualifying round and day 1 is skipped,
 * not counted, and the numbers still run without a gap. A Slam's third
 * qualifying round spread over two days is Q3 and Q4: each chip is a day,
 * not a round. Day 1 unknown (no main-draw sheet yet): every day is a
 * main-draw day, numbered from 1. */
/* `todayIso` FLAGS TODAY rather than the strip working it out, because the
 * label and the flag are one answer about one day and belong in one place —
 * and this module is already the one that knows what a day is called.
 *
 * The label is still built for every day even though the strip now draws dots
 * (owner, 2026-09-21): it is what the accessibility label says, so "Q1" and
 * "Day 3" survive losing their glyphs. */
export function dayLabels(dates, mainStart, todayIso = null) {
  const out = []
  let q = 0, d = 0
  for (const date of dates || []) {
    const qual = mainStart != null && date < mainStart
    out.push({ date, label: qual ? `Q${++q}` : String(++d), isToday: date === todayIso })
  }
  return out
}

/* The chosen day's name in the strip's right slot: a word for the three days a
 * reader has one for — "Yday", "Today", "Tmrw" — and the date for every other.
 * The owner's wording, and short enough for the slot (2026-09-17; tomorrow
 * added and yesterday shortened to match it, 2026-09-20).
 *
 * Both dates are plain YYYY-MM-DD in the DEVICE's calendar (the schedule's
 * rule: the zone is the device), so this is arithmetic on days with no zones
 * in it. The shift is done at NOON UTC deliberately: at midnight a daylight
 * saving change can land the result on the wrong side of the date line. */
export function relativeDayWord(iso, todayIso) {
  if (!iso || !todayIso) return null
  if (iso === todayIso) return 'Today'
  const shifted = (days) => {
    const t = new Date(todayIso + 'T12:00:00Z')
    t.setUTCDate(t.getUTCDate() + days)
    return t.toISOString().slice(0, 10)
  }
  if (iso === shifted(-1)) return 'Yday'
  if (iso === shifted(1)) return 'Tmrw'
  return null
}


/* THE WIDEST WORD THE RIGHT SLOT WILL HOLD over the days on offer.
 *
 * The slot is sized by its content, so the rule between it and the chips
 * moved every time the word did — "Today" out to "Sep 15" and back as the
 * reader swiped, which is a line jumping sideways under their thumb (owner,
 * 2026-09-22). Sizing it to the widest word the CURRENT RANGE can show pins
 * the rule until the range itself changes.
 *
 * Returns the label, not a width: the caller owns the font, and a test can
 * then assert which word was chosen without measuring anything.
 *
 * `active` is included because the slot shows the CHOSEN day, and that day is
 * not always in `dates` — a day with no sheet still says which day it is.
 */
export function widestDayWord(dates, todayIso, shortDateOf, active = null) {
  const words = []
  for (const iso of [...(dates || []), active]) {
    if (!iso) continue
    words.push(relativeDayWord(iso, todayIso) ?? shortDateOf(iso))
  }
  if (!words.length) return ''
  // Longest by CHARACTERS is not longest by pixels, but it is the right
  // shortlist: the caller measures the one this returns, and every candidate
  // here is either a fixed word or "Mmm D" / "Mmm DD", so the character count
  // and the width agree except between two same-length strings — where the
  // difference is a point or two and the padding covers it.
  return words.reduce((a, b) => (b.length > a.length ? b : a))
}
