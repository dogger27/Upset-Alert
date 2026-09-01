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


/* ── Expected start ──────────────────────────────────────────────────────────
 *
 * Ported VERBATIM from frontend/src/utils/score.jsx::expectedStartLabel. Every
 * decision in it is load-bearing and none of it is obvious:
 *
 *   - estimates round to five minutes, so a chained guess never claims "8:12";
 *   - the tilde marks an estimate, so it cannot read as an announced time;
 *   - "Today"/"Tomorrow" are decided IN THE ZONE BEING DISPLAYED, or a late
 *     match reads "Today" to one reader and "Tomorrow" to another;
 *   - the zone is always named, including the reader's own, and is resolved by
 *     Intl so it tracks daylight saving rather than being stored;
 *   - formatters are cached per zone because building them per label cost
 *     ~30ms a frame on the site's bracket.
 *
 * Re-deriving any of that would have got it subtly wrong, which is why this is
 * a copy and not a rewrite. Hermes supports Intl on iOS, so it runs as-is.
 */
const FIVE_MIN = 5 * 60 * 1000

/* EVERY FORMATTER HERE IS BUILT ONCE PER ZONE, NOT PER LABEL.
 *
 * toLocaleTimeString / toLocaleDateString construct an Intl formatter on each
 * call whenever options are passed — ~90-140µs apiece. This function needs
 * five of them (the time, the day of the match, the day today, sometimes the
 * day tomorrow, and the zone abbreviation), so a single label cost the best
 * part of half a millisecond. CombinedView renders one for every undecided
 * match on screen and re-renders on every live-score nudge, which put ~30ms of
 * pure date formatting into a frame that had nothing else to do.
 *
 * Keyed by zone because that is the only input that varies — the option bags
 * are fixed. Undefined (the reader's own zone) gets its own entry under ''.
 */
const _fmt = new Map()
function formatter(kind, zone) {
  const key = `${kind}\u0000${zone ?? ''}`
  let f = _fmt.get(key)
  if (f === undefined) {
    const tz = zone ? { timeZone: zone } : {}
    f = kind === 'time'
      ? new Intl.DateTimeFormat([], { hour: 'numeric', minute: '2-digit', ...tz })
      : kind === 'day'
        ? new Intl.DateTimeFormat('en-CA', tz)
        : kind === 'weekday'
          ? new Intl.DateTimeFormat([], { weekday: 'short', ...tz })
          : new Intl.DateTimeFormat('en-US', { timeZoneName: 'short', ...tz })
    _fmt.set(key, f)
  }
  return f
}

export function expectedStartLabel(iso, source, zone) {
  if (!iso) return null
  let when = new Date(iso)
  if (Number.isNaN(when.getTime())) return null

  // Round estimates to five minutes, as the schedule does. A guess chained from
  // constant match lengths has no business claiming "8:12" — the precision is
  // invented, and showing it invites more trust than it has earned. A printed
  // time keeps whatever the tournament stated.
  if (source !== 'printed') {
    when = new Date(Math.round(when.getTime() / FIVE_MIN) * FIVE_MIN)
  }

  const time = formatter('time', zone).format(when)

  // Compare calendar days in the SAME zone the time is being shown in —
  // otherwise a late match reads "Today" to one reader and "Tomorrow" to
  // another looking at the identical row.
  const dayFmt = formatter('day', zone)
  const dayOf = (d) => dayFmt.format(d)
  const today = dayOf(new Date())
  const thatDay = dayOf(when)

  let prefix
  if (thatDay === today) {
    prefix = 'Today'
  } else {
    const tomorrow = new Date()
    tomorrow.setDate(tomorrow.getDate() + 1)
    prefix = thatDay === dayOf(tomorrow)
      ? 'Tomorrow'
      : formatter('weekday', zone).format(when)
  }

  // Always name the zone, including the reader's own. A bare time forces the
  // question "whose clock is that?" on anyone who has ever switched the
  // setting, and the answer is only obvious to someone who has not.
  //
  // Resolved by Intl rather than stored, so it tracks daylight saving on its
  // own: the same venue is EDT in August and EST in November, and a fixed
  // abbreviation would be wrong for half the season.
  let suffix = ''
  {
    const parts = formatter('tz', zone).formatToParts(when)
    const tzName = parts.find(p => p.type === 'timeZoneName')?.value
    if (tzName) suffix = ` ${tzName}`
  }

  const hedge = source === 'printed' ? '' : '~'
  return `${prefix} at ${hedge}${time}${suffix}`
}
