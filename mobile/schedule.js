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
import { properName, sheetName } from './names.js'

export function sideName(players, side) {
  const ps = (players || []).filter(p => p.side === side)
  if (!ps.length) return 'TBD'
  // entry_name is proper case; `name` is the sheet's string — a seed in
  // brackets, the surname shouting, the IOC code last — so it is stripped of
  // that furniture before the name ladder ever sees it. Doubles has two per
  // side, joined the way a scoreboard does.
  return ps.map(p => p.entry_name || properName(sheetName(p.name).name) || 'TBD').join(' / ')
}

/* The flag codes for a side, in the order the names are joined — so doubles
   shows both. Deliberately parallel to sideName: if one shows two names, the
   other must offer two flags or they cannot be lined up. */
export function sideFlags(players, side) {
  /* The sheet's own IOC code stands in where the server has no nationality:
     it is null on every doubles row (no draw entry to read one off), and the
     printed name carried it all along. An empty box still means "no country
     here" — it just no longer means "we threw it away". */
  return (players || []).filter(p => p.side === side)
    .map(p => p.nationality || sheetName(p.name).nat || null)
}

export function sideSeed(players, side) {
  const p = (players || []).find(x => x.side === side && x.seed)
  return p?.seed ?? null
}

/* HOW THIS SIDE GOT INTO THE DRAW — Q, WC, LL and the rest. The bracket has
   always shown it; the schedule row, which is where a reader first meets a
   name they do not know, did not.

   The FIRST non-null on the side, which is also the only one: a doubles team
   enters as a unit, so both halves carry the team's entry type, and reading
   one of them is reading the pair's. */
export function sideEntryType(players, side) {
  const p = (players || []).find(x => x.side === side && x.entry_type)
  return p?.entry_type ?? null
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

/* WHICH OF THE THREE A ROW IS IN (owner, 2026-09-20): the day's filter switch
   offers Completed, Live and Upcoming, so every row has to land in exactly one
   of them and none may fall through.

   A POSTPONED match leaves with the finished ones — it is off this day's sheet
   and nothing more will happen on it today, which is the same answer a reader
   wants from "Completed" as a finished match. So does a carried one
   ('to_be_completed'): its play on THIS day is over, and it reappears as a
   fresh row on the day it resumes. The old Completed toggle hid postponed rows
   with the finished ones for the same reason.

   Suspended rows stay LIVE, because the server still calls them live and play
   is expected to resume within the day (see isSuspended below). */
export function matchPhase(e) {
  const st = e?.status
  if (st === 'live') return 'live'
  if (st === 'completed' || st === 'postponed' || st === 'to_be_completed') return 'completed'
  return 'upcoming'
}

/* The three in the order the switch shows them, which is the order the day
   happens in: what is done, what is on now, what is still to come. */
export const PHASES = [
  { key: 'completed', label: 'Completed' },
  { key: 'live', label: 'Live' },
  { key: 'upcoming', label: 'Upcoming' },
]

/* {completed, live, upcoming} over whatever the other controls have left. */
export function phaseCounts(entries) {
  const out = { completed: 0, live: 0, upcoming: 0 }
  for (const e of entries || []) out[matchPhase(e)] += 1
  return out
}

/* WHICH SEGMENT IS SELECTED. The reader's own choice while it still has
   matches in it, else what is happening: on court now, then what is coming,
   then the record. A selected-but-empty segment would leave the reader looking
   at an empty list holding a filter they cannot see the effect of — which is
   what happens on its own as the last live match of the day finishes. */
export function effectivePhase(counts, chosen) {
  if (chosen && counts?.[chosen] > 0) return chosen
  return ['live', 'upcoming', 'completed'].find(k => counts?.[k] > 0) || null
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
/* The clock inside the note, found by its DIGITS and whatever meridiem follows
   them. start_time_local is usually the note's own substring, but not when the
   sheet left the meridiem off: SP Open 2026-09-17 printed "NB 2:30 possible
   court change" and the ingest stores the clock it means, "2:30 PM"
   (backend oop_parser.settle_meridiems). Matched whole, so 2:30 never
   rewrites the tail of a 12:30. Same rule as the site's utils/noteClock.js. */
/* A BARE HOUR is the same moment and not the same text: SP Open 2026-09-18
   printed "After suitable rest - NB 4pm" and the row stores the canonical
   "4:00 PM" (backend oop_parser._canonical_clock). Only ever with a meridiem —
   a lone number in a note is a court or a round far more often than a time. */
function rewriteNoteClock(note, clock, replacement) {
  const parts = (clock || '').match(/^(\d{1,2})[:.](\d{2})/)
  if (!parts) return note.replace(clock, replacement)
  const [digits, hour, minute] = parts
  const alt = minute === '00' ? `|${hour}\\s*[AP]\\.?M\\.?` : ''
  const re = new RegExp(
    `(^|[^\\d:.])(?:${digits.replace('.', '\\.')}(?:\\s*[AP]\\.?M\\.?)?${alt})(?!\\d)`, 'i')
  return note.replace(re, (_m, lead) => lead + replacement)
}

function printedStart(e, zone, venueMode) {
  const mine = !venueMode && e.printed_start_at
  // A clock handed down from a BLANK box above is not in the note: SP Open
  // 2026-09-17 printed QUADRA 2's opener "Followed by" under an empty
  // "Starting at 12:00 PM" box, and the ingest keeps the noon on the row
  // (backend oop_parser._carried_clock). The note alone would print no time.
  // Same rule as the site's utils/noteClock.js noteHasClock.
  if (e.start_note && e.start_time_local
      && !/\d{1,2}(?:[:.]\d{2}|\s*[AP]\.?M\.?)/i.test(e.start_note)) {
    return mine ? clockIn(e.printed_start_at, zone) : e.start_time_local
  }
  if (e.start_note && mine && e.start_time_local) {
    return shorten(rewriteNoteClock(e.start_note, e.start_time_local, clockIn(e.printed_start_at, zone)))
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

/* THE COMPACT LIST'S CLOCK — footTime's ladder without its silence. A row
   that is one line has nothing but this column to say when, and "when did it
   start" is still the first thing on the line once a match is on or over:
   the hour it began if it has, else the expected start (estimated or
   printed), else the sheet's own wording. Always a clock rather than
   "Followed by", because one column cannot carry a phrase; the wording that
   would have shown is returned as `displaced` for the accessibility label. */
/* JUST THE CLOCK (owner, 2026-09-17): rowClock's text without the ladder's
   phrases — "Started at", "Resumed at", "Not before" — or the "~" of an
   estimate. The dense views print this and nothing else. */
export function rowWhen(e, zone, venueMode) {
  return String(rowClock(e, zone, venueMode).text || '').replace(/^[A-Za-z][A-Za-z ]* at /, '').replace(/^Not before /i, '').replace(/^~+/, '')
}

export function rowClock(e, zone, venueMode) {
  if (!e) return { text: '', estimated: false, displaced: null }
  const started = startedLine(e, zone)
  // "In progress" is the ladder's word for a live match with no known start —
  // a status, not a clock. This column falls through to the sheet's time.
  if (started && started !== 'In progress') return { ...stripScaffolding(started), estimated: false }
  const bare = stripScaffolding(expectedStart(e, zone, venueMode))
  if (bare.text) {
    return { text: bare.text, estimated: e.expected_source === 'estimated',
             displaced: estimateSupersedes(e) ? canon(printedStart(e, zone, venueMode)) : bare.displaced }
  }
  return { ...stripScaffolding(canon(printedStart(e, zone, venueMode))), estimated: false }
}

/* The STATUS, and only the status — the site's pill block, which draws
   nothing at all on a row that has not started (pages/Schedule.jsx). This used
   to fall through to the printed start, so a scheduled row announced its time
   twice: once here and again on the line below. */
/* An entry dressed as a MATCH, for the predictors sheet.
 *
 * The inverse of scoreHistory's entryFromMatch, and needed for the same
 * reason: the two surfaces describe one match through two shapes, and the
 * sheet was written against the draw page's. Only rows with a bracket match
 * have anyone to report — doubles and qualifying carry no picks.
 *
 * Sides here are the SHEET's order, which need not be the bracket's. That only
 * reaches the "X vs. Y" caption; everything the sheet actually fetches is
 * keyed on the match id.
 */
export function matchFromEntry(e) {
  if (!e?.match_id) return null
  const players = e.players || []
  const a = players.find(p => p.side === 'a')
  const b = players.find(p => p.side === 'b')
  const nameOf = (p) => (p ? { name: p.entry_name || p.name } : null)
  const won = e.winner_side == null ? null : (e.winner_side === 0 ? a : b)
  return {
    id: e.match_id,
    // Carried ON the object: a schedule day mixes the men's draw and the
    // women's, so there is no single draw id the page could supply.
    draw_id: e.draw_id,
    // The sheet's round pill reads `round_name`; a schedule row spells the
    // same thing `round_label`, already in the compact form a pill wants
    // ("R16"). Without this the pill had nothing and drew a bare dash.
    round_name: e.round_label,
    player1: nameOf(a),
    player2: nameOf(b),
    winner: nameOf(won),
    live_scores: e.live_scores || null,
    live_point: e.live_point || null,
  }
}

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

/*
 * The Time view as a chronology of the day — the site's rule exactly
 * (frontend/src/utils/dayOrder.js). Sort on the same instant the row DISPLAYS:
 * when a match actually began, else the estimate — or a match that went on
 * late sits among the slots it was printed beside while its own row says
 * "Started at" some quite different time. A match carried over from yesterday
 * keeps yesterday's started_at (that is what the field means), so it is keyed
 * on when it comes back today: resumed_at once it has, the slot it is due in
 * until then.
 *
 * A row with no time at all goes LAST. Guadalajara 2026-09-17 printed its
 * doubles SF "Time TBA - After suitable rest" with nothing ahead of it on its
 * court, so it had no estimate; an empty key sorts before every instant and
 * listed the one match nobody can time above the 1:00 PM opener.
 */
/* STARTED ABOVE NOT STARTED (owner, 2026-09-17): in the dense views a
   match that is on court or over rises above the ones still waiting, each
   half keeping its chronology. Live is the server's word (a suspended match
   is still 'live'); a carried match waits with the rest. Stable. */
export function hasStarted(e) {
  return e?.status === 'live' || e?.status === 'completed'
}

export function startedFirst(entries) {
  return [...entries.filter(hasStarted), ...entries.filter(e => !hasStarted(e))]
}

export function byTimeOfDay(entries) {
  const key = e => {
    if (e.resumed_at) return e.resumed_at
    if (e.status === 'to_be_completed') return e.expected_start_at || null
    return e.started_at || e.expected_start_at || null
  }
  return [...entries].sort((a, b) => {
    const ka = key(a), kb = key(b)
    if ((ka == null) !== (kb == null)) return ka == null ? 1 : -1
    if (ka !== kb) return ka < kb ? -1 : 1
    // Same instant, or both unknown: keep a court's own running order intact.
    return (a.court || '').localeCompare(b.court || '')
      || (a.court_order ?? 99) - (b.court_order ?? 99)
  })
}
