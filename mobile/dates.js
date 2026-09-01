/*
 * "Sep 21 – 27" / "Sep 28 – Oct 4".
 *
 * The month is repeated only when it changes, which is what keeps the range on
 * one line beside a city and a surface pill — the web card's meta row wraps
 * otherwise, and what wraps is the date, where it reads as a separate fact
 * rather than the third item in a summary.
 */

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function parts(iso) {
  if (!iso) return null
  const [y, m, d] = iso.split('-').map(Number)
  if (!y || !m || !d) return null
  return { m: MONTHS[m - 1], d }
}

export function dateRange(t) {
  const a = parts(t?.start_date)
  const b = parts(t?.end_date)
  if (!a && !b) return ''
  if (!b) return `${a.m} ${a.d}`
  if (!a) return `${b.m} ${b.d}`
  return a.m === b.m ? `${a.m} ${a.d} – ${b.d}` : `${a.m} ${a.d} – ${b.m} ${b.d}`
}
