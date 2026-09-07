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

/* The site's startedLine, ported whole (pages/Schedule.jsx). Only a match on
   court or finished names a start; a resumed one names the time it came BACK,
   because started_at is the first point and does not move — a match suspended
   overnight still started yesterday. */
function startedLine(e, zone) {
  if (e.status !== 'live' && e.status !== 'completed') return null
  if (e.resumed_at && (!e.started_at || new Date(e.resumed_at) > new Date(e.started_at))) {
    return `Resumed at ${clockIn(e.resumed_at, zone)}`
  }
  // A RECONSTRUCTED start wears the tilde every other estimate here wears.
  // We did not see this one begin; the time is the finish less the playing
  // time, good to about five minutes. Saying it plainly is the point — the
  // alternative was printing the scheduled slot as though it were observed.
  if (e.started_at) {
    const t = clockIn(e.started_at, zone)
    return `Started at ${e.started_estimated ? '~' : ''}${t}`
  }
  // started_at comes from the live feeds, which never saw doubles, qualifying,
  // or anything already under way when we began recording. The match has
  // demonstrably started though, so keep the printed time and fix the TENSE:
  // "Starting at 11:00 AM" on a finished match is the one thing it must not say.
  if (e.printed_start_at && e.start_type === 'fixed') {
    return `Started at ${clockIn(e.printed_start_at, zone)}`
  }
  // A FINISHED match says nothing rather than guessing — the pill already says
  // Completed, and "In progress" beside it would contradict it.
  return e.status === 'completed' ? null : 'In progress'
}

const FIVE_MIN = 5 * 60 * 1000

/* Estimates are hedged with a tilde so they never read as announced, and
   rounded to five minutes — a guess chained from average match lengths has no
   business reporting "4:27". Printed times are left exactly as stated. */
function expectedStart(e, zone, venueMode) {
  if (!e.expected_start_at) return printedStart(e, zone, venueMode)
  const printed = e.expected_source === 'printed'
  let d = new Date(e.expected_start_at)
  if (!printed) d = new Date(Math.round(d.getTime() / FIVE_MIN) * FIVE_MIN)
  const t = d.toLocaleTimeString([], {
    hour: 'numeric', minute: '2-digit', ...(zone ? { timeZone: zone } : {}),
  })
  return printed ? t : `~${t}`
}

/* Labels that are pure scaffolding in front of a clock. "Started at 8:17 AM",
   "Starting at 4:00 PM" and "Not before 11:00 AM" all reduce to their time;
   the words go to hover, where a reader who wants them can still find them.

   Deliberately NOT here: "Resumed at" says this match came back from a delay,
   which is the whole reason its clock disagrees with the score beside it, and
   "Followed by" places a match in the day's order with no clock of its own to
   fall back on. Those two earn their words.

/* Labels that are pure scaffolding in front of a clock. "Starting at 4:00 PM"
   and "Not before 11:00 AM" both reduce to their time; the words go to hover,
   where a reader who wants them can still find them.

   "STARTED AT" IS NOT AMONG THEM, deliberately, though it was for a while.
   Stripped to a bare clock it becomes ambiguous in the one place it matters:
   on a live or finished row, "8:17 AM" reads exactly like a scheduled slot,
   and the whole point of that line is to say the match REALLY began then
   rather than that it was due to. The tense is the information.

   "Resumed at" stays for the same reason and one more: it explains why its
   clock disagrees with the score beside it. "Followed by" has no clock of its
   own to fall back on. */
const BARE_LABELS = new Set(['Starting at', 'Not before'])

function stripScaffolding(text) {
  const m = (text || '').match(/^(.*?)\s*(~?\d{1,2}[:.]\d{2}\s*(?:[AP]\.?M\.?)?)$/i)
  if (!m) return { text, displaced: null }
  const label = m[1].trim()
  if (!BARE_LABELS.has(label)) return { text, displaced: null }
  return { text: m[2].trim(), displaced: text }
}

/* WHEN WE HAVE AN ESTIMATE, THE ESTIMATE IS THE LINE. The sheet's wording
   answers a different question — "Followed by" and "Not before 9:30 AM" say
   where a match sits in the day's order, not when to turn up — and once a
   chained estimate exists it answers the asked one better on its own.

   The single exception is a "not before" floor, which is a hard constraint
   rather than a guess: a match CANNOT start before it, so an estimate that
   falls below one is impossible and the floor stays. Above it, the floor is no
   longer news. */
function estimateSupersedes(e) {
  if (e.expected_source !== 'estimated' || !e.expected_start_at) return false
  if (e.start_type === 'not_before' && e.printed_start_at
      && new Date(e.expected_start_at) <= new Date(e.printed_start_at)) return false
  return true
}

/* THE SITE'S BOTTOM-LEFT LINE, as one expression:
     startedLine ?? (names its own court ? expectedStart : printedStart)
   `inCourt` is the app's name for a card grouped UNDER its court, which is the
   site's !showCourt — grouped that way the sheet's own wording is shown
   ("Followed by"), and elsewhere the clock, because a card that already names
   its court has no room for a phrase.

   `est` is the chained estimate the site prints BESIDE the wording, and only
   where it adds something: "Followed by" alone does not tell you when to turn
   up, but a slot whose expected time is simply the printed one would repeat
   itself. */
export function footTime(e, zone, venueMode, inCourt) {
  if (!e) return { text: '', estimated: false, displaced: null }

  /* NOTHING AT ALL once a match is on court or over. The status beside it
     already says "In progress" or "Completed", the score says the rest, and
     the hour it began answers a question nobody is asking by then — a reader
     looking at a live row wants to know where the match IS. Falling through to
     the scheduled time would be worse than saying nothing: a finished match
     labelled with the slot it was due in reads as though it had not started. */
  if (e.status === 'live' || e.status === 'completed' || isSuspended(e)) {
    return { text: '', estimated: false, displaced: null }
  }

  /* `displaced` is whatever wording the line no longer shows. The site keeps
     it as hover text; a phone has no hover, so it goes to the accessibility
     label instead. Either way it should not simply vanish — "Followed by"
     says where a match sits in the day's ORDER, and "Started at" tells a
     reader the clock is a fact rather than a plan. */
  const started = startedLine(e, zone)
  if (started) return { ...stripScaffolding(started), estimated: false }

  if (!inCourt || estimateSupersedes(e)) {
    const bare = stripScaffolding(expectedStart(e, zone, venueMode))
    return {
      text: bare.text,
      estimated: e.expected_source === 'estimated',
      displaced: estimateSupersedes(e)
        ? canon(printedStart(e, zone, venueMode))
        : bare.displaced,
    }
  }
  return { ...stripScaffolding(canon(printedStart(e, zone, venueMode))), estimated: false }
}

/* The STATUS, and only the status — the site's pill block, which draws
   nothing at all on a row that has not started (pages/Schedule.jsx). This used
   to fall through to the printed start, so a scheduled row announced its time
   twice: once here and again on the line below. */
export function whenLabel(e) {
  if (!e) return ''
  if (e.status === 'completed') return 'Completed'
  // The two halves of a washed-out day, in the site's words: abandoned here,
  // resumed there. Neither is "in progress" and neither is a plan.
  if (e.status === 'postponed') return 'Postponed'
  if (e.status === 'to_be_completed') return 'To be completed'
  if (isSuspended(e)) return 'Suspended'
  if (e.status === 'live') return 'In progress'
  return ''
}
