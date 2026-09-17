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

/* The chosen day's name in the strip's right slot: "Today" and "Yester." for
 * the two days a reader has a word for, the date for every other — the
 * owner's wording, short enough for the slot (2026-09-17). Both dates are
 * plain YYYY-MM-DD in the DEVICE's calendar (the schedule's rule: the zone
 * is the device), so this is string arithmetic on days, no zones involved. */
export function relativeDayWord(iso, todayIso) {
  if (!iso || !todayIso) return null
  if (iso === todayIso) return 'Today'
  const t = new Date(todayIso + 'T12:00:00Z')
  t.setUTCDate(t.getUTCDate() - 1)
  if (iso === t.toISOString().slice(0, 10)) return 'Yester.'
  return null
}
