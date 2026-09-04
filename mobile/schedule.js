/*
 * Reading one line of an order-of-play sheet.
 *
 * THREE SOURCES OF SCORE, IN PRIORITY ORDER, and they are not interchangeable:
 *
 *   live_point   Sofascore. Games AND the current point (40-30). Best.
 *   live_scores  ESPN. Games only — it has no point to give, so showing "0-0"
 *                would confidently invent love-all through an entire game.
 *   scores       the final result, once the match is over.
 *
 * Everything here is display-only. Nothing infers a result.
 */
import { properName } from './names'

export function sideName(players, side) {
  const ps = (players || []).filter(p => p.side === side)
  if (!ps.length) return 'TBD'
  // entry_name is proper case; `name` is the sheet's SURNAME IN CAPS. Doubles
  // has two per side, joined the way a scoreboard does.
  return ps.map(p => p.entry_name || properName(p.name) || 'TBD').join(' / ')
}

/* The flag codes for a side, in the order the names are joined — so doubles
   shows both. Deliberately parallel to sideName: if one shows two names, the
   other must offer two flags or they cannot be lined up. */
export function sideFlags(players, side) {
  return (players || []).filter(p => p.side === side).map(p => p.nationality || null)
}

export function sideSeed(players, side) {
  const p = (players || []).find(x => x.side === side && x.seed)
  return p?.seed ?? null
}

/* The inferred seed, for the badge to fall back to. Main-draw singles only —
   the server withholds it for doubles and qualifying, where a draw_entry_id
   points at the player's SINGLES row and any number read off it would describe
   a different event. */
export function sideDrawRank(players, side) {
  const p = (players || []).find(x => x.side === side && x.draw_rank != null)
  return p?.draw_rank ?? null
}

/** [[a games], [b games]] from whichever source has them, or null. */
export function gamesOf(e) {
  if (e?.live_point?.games) return e.live_point.games
  if (Array.isArray(e?.live_scores) && e.live_scores.length >= 2) {
    return [e.live_scores[0], e.live_scores[1]]
  }
  if (e?.scores) return e.scores
  return null
}

/** ["40","30"] while the point is known, else null. Never fabricated. */
export function pointOf(e) {
  const p = e?.live_point?.point
  return Array.isArray(p) && p.length === 2 ? p : null
}

export function servingSide(e) {
  const s = e?.live_point?.serving
    ?? (Array.isArray(e?.live_scores) ? e.live_scores[2] : null)
  return s === 1 ? 'a' : s === 2 ? 'b' : null
}

export function winnerSide(e) {
  if (e?.winner_side === 0) return 'a'
  if (e?.winner_side === 1) return 'b'
  return null
}

/* Live is the SERVER's word. A suspended match is still status 'live' (play
   stopped, score stands), so nothing is lost by trusting it — and a match
   postponed off the day, or carried to a later one, keeps a frozen point with
   the suspended flag on it. Reading that flag as "live" gave a postponed row
   the live border and counted it on the Today tab. */
export function isLive(e) {
  return e?.status === 'live'
}

/* Suspended is a sub-state of live, as the site draws it: the badge only
   swaps wording on a live row. */
export function isSuspended(e) {
  return e?.status === 'live'
    && (e?.live_scores?.[4] === 'suspended' || !!e?.live_point?.suspended)
}

/* When it starts, in the words the sheet used.
   start_note carries the sheet's own phrasing ("Followed By", "Not Before
   2:00 PM") and that is more honest than a clock we computed — those matches
   genuinely have no time. */
/* The site's wording, exactly: "Completed", "Suspended", "In progress", and
   for a match not yet started the sheet's own phrase — "Followed by",
   "Not before 3:00 PM", or the printed time. "Final" and "On court" were this
   app's inventions; two apps naming one state two ways is the kind of drift
   the reader notices without being able to say why. */
/* The site's slot line (Schedule.jsx printedStart / SHORTEN / CANON), ported
   whole. Three display-only rewrites of what the sheet printed — start_note
   itself is kept faithful:
   - the CLOCK inside the line follows the zone switch: "Not before 3:00 PM"
     is the venue's clock, and in "my time" it is rewritten to the reader's or
     the switch moves every estimate and leaves this line on a different
     clock (that was this app's bug: "11:00 AM" above "Wed 8:00 a.m.");
   - wordings too long for a row are shortened;
   - one wording per phrase — "Followed By", "Starts At" and friends vary
     sheet to sheet and would change shape row to row. */
const SHORTEN = [
  [/after\s+suitable\s+rest/i, 'After rest'],
  [/after\s+the\s+(?:conclusion|completion)\s+of[^,]*/i, 'After previous'],
]

function shorten(text) {
  if (!text) return text
  for (const [re, short] of SHORTEN) if (re.test(text)) return text.replace(re, short)
  return text
}

const CANON = [
  [/^followed\s+by$/i, 'Followed by'],
  [/^not\s+before$/i, 'Not before'],
  [/^starts?(?:ing)?\s+at$/i, 'Starting at'],
]

/* The site splits the line into wording and clock and canonicalises the
   wording; this app renders one line, so the two halves are joined again. */
function canon(text) {
  // "a.m." as well as "AM": en-CA and en-AU devices print the dotted form,
  // and a clock the split does not recognise leaves the whole line as
  // wording, so nothing canonicalises and "Starts At" survives.
  const m = (text || '').match(/^(.*?)\s*(~?\d{1,2}[:.]\d{2}\s*(?:[AP]\.?M\.?)?)$/i)
  const label = (m ? m[1] : text || '').trim()
  const time = m ? m[2].trim() : ''
  let out = label
  for (const [re, c] of CANON) if (re.test(label)) { out = c; break }
  return [out, time].filter(Boolean).join(' ')
}

function clockIn(iso, zone) {
  return new Date(iso).toLocaleTimeString([], {
    hour: 'numeric', minute: '2-digit', ...(zone ? { timeZone: zone } : {}),
  })
}

/* Venue mode shows the sheet's line untouched — it is already venue-local. In
   "my time" the wording stays but the clock inside it is rewritten. The
   fallbacks only apply to rows stored before start_note existed; they follow
   the same clock rule, which the site states but only applies to the note. */
function printedStart(e, zone, venueMode) {
  const mine = !venueMode && e.printed_start_at
  if (e.start_note && mine && e.start_time_local) {
    return shorten(e.start_note.replace(e.start_time_local, clockIn(e.printed_start_at, zone)))
  }
  if (e.start_note) return shorten(e.start_note)
  const clock = mine ? clockIn(e.printed_start_at, zone) : e.start_time_local
  if (e.start_type === 'followed_by') return 'Followed by'
  if (e.start_type === 'not_before') return `Not before ${clock ?? ''}`.trim()
  if (e.start_type === 'after_event') return 'After rest'
  if (clock) return clock
  return 'TBA'
}

/* zone: an IANA name for venue mode, undefined for the device's own. */
export function whenLabel(e, zone, venueMode) {
  if (!e) return ''
  if (e.status === 'completed') return 'Completed'
  // The two halves of a washed-out day, in the site's words: abandoned here,
  // resumed there. Neither is "in progress" and neither is a plan.
  if (e.status === 'postponed') return 'Postponed'
  if (e.status === 'to_be_completed') return 'To be completed'
  if (isSuspended(e)) return 'Suspended'
  if (e.status === 'live') return 'In progress'
  return canon(printedStart(e, zone, venueMode))
}
