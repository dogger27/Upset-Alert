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
export function dayLabels(dates, mainStart) {
  const out = []
  let q = 0, d = 0
  for (const date of dates || []) {
    const qual = mainStart != null && date < mainStart
    out.push({ date, label: qual ? `Q${++q}` : String(++d) })
  }
  return out
}

/* The chosen day's name in the strip's right slot: a word for the three days
 * a reader has one for — "Yester.", "Today", "Tmrw" — and the date for every
 * other. The owner's wording, and short enough for the slot (2026-09-17,
 * tomorrow added 2026-09-20).
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
  if (iso === shifted(-1)) return 'Yester.'
  if (iso === shifted(1)) return 'Tmrw'
  return null
}
