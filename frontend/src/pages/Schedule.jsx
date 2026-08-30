import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useLiveUpdates } from '../hooks/useLiveUpdates'
import useFlashOnChange from '../hooks/useFlashOnChange'
import useScoreEvent from '../hooks/useScoreEvent'
import useServiceBreak from '../hooks/useServiceBreak'
import ChampionFanfare from '../components/ChampionFanfare'
import H2HPanel from '../components/H2HPanel'
import ScoreHistoryPopup from '../components/ScoreHistoryPopup'
import MatchScoreCard from '../components/MatchScoreCard'
import { useSearchParams, Link } from 'react-router-dom'
import clsx from 'clsx'
import { listTournaments } from '../api/tournaments'
import { getScheduleDay, getScheduleDates } from '../api/schedule'
import { updateMe } from '../api/auth'
import { getPredictions } from '../api/predictions'
import { useAuth } from '../store/auth'
import { nationalityIso2, splitPlayerName } from '../utils/flags'
import { rootFontPx, textWidth } from '../utils/text'
import { parseSet } from '../utils/score'
import './Schedule.css'

const VIEW_KEY = 'ua-schedule-view'
const TZ_KEY = 'ua-schedule-tz'

// Venue time by default: the sheet prints venue local, so showing anything else
// puts our estimates on a different clock from the times beside them.
//
// localStorage is a CACHE, not the record. The preference lives on the account
// (users.schedule_tz) so it follows a reader from phone to desktop — same
// arrangement as the theme — but the account value is unknown until /auth/me
// returns, and the page must render before then without flipping clocks.
function storedTz() {
  try { return localStorage.getItem(TZ_KEY) === 'user' ? 'user' : 'venue' }
  catch { return 'venue' }
}

// Time view is the default: a flat list needs no horizontal space, which is
// what makes it the workable one on a phone. Whichever view is used last wins
// next time.
function storedView() {
  try {
    return localStorage.getItem(VIEW_KEY) === 'court' ? 'court' : 'time'
  } catch { return 'time' }
}

function isoDay(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function prettyDay(iso) {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: 'short', month: 'short', day: 'numeric',
  })
}

/** The sheet's own wording, verbatim — the whole point of the court view.
 *
 * Prefer what was actually printed. Deriving a label from start_type meant
 * inventing phrasing the sheet never used — "After preceding" where it plainly
 * said "After suitable rest" — and every new wording needed another branch. The
 * fallbacks below only apply to rows stored before start_note existed. */
/* Split a slot line into its wording and its clock time.
 *
 * "Started 9:44 AM" wrapped as "Started 9:44" / "AM" in a narrow column — the
 * time itself broken in half. Rendering the label and the time as separate
 * lines, with the time kept whole, means a wrap can only ever happen where it
 * makes sense.
 */
function splitTimeLine(text) {
  if (!text) return { label: '', time: '' }
  const m = text.match(/^(.*?)\s*(~?\d{1,2}[:.]\d{2}\s*(?:[AP]M)?)$/i)
  return m ? { label: m[1].trim(), time: m[2].trim() } : { label: text, time: '' }
}

/* Wordings that are too long for the time column on a phone.
   Abbreviated at RENDER only, and only on a narrow screen — start_note keeps
   whatever the tournament actually printed, so the stored record stays
   faithful and this stays a display decision. Distinct from SHORTEN below,
   which applies at every width because those phrasings are too long
   everywhere. */
const MOBILE_ABBR = {
  'followed by': 'Fol. by',
}

/* KEYED IN LOWER CASE, AND LOOKED UP THAT WAY. Anything added here must be a
   lower-case key; see CANON for why. */
function abbreviate(label) {
  return MOBILE_ABBR[(label || '').toLowerCase()]
}

/* ONE WORDING PER PHRASE, whatever the tournament printed.
   The sheets do not agree with each other, and in a single week printed all of:

     "Followed by"  23   "Followed By"   8
     "Not before"   26   "Not Before"    7
     "Starting at"  19   "Starts At"     7

   Read straight through, the page shows whichever the tournament happened to
   use, so the same phrase changes shape from row to row — and an exact-string
   abbreviation matched one spelling and silently did nothing to the other,
   which reads as the setting having been reverted rather than as a difference
   in the source. "Starts At" is a different PHRASING, not just different
   capitals, so casing alone would not have made these the same.

   Canonicalised at render only. `start_note` keeps what the tournament actually
   printed, so the stored record stays faithful and this stays a display
   decision — same rule as MOBILE_ABBR and SHORTEN. */
const CANON = [
  [/^followed\s+by$/i, 'Followed by'],
  [/^not\s+before$/i, 'Not before'],
  [/^starts?(?:ing)?\s+at$/i, 'Starting at'],
]

function canonLabel(label) {
  const t = (label || '').trim()
  for (const [re, canon] of CANON) if (re.test(t)) return canon
  return t
}

function TimeLine({ text, className }) {
  const { label: printed, time } = splitTimeLine(text)
  const label = canonLabel(printed)
  const short = abbreviate(label)
  return (
    <span className={className}>
      {label && (
        <span className="sched-time-label">
          {/* Both forms, with CSS choosing. Picking in JS would need a width
              listener and a re-render on every rotation, to change two words. */}
          {short ? (
            <>
              <span className="sched-abbr-full">{label}</span>
              <span className="sched-abbr-short">{short}</span>
            </>
          ) : label}
        </span>
      )}
      {time && <span className="sched-time-clock">{time}</span>}
    </span>
  )
}

/* Wordings the sheets use that are longer than the column can carry. Shortened
   at render only — start_note keeps whatever the tournament actually printed,
   so the stored record stays faithful and this stays a display decision. */
const SHORTEN = [
  [/after\s+suitable\s+rest/i, 'After rest'],
  [/after\s+the\s+(?:conclusion|completion)\s+of[^,]*/i, 'After previous'],
]

function shorten(text) {
  if (!text) return text
  for (const [re, short] of SHORTEN) {
    if (re.test(text)) return text.replace(re, short)
  }
  return text
}

function printedStart(e, zone, venueMode) {
  // Venue mode shows the sheet's line untouched — it is already venue-local.
  // In "my time" the wording stays but the clock inside it is rewritten, or the
  // switch would move the estimates and leave "Not before 3:00 PM" behind on a
  // different clock.
  if (e.start_note && !venueMode && e.printed_start_at && e.start_time_local) {
    const t = new Date(e.printed_start_at).toLocaleTimeString([], {
      hour: 'numeric', minute: '2-digit', ...(zone ? { timeZone: zone } : {}),
    })
    return shorten(e.start_note.replace(e.start_time_local, t))
  }
  if (e.start_note) return shorten(e.start_note)
  if (e.start_type === 'followed_by') return 'Followed by'
  if (e.start_type === 'not_before') return `Not before ${e.start_time_local ?? ''}`.trim()
  if (e.start_type === 'after_event') return 'After rest'
  if (e.start_time_local) return e.start_time_local
  return 'TBA'
}

/** Estimated starts are hedged with a tilde so they never read as announced. */
const FIVE_MIN = 5 * 60 * 1000

function expectedStart(e, zone, venueMode) {
  if (!e.expected_start_at) return printedStart(e, zone, venueMode)
  const printed = e.expected_source === 'printed'
  let d = new Date(e.expected_start_at)
  // Round estimates to five minutes. A chained guess built from constant match
  // lengths has no business reporting "4:27" — the precision is invented, and
  // showing it invites the number to be trusted more than it deserves. Printed
  // times are left exactly as the tournament stated them.
  if (!printed) d = new Date(Math.round(d.getTime() / FIVE_MIN) * FIVE_MIN)
  const opts = { hour: 'numeric', minute: '2-digit' }
  if (zone) opts.timeZone = zone
  const t = d.toLocaleTimeString([], opts)
  return printed ? t : `~${t}`
}

// A finite sentinel rather than Infinity: two unseeded courts would otherwise
// compare as Infinity - Infinity = NaN, and a NaN comparator silently leaves
// the array in whatever order it started in.
const NO_SEED = 9999

/* A round label that already announces qualifying, so the separate "Q" chip
   beside it would only repeat itself. */
const QUALI_ROUND = /^(q\d?|fq)$/i

/* Characters the court column carries at full size. Narrower than the name
   column and holding words like "GRANDSTAND" and "STADIUM COURT", so it runs
   out first — and when it does it is the court that gives, not the player. */
const COURT_FIT = 9

/* Characters a DOUBLES side carries on its one line: two surnames, the slash,
   and the team seed. Fewer than a singles name has, because the line holds two
   people rather than one. */
function courtScale(court) {
  /* Measured off the LONGEST WORD, not the whole string. The column wraps
     between words, so "P&G STADIUM COURT" needs no shrinking — it needs two
     lines, which it has. What wrapping cannot help is a single word wider than
     the column, and GRANDSTAND is one: there is no break to make, so the type
     is all that is left to give. Measuring the whole string shrank the
     multi-word names that were already fine and left this one alone. */
  const longest = Math.max(0, ...String(court || '').split(/\s+/).map(w => w.length))
  return longest > COURT_FIT
    ? { '--court-scale': Math.max(0.7, COURT_FIT / longest) }
    : undefined
}

/**
 * A player's seed number, or null.
 *
 * The API sends it as a field, taken from the bracket where the player
 * resolved and from the sheet's own "[17]" otherwise — so a resolved name can
 * be shown clean without the seeding disappearing with the brackets. The parse
 * stays as the fallback for anything the API has not filled in.
 *
 * Only digits count. The same brackets carry [Q], [WC], [LL], [PR] and [Alt],
 * which say how a player ENTERED rather than how highly they are ranked — and a
 * name can carry both, as in "[WC] [2]".
 */
function seedNumber(player) {
  if (player?.seed != null) return player.seed
  const { seed } = splitPlayerName(player?.name)
  const nums = seed && seed.match(/\d+/g)
  return nums ? Math.min(...nums.map(Number)) : null
}

/**
 * One player: flag, then name. Doubles shows surnames only — four full names on
 * one row does not fit a phone, and the surname is what identifies a pair
 * anyway.
 */
/* Once a match is actually on court, when it BEGAN beats any prediction about
   when it might. Both the printed line and the chained estimate are replaced by
   the real thing, in the same weight as the printed time — it is a fact now, not
   a guess, so it should not read as one.
   Only main-draw singles carry started_at: ESPN is the source and it covers
   nothing else, and only from the point we began recording it. Everything else
   keeps the printed line. */
function startedLine(e, zone) {
  if (e.status !== 'live' && e.status !== 'completed') return null
  const opts = { hour: 'numeric', minute: '2-digit' }
  if (zone) opts.timeZone = zone

  // The observed start — when the first point was played, stamped by whichever
  // poller saw it. This is the normal path now for anything live or finished.
  if (e.started_at) {
    return `Started at ${new Date(e.started_at).toLocaleTimeString([], opts)}`
  }
  // We often do not. started_at comes from ESPN, which covers only main-draw
  // singles and only since we began recording it, so doubles, qualifying and
  // anything already under way beforehand have none. The match has still
  // demonstrably started, though, so keep the printed time and fix the TENSE —
  // "Starting at 11:00 AM" on a finished match reads as if it were still to
  // come, which is the one thing the row must not say.
  if (e.printed_start_at && e.start_type === 'fixed') {
    return `Started at ${new Date(e.printed_start_at).toLocaleTimeString([], opts)}`
  }
  // Nothing recorded and nothing printed. A FINISHED match must not be
  // labelled "In progress" — the pill beside it already says Completed, and
  // the two would contradict each other — so it simply says nothing rather
  // than guessing. Only a live match reaches the second line.
  return e.status === 'completed' ? null : 'In progress'
}

/* A tennis ball, matching the draw page's. Same geometry deliberately: the two
   pages show the same match and a second, different ball would read as a
   different piece of information. */
/* What a row is watched on, lowest tier first — see hooks/useScoreEvent.js.
   COUNTED, not compared: "games played" going up by one IS a game finishing,
   and knowing that needs no knowledge of which set it was in or who won it.
   Same for sets. Derived this way, a row that arrives mid-match or whose feed
   skips a beat cannot celebrate something that did not happen — the count
   either moved or it did not.

   The set in play is left out of the decided count, or every game the leader
   wins would register as the set ending. A match tiebreak has no set in play,
   so nothing is excluded there. */
function scoreMarks(e) {
  const live = e.status === 'live'
  const lp = e.live_point ?? null
  const g = lp?.games ?? (e.live_scores ? [e.live_scores[0], e.live_scores[1]] : null)
  const sets = live ? g : (e.scores ? [e.scores[0], e.scores[1]] : null)

  let games = 0, decided = 0
  if (sets) {
    const n = Math.max(sets[0]?.length ?? 0, sets[1]?.length ?? 0)
    for (let i = 0; i < n; i++) {
      const x = Number(parseSet(sets[0]?.[i]).g) || 0
      const y = Number(parseSet(sets[1]?.[i]).g) || 0
      games += x + y
      const inPlay = live && i === n - 1 && !lp?.match_tiebreak
      if (!inPlay && x !== y) decided += 1
    }
  }

  const done = e.status === 'completed' ? 1 : 0
  /* A final is the only match that also ends a draw. Both tiers fire on the
     same update and the higher one wins, which is what ranking them is for.

     MAIN-DRAW SINGLES ONLY. A doubles final is labelled "F" like any other, and
     on 2026-08-22 the Cincinnati women's doubles final threw the full
     ten-second champion fanfare across a day on which no draw had finished
     anything. Doubles is not a draw here — there is no bracket, nobody picks
     it, nothing scores it — so its final ends nothing this page is about.
     Qualifying is excluded for the same reason: winning a final qualifying
     round gets you INTO the tournament. */
  const isFinal = e.discipline === 'singles' && e.stage === 'main'
    && /^(f|final)$/i.test(String(e.round_label ?? '').trim())
  return [
    ['game', games],
    ['set', decided],
    ['match', done],
    ['champion', done && isFinal ? 1 : 0],
  ]
}

/* How recently a match has to have finished for its result to still count as
   news when the page opens. Long enough to survive a phone waking up, a reload
   and a round-trip to the API; short enough that it is genuinely "that just
   happened" rather than a recap of the afternoon. */
const JUST_FINISHED_MS = 90_000

/* The tier to fire on FIRST render, or null to stay quiet — see useScoreEvent.
   Only a finish qualifies. A game or a set is over in the time it takes to walk
   back from the kitchen and there is no useful record of when either happened,
   whereas a completed match is stamped and is the one moment worth catching up
   on. Rows whose status was inferred from the court order carry no stamp and
   correctly say nothing.

   Tolerant in one direction on purpose: a clock that reads BEHIND the server
   makes this negative, and a phone with a slightly wrong clock should still see
   the animation. Ahead by more than the window, it silently does not fire,
   which is the harmless way round. */
function arrivalTier(e, marks) {
  if (e.status !== 'completed' || !e.completed_at) return null
  const at = Date.parse(e.completed_at)
  if (!Number.isFinite(at) || Date.now() - at > JUST_FINISHED_MS) return null
  // marks[3] is the champion mark — set only on a final that is over.
  return marks[3][1] ? 'champion' : 'match'
}

/* One set's games for one player, with the tiebreak as a superscript.
   parseSet already understands "7(9)"; this only decides how it renders. */
/* The point, which is the number that actually moves while you are watching.
   Its own component so it can hold the hook — the games beside it change every
   few minutes and this changes every few seconds, and they should not flash
   together. */
/* Both competitors, one per line, each with their own scores.
   Built from ONE source per render — the live snapshot when a match is under
   way, the final scores when it is over. Mixing them is what put a point score
   beside a set score that had already moved on. */
function MatchRow({ e, showCourt, zone, venueMode, onH2H, onChampion, onHistory, dimmed }) {
  const rowRef = useRef(null)
  const a = e.players.filter(p => p.side === 'a')
  const b = e.players.filter(p => p.side === 'b')

  // Head-to-head needs exactly one named player a side. Doubles has four, and
  // an unresolved "X OR Y" slot has no single opponent to compare against.
  const h2hPair = (e.discipline === 'singles'
                   && !e.is_tbd && a.length === 1 && b.length === 1
                   && a[0]?.name && b[0]?.name)
    ? { p1: a[0], p2: b[0], entry: e }
    : null
  const done = e.status === 'completed'
  // Same flag the draw page reads — ESPN parks a suspended match at the fifth
  // slot of live_scores. Reusing the draw's own badge so rain reads the same
  // on both screens rather than looking like ordinary play here.
  const suspended = e.live_scores?.[4] === 'suspended'
  const started = startedLine(e, zone)

  // The biggest thing that just happened to this match, or null. Marks the CARD
  // rather than a digit: a set belongs to the match, and putting the emphasis
  // on whichever cell changed would celebrate a 6 instead of the thing the 6
  // completed.
  //
  // The second argument covers the case where the result was already in by the
  // time this row first rendered. That is the NORMAL case on a phone — the tab
  // is discarded while backgrounded and the page rebuilt on return, so a match
  // that finished while the screen was off has no transition for the hook to
  // watch. Comparing renders can only ever catch a change the browser was
  // awake for; the row's own completed_at says what happened regardless of who
  // was watching, which is what makes the finish visible on mobile at all.
  const marks = scoreMarks(e)
  const fx = useScoreEvent(marks, arrivalTier(e, marks))

  /* A champion is a whole-page event, so the page has to be told. Ten seconds
     of confetti over a list of twenty rows says something enormous happened and
     leaves you hunting for which line it happened on — the fanfare covers the
     screen, and the card underneath it is wherever it happened to be sorted,
     quite possibly off the bottom. Reporting up lets the page scroll this row
     to the middle and fade the rest, which is the only part that answers
     "which match?".
     Cleared on the way out, and on unmount — a row that scrolls out of the list
     mid-celebration must not leave the whole page dimmed behind it. */
  useEffect(() => {
    if (fx !== 'champion') return
    onChampion?.(e.id)
    rowRef.current?.scrollIntoView({
      block: 'center',
      behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
        ? 'auto' : 'smooth',
    })
    return () => onChampion?.(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fx === 'champion', e.id])

  // A break of serve, worked out from two consecutive readings of this row —
  // see the hook. Its own banner rather than another card tier: a break is not
  // a bigger game, it is a different KIND of fact, and the tiers are a scale of
  // how much a result matters rather than a vocabulary of what happened.
  const lpNow = e.live_point ?? null
  const brokeGames = lpNow?.games
    ?? (e.live_scores ? [e.live_scores[0], e.live_scores[1]] : null)
  const broke = useServiceBreak(
    e.status === 'live' ? brokeGames : null,
    lpNow?.serving ?? e.live_scores?.[2] ?? null,
    lpNow?.tiebreak)

  const winner = e.winner_side === 'a' ? a : e.winner_side === 'b' ? b : null

  return (
    <>
    {fx === 'champion' && (
      <ChampionFanfare name={winner?.map(p => splitPlayerName(p.name).last)
                                    .filter(Boolean).join(' / ') || null} />
    )}
    <div ref={rowRef} className={clsx('sched-row', fx && `score-fx--${fx}`, {
      // Everything that is not the champion recedes for the duration, so the
      // one card still lit is unmistakably the one being celebrated.
      'sched-row--dimmed': dimmed,
      'sched-row--done': done,
      'sched-row--live': e.status === 'live' && !suspended,
      'sched-row--suspended': e.status === 'live' && suspended,
      // Tour tint on SINGLES only — doubles keeps the plain card, so the draws
      // people actually play stand out from the ones they don't.
      'sched-row--atp': e.discipline === 'singles' && e.tour === 'ATP',
      'sched-row--wta': e.discipline === 'singles' && e.tour === 'WTA',
    })}>
      {/* Status sits in the row's top-right corner rather than inline with the
          tags: where a court has got to is the thing you scan a column for, and
          in the tag row it queued up behind ATP/R16/DOUBLES and moved around as
          those changed. The in-progress badge is the draw page's own, so both
          screens read identically. */}
      {/* Shouted across the whole card, because what just happened is about the
          match rather than about either line of it. */}
      {broke && <span className="sched-shout" aria-hidden="true">BREAK</span>}
      {e.status === 'live' && (
        /* Say when play has STOPPED. A rain delay left rows reading "In
           progress" beside a score that could not move, which is the state
           people read as the site being broken. */
        e.live_point?.suspended
          ? <span className="in-progress-badge in-progress-badge--suspended sched-status"
                  title="Play is suspended — the score is where it stood">Suspended</span>
          : <span className="in-progress-badge sched-status">In progress</span>
      )}
      {/* The two halves of a washed-out day: abandoned here, resumed there. */}
      {e.status === 'postponed' && (
        <span className="in-progress-badge in-progress-badge--suspended sched-status"
              title="Play was abandoned for the day — this match did not finish">
          Postponed
        </span>
      )}
      {e.status === 'to_be_completed' && (
        <span className="in-progress-badge in-progress-badge--carried sched-status"
              title="Carried over from an earlier day — the score stands where play stopped">
          To be completed
        </span>
      )}
      {e.status === 'completed' && <span className="sched-status sched-status--done">Completed</span>}

      <div className="sched-row-when">
        <TimeLine
          className={clsx('sched-time', {
            'sched-time--est': !started && showCourt && e.expected_source === 'estimated',
          })}
          text={started ?? (showCourt ? expectedStart(e, zone, venueMode)
                                      : printedStart(e, zone, venueMode))} />
        {showCourt && e.court && (
          <span className="sched-court" style={courtScale(e.court)}>{e.court}</span>
        )}
        {/* Court view keeps the sheet's wording, but "Followed by" alone does
            not tell you when to turn up. The chained estimate goes underneath.
            Only when it ADDS something: a slot whose expected time is simply
            the printed one would just repeat the line above it. */}
        {!started && !showCourt && e.expected_source === 'estimated' && e.expected_start_at && (
          <TimeLine className="sched-est" text={expectedStart(e, zone, venueMode)} />
        )}
      </div>
      {/* A started match answers a click with its history — the same popup,
          slider and card the draw page opens, because the two surfaces
          describe the same match. Scheduled rows stay inert: nothing to show,
          and a dead click reading as a broken page is the draw page's own
          documented lesson. The H2H strip is a sibling, unaffected. */}
      <div
        className={clsx('sched-row-main',
                        (['live', 'completed', 'postponed', 'to_be_completed']
                          .includes(e.status))
                          && onHistory && 'sched-row-main--openable')}
        onClick={['live', 'completed', 'postponed', 'to_be_completed'].includes(e.status)
          && onHistory ? () => onHistory(e.id) : undefined}
      >
        <div className="sched-tags">
          {e.tour && <span className={clsx('sched-tag', `sched-tag--${e.tour.toLowerCase()}`)}>{e.tour}</span>}
          {e.round_label && <span className="sched-tag sched-tag--round">{e.round_label}</span>}
          {/* Only when the round does not already say so. "Q1" beside a "Q"
              states the same fact twice and costs the tag row the width. It
              still earns its place on a qualifying row whose round we could not
              derive — which is most ATP sheets, since they print no round at
              all (see _classify). */}
          {e.stage === 'qualifying' && !QUALI_ROUND.test(String(e.round_label ?? '').trim())
            && <span className="sched-tag sched-tag--quali">Q</span>}
          {e.discipline !== 'singles' && <span className="sched-tag">{e.discipline === 'mixed' ? 'XDoubles' : 'Doubles'}</span>}
        </div>
        {/* One competitor per line, with that competitor's own set scores in
            columns beside them — the same statement the draw page makes.
            "A vs B" with a combined "6-4, 7-6" score forced the reader to work
            out which number belonged to whom, and on a phone it wrapped into an
            unreadable block. Names shrink and fall back to surnames rather than
            wrapping: a line per player is the invariant. */}
        <MatchScoreCard e={e} a={a} b={b} />
      </div>
      {/* Head-to-head, in the same place and the same shape as the draw page —
          the two surfaces describe the same match and a different affordance
          would read as a different feature.

          Singles only: with four players there is no single pairing to compare.
          NOT gated on te_slug, matching the bracket: an unmatched player would
          otherwise take the button away from a match being played right now. */}
      {h2hPair && (
        <button
          className="h2h-strip sched-h2h"
          onClick={() => onH2H(h2hPair)}
          title={`Head-to-head: ${h2hPair.p1.name} vs ${h2hPair.p2.name}`}
        >
          <span className="h2h-strip-label">H2H</span>
        </button>
      )}
    </div>
    </>
  )
}

export default function Schedule() {
  // The panel is owned by the page, not the row: it is a full-screen overlay,
  // and one instance beats one per match.
  const [h2h, setH2H] = useState(null)
  /* The id, not the row: the popup must read the CURRENT entry off each
     render so a live score keeps moving while it is open — the draw page's
     convention exactly. */
  const [scoreHistId, setScoreHistId] = useState(null)
  /* THE USER'S OWN PICK, ON THE ORDER OF PLAY'S H2H.
     The draw page has always highlighted it; this panel was opened with
     match={null} and no picks at all, so pickedId could only ever be null and
     nothing was ever going to light up. The row carries everything needed —
     the draw, the match and each player's draw_entry_id — so the picks are
     fetched for the draw the open match belongs to.
     Only main-draw singles has any of those: doubles and qualifying have no
     bracket row and nobody predicts them, so the query stays disabled and the
     panel behaves exactly as before. */
  const h2hDrawId = h2h?.entry?.draw_id ?? null
  const h2hMatchId = h2h?.entry?.match_id ?? null
  const { data: h2hPreds } = useQuery({
    queryKey: ['predictions', h2hDrawId],
    queryFn: () => getPredictions(h2hDrawId),
    enabled: h2hDrawId != null && h2hMatchId != null,
    staleTime: 60_000,
  })
  const h2hPicks = useMemo(() => {
    if (!h2hPreds) return null
    const map = {}
    for (const p of h2hPreds) {
      if (p.predicted_winner_id != null) map[p.match_id] = p.predicted_winner_id
    }
    return map
  }, [h2hPreds])
  /* The id of the row throwing a champion celebration, or null. Owned by the
     page rather than the row because the answer to "which match?" is about
     every OTHER row — they all have to recede for the one that is left lit to
     mean anything. */
  const [champion, setChampion] = useState(null)
  const [params, setParams] = useSearchParams()
  const [view, setView] = useState(storedView)
  // Every filter on this page now says what to SHOW. "Hide completed" was the
  // odd one out — an off switch among on switches — so the row read as three
  // things you turn on and one you turn off, which is two mental models for
  // four adjacent buttons. On by default, which is the behaviour it replaces.
  const [showDone, setShowDone] = useState(true)
  // Off by default. The time view is the curated list of what people are
  // playing for, and doubles is not in the draws — but it is on the sheet, and
  // asking for it should not mean switching to the court view to find it.
  const [showDoubles, setShowDoubles] = useState(false)
  const [tzMode, setTzModeState] = useState(storedTz)
  const user = useAuth(s => s.user)

  // Adopt the account's choice once it arrives, unless this session has already
  // changed it — a write in flight must not be undone by the value it replaces.
  const tzTouched = useRef(false)
  useEffect(() => {
    if (tzTouched.current) return
    const saved = user?.schedule_tz
    if (saved === 'venue' || saved === 'user') setTzModeState(saved)
  }, [user])

  const setTzMode = (mode) => {
    tzTouched.current = true
    setTzModeState(mode)
    // Fire and forget: a signed-out reader still gets the local cache, and a
    // failed write costs a preference rather than the page.
    if (user) updateMe({ schedule_tz: mode }).catch(() => {})
  }

  const tournamentId = params.get('tournament') ? Number(params.get('tournament')) : undefined

  /* Which days actually exist. Every day this page can show is a day somebody
     published a sheet for, and the arrows walk that list rather than the
     calendar — stepping by ±1 day walked into gaps (a tournament plays through
     but only publishes the day before, and qualifying leaves a hole before the
     main draw), and every one of those landed on an empty page that looks
     exactly like a page that failed to load. */
  const { data: dateData } = useQuery({
    queryKey: ['schedule-dates', tournamentId ?? 'all'],
    queryFn: () => getScheduleDates(tournamentId),
    staleTime: 5 * 60_000,
  })
  const dates = dateData?.dates ?? []

  /* No date in the URL means THE EARLIEST DAY WITH TENNIS LEFT IN IT, never
     earlier than today. That is the sheet someone opening "Order of play" is
     looking for: the matches still to come. It used to be the latest published
     day, which during a Slam is tomorrow's card — correct only on the evening
     the next sheet drops, and wrong every other hour.

     Today is still not blindly the answer, for the reason the old rule gave:
     out of season today has no sheet at all. So the day is chosen from the
     dates that EXIST, and a day whose matches are all finished is stepped
     over — at the end of a Slam day this walks forward to tomorrow on its own.
     If nothing from today onward has anything open, the last such day stands,
     and out of season it falls back to the latest sheet we hold.

     A date that IS in the URL is clamped to the list, so an old link or a hand
     typed date cannot strand the page on a day with nothing on it. */
  const asked = params.get('date')
  const openCounts = dateData?.open_counts ?? {}
  const today = isoDay(new Date())
  const upcoming = dates.filter(d => d >= today)
  const firstOpen = upcoming.find(d => (openCounts[d] ?? 1) > 0)
  const day = (dates.length
    ? (asked && dates.includes(asked)
        ? asked
        : (firstOpen || upcoming[upcoming.length - 1] || dates[dates.length - 1]))
    : (asked || today))

  const dayIndex = dates.indexOf(day)
  const prevDay = dayIndex > 0 ? dates[dayIndex - 1] : null
  const nextDay = dayIndex >= 0 && dayIndex < dates.length - 1 ? dates[dayIndex + 1] : null
  // The draw we arrived from, if any. Drives both the back link and which tour
  // the time view opens on.
  const fromDraw = params.get('draw') ? Number(params.get('draw')) : undefined
  // Grey the Draw button when its draw has nothing to show — the US Open's
  // qualifying schedule is live days before its bracket is released, and a
  // live link to an empty draw reads as a broken page. Same released rule
  // the dashboard cards use; enabled while the list is still loading so a
  // released draw's button never flashes disabled.
  const { data: allDrawsList } = useQuery({
    queryKey: ['tournaments'], queryFn: listTournaments,
    staleTime: 300_000, enabled: !!fromDraw,
  })
  const fromDrawRow = (allDrawsList ?? []).find(d => d.id === fromDraw)
  const drawReady = !allDrawsList || !fromDrawRow
    || fromDrawRow.status === 'completed' || !!fromDrawRow.draw_released_direct_at
  // A SET of tours, not one. Any combination shows, so ATP+WTA is expressible
  // and is the default on a combined event. null until the day's data has
  // arrived and the default can be worked out.
  const [tourSel, setTourSel] = useState(null)

  useEffect(() => { try { localStorage.setItem(VIEW_KEY, view) } catch {} }, [view])
  useEffect(() => { try { localStorage.setItem(TZ_KEY, tzMode) } catch {} }, [tzMode])

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['schedule', day, tournamentId ?? 'all'],
    queryFn: () => getScheduleDay({ date: day, tournamentId }),
    staleTime: 30_000,
    // A modest interval as the floor. This page previously had NONE — left open
    // on a second screen it never updated at all, because React Query only
    // refetches it on mount or when the tab regains focus. SSE below is what
    // actually keeps it current; this only covers a dropped connection.
    refetchInterval: 60_000,
  })

  // Push updates for every tournament on this day, not just the filtered one —
  // a day can span two events and the unwatched one would sit stale.
  useLiveUpdates((data?.tournaments ?? []).map(t => t.id),
                 [['schedule', day, tournamentId ?? 'all']])

  // ABOVE the effect that reads it. It used to sit below, which was fine while
  // nothing above referenced it — then the tour default started needing the
  // day's list of tours, and a const read before its own declaration is a
  // temporal dead zone, not an undefined: the whole page threw on render.
  // The dependency array is what does it, evaluated during render whether or
  // not the effect body ever runs.
  const tours = useMemo(() => {
    const t = new Set((data?.entries ?? []).filter(e => e.tour).map(e => e.tour))
    return [...t].sort()
  }, [data])

  // Open on the tour of the draw we came from — someone who clicked OOP on the
  // men's draw wants the men's matches first. Only defaulted once, so a manual
  // choice is not overwritten when the day's data refreshes.
  const defaulted = useRef(false)
  useEffect(() => {
    if (defaulted.current || !data?.entries?.length) return
    defaulted.current = true
    const origin = fromDraw ? data.entries.find(e => e.draw_id === fromDraw) : null
    // Arriving from a draw narrows to that draw's tour; arriving cold shows
    // everything the day has.
    setTourSel(new Set(origin?.tour ? [origin.tour] : tours))
  }, [data, fromDraw, tours])

  // undefined => render in the reader's own zone, which is what toLocaleTimeString
  // does with no timeZone option.
  const venueTz = data?.tournaments?.find(t => t.venue_timezone)?.venue_timezone
  const zone = tzMode === 'venue' ? venueTz : undefined

  // Whether the day has anything that is not singles. The Doubles button is
  // shown only when there is doubles to show, the same way the tour chips
  // appear only on a day that runs both — a control that cannot change what is
  // on screen is worse than no control.
  const hasDoubles = useMemo(
    () => (data?.entries ?? []).some(e => e.discipline !== 'singles'), [data])

  const toggleTour = (t) => setTourSel(prev => {
    const cur = new Set(prev ?? tours)
    if (!cur.has(t)) { cur.add(t); return cur }
    // The last tour stays on. Turning it off would empty the page, and a page
    // that has gone blank reads as broken rather than as filtered — the one
    // combination worth taking away from a set of filters that are otherwise
    // free to be set any way at all.
    if (cur.size === 1) return prev ?? cur
    cur.delete(t)
    return cur
  })

  const setDay = (iso) => {
    const next = new URLSearchParams(params)
    next.set('date', iso)
    setParams(next, { replace: true })
  }

  const entries = useMemo(() => {
    const all = data?.entries ?? []
    return all.filter(e => {
      // Court view reproduces the sheet — every match on it, doubles and mixed
      // included — because the running order of a court only makes sense if
      // nothing is missing from it. So discipline and tour are TIME-view
      // controls: a court running both tours, filtered, would read as if
      // matches had gone missing rather than been hidden.
      if (view === 'time' && e.discipline !== 'singles' && !showDoubles) return false
      // An entry with no tour recorded is shown regardless — the filter picks
      // between tours, and a row that names none is not a row that names the
      // other one.
      if (view === 'time' && tourSel && e.tour && !tourSel.has(e.tour)) return false
      if (!showDone && e.status === 'completed') return false
      return true
    })
  }, [data, view, showDone, showDoubles, tourSel])

  /* Order the time view by when a match ACTUALLY began, falling back to the
     estimate for anything still to come.
     The API sorts on expected_start_at, which for a match already under way is
     the time the sheet PRINTED — so a match that went on late sat among the
     slots it was scheduled beside rather than where it belongs, while its own
     row said "Started at" some quite different time. Sorting on the same value
     the row displays is what makes the list read as a chronology. */
  const timeEntries = useMemo(() => {
    const key = e => e.started_at || e.expected_start_at || ''
    return [...entries].sort((a, b) => {
      const ka = key(a), kb = key(b)
      if (ka !== kb) return ka < kb ? -1 : 1
      // Same instant: keep a court's own running order intact.
      return (a.court || '').localeCompare(b.court || '') || a.court_order - b.court_order
    })
  }, [entries])

  const byCourt = useMemo(() => {
    const m = new Map()
    for (const e of entries) {
      const k = e.court || 'Unassigned'
      if (!m.has(k)) m.set(k, [])
      m.get(k).push(e)
    }
    for (const list of m.values()) list.sort((x, y) => x.court_order - y.court_order)

    // Courts are ordered by the best seed playing on them, so the show courts
    // rise to the top without hardcoding venue-specific names — every
    // tournament calls its main court something different. Falls back to how
    // many matches a court is hosting, which is the next best proxy for
    // importance when nobody seeded is out there.
    // Ranked on SINGLES only, even though the view now lists everything: a
    // doubles bracket is seeded separately, so its [1] says nothing about how
    // big the match is next to a singles [1]. A court hosting only doubles
    // scores nothing on either measure and settles at the bottom, which is
    // where it belongs without being hidden.
    const ranked = [...m.entries()].map(([name, list]) => {
      let best = NO_SEED
      let count = 0
      for (const e of list) {
        if (e.discipline !== 'singles') continue
        count += 1
        for (const p of e.players) {
          const n = seedNumber(p)
          if (n != null && n < best) best = n
        }
      }
      return { name, list, best, count }
    })
    ranked.sort((a, b) =>
      a.best - b.best || b.count - a.count || a.name.localeCompare(b.name))
    return ranked.map(r => [r.name, r.list])
  }, [entries])

  /*
   * No measuring pass. There used to be one here that sized every card to the
   * longest name on the page, and it caused more damage than it prevented:
   *
   *  - it fed on itself. A card is width:fit-content, so its width depends on
   *    the name being measured, and reading that back produced a column that
   *    ratcheted smaller every pass.
   *  - it never settled. The pass mutated font sizes and a CSS variable, the
   *    ResizeObserver watching the container saw the resulting reflow, and ran
   *    it again — text visibly vibrating on both desktop and mobile.
   *
   * CSS does the same job without either failure: cards fill their column up
   * to a maximum, so every card in a column is identical by construction, and
   * the name takes whatever is left after the fixed columns.
   *
   * ONE THING IS MEASURED NOW, and the difference is the whole reason it is
   * safe. useNameBox reads the width of .sched-competitor-name, which is
   * flex:1 1 auto with min-width:0 among fixed-width siblings — so its width is
   * decided by THEM, not by what is inside it. Making the name narrower cannot
   * widen the box, so the reading cannot change as a result of being acted on.
   * The pass above measured a width that DEPENDED on the text it was sizing,
   * which is what made it ratchet and vibrate. Nothing here writes a card
   * width, and no observer watches a box whose size its own output can move.
   */

  return (
    <div className="sched-page">
      {/* Same panel the draw page opens, so head-to-head looks and behaves
          identically wherever it is reached from. No picking here: the schedule
          is a view of play, and a pick belongs on the bracket where the cascade
          it affects is visible. */}
      {/* entry_name is the BRACKET's spelling — "Iga Świątek" — where the row
          deliberately prints the sheet's "[7] Iga SWIATEK POL". The panel is
          about the players; the row is about the sheet. */}
      {scoreHistId != null && (() => {
        const cur = (data?.entries ?? []).find(x => x.id === scoreHistId)
        return cur ? (
          <ScoreHistoryPopup entry={cur} onClose={() => setScoreHistId(null)} />
        ) : null
      })()}
      {h2h && (
        /* `id` is the DRAW ENTRY id, which is the space predictions are stored
           in — a schedule player carries it as draw_entry_id and has no `id` of
           its own, so without it the pick comparison has nothing to match.
           `match` only needs its id here; the panel reads nothing else off it.
           Picking stays OFF: the order of play shows what is happening, and a
           bracket is edited on the draw page. */
        <H2HPanel
          slug1={h2h.p1.te_slug}
          slug2={h2h.p2.te_slug}
          player1={{ ...h2h.p1, id: h2h.p1.draw_entry_id ?? null,
                     name: h2h.p1.entry_name || h2h.p1.name }}
          player2={{ ...h2h.p2, id: h2h.p2.draw_entry_id ?? null,
                     name: h2h.p2.entry_name || h2h.p2.name }}
          tournSurface={h2h.entry?.surface}
          tournGender={h2h.entry?.gender || (h2h.entry?.tour === 'WTA' ? 'F' : 'M')}
          beforeDrawId={h2h.entry?.draw_id}
          match={h2hMatchId != null ? { id: h2hMatchId } : null}
          picks={h2hPicks}
          canPick={false}
          onClose={() => setH2H(null)}
        />
      )}
      {/* Everything on the page shares one shrink-to-fit column, so the header
          and the filters end on the same left and right edges as the match
          boxes rather than on the edges of the monitor. The boxes are what
          decide that width — they are the widest thing here — so the controls
          follow them instead of the other way round. */}
      <div className="sched-shell">
      <div className="sched-topbar">
        <div className="sched-titleblock">
          <h1 className="sched-title">
            {data?.tournaments?.length === 1
              ? data.tournaments[0].name
              : data?.tournaments?.length ? 'Order of play' : 'Schedule'}
          </h1>
          <div className="sched-subtitle">Order of play</div>
        </div>

        <div className="sched-center">
            <div className="sched-daynav">
            {/* Disabled at the ends rather than walking into an empty day. A
                page with no matches on it is indistinguishable from one that
                failed to load, so the arrow that would produce it is the wrong
                thing to offer. */}
            <button className="sched-nav-btn" onClick={() => prevDay && setDay(prevDay)}
                    disabled={!prevDay} aria-label="Previous day">‹</button>
            {/* Fixed width, so the arrows hold their position as the date
                changes — "Wed, Aug 19" and "Thu, Sep 3" are different widths and
                the buttons would otherwise shuffle under the cursor. */}
            <span className="sched-day-label">{prettyDay(day)}</span>
            <button className="sched-nav-btn" onClick={() => nextDay && setDay(nextDay)}
                    disabled={!nextDay} aria-label="Next day">›</button>
          </div>

            <div className="sched-viewswitch" role="tablist">
            <button role="tab" aria-selected={view === 'time'}
                    className={clsx('sched-viewbtn', { 'sched-viewbtn--on': view === 'time' })}
                    onClick={() => setView('time')}>Time</button>
            <button role="tab" aria-selected={view === 'court'}
                    className={clsx('sched-viewbtn', { 'sched-viewbtn--on': view === 'court' })}
                    onClick={() => setView('court')}>Court</button>
          </div>
        </div>

        <div className="sched-topright">
          {(data?.tournaments ?? []).filter(t => t.oop_url).slice(0, 1).map(t => (
            <a key={t.id} className="sched-pdf" href={t.oop_url}
               target="_blank" rel="noopener noreferrer"
               /* The revision ordinal matches the status emails ("OOP rev.3")
                  — same count, same meaning: which correction of the day's
                  sheet the site currently reflects. Absent on old days the
                  document table no longer covers. */
               title={`${t.name} — official order of play (PDF)${
                 t.oop_revision ? ` — rev.${t.oop_revision}` : ''}`}>
              PDF
            </a>
          ))}

          {venueTz && (
            <div className="sched-tzswitch" role="tablist" aria-label="Time zone">
              <button role="tab" aria-selected={tzMode === 'venue'}
                      className={clsx('sched-tzbtn', { 'sched-tzbtn--on': tzMode === 'venue' })}
                      onClick={() => setTzMode('venue')}>Venue</button>
              <button role="tab" aria-selected={tzMode === 'user'}
                      className={clsx('sched-tzbtn', { 'sched-tzbtn--on': tzMode === 'user' })}
                      onClick={() => setTzMode('user')}>My time</button>
            </div>
          )}
        </div>
      </div>

      {/* Filters and the list share one wrapper so they keep a common left and
          right edge. In time view that wrapper sizes to the widest row, so
          centring the boxes centres the controls above them too rather than
          leaving them stranded at the page edges. */}
      <div className={clsx('sched-body', { 'sched-body--fit': view === 'time' })}>
      <div className="sched-filters">
        {fromDraw && (drawReady ? (
          <Link className="sched-back" to={`/tournaments/${fromDraw}`}>Draw</Link>
        ) : (
          <span className="sched-back sched-back--disabled"
                title="Draw not released yet" aria-disabled="true">Draw</span>
        ))}
        {view === 'time' && tours.length > 1 && (
          <>
            {tours.map(t => (
              <button key={t}
                      className={clsx('sched-chip', `sched-chip--${t.toLowerCase()}`,
                                      { 'sched-chip--on': !tourSel || tourSel.has(t) })}
                      onClick={() => toggleTour(t)}>{t}</button>
            ))}
          </>
        )}
        {view === 'time' && hasDoubles && (
          <button className={clsx('sched-chip', { 'sched-chip--on': showDoubles })}
                  onClick={() => setShowDoubles(v => !v)}>Doubles</button>
        )}
        <button className={clsx('sched-chip', { 'sched-chip--on': showDone })}
                onClick={() => setShowDone(v => !v)}>Completed</button>
      </div>

      {isLoading && <div className="sched-empty">Loading…</div>}

      {/* A FAILED FETCH IS NOT AN EMPTY SCHEDULE. One dropped request used to
          render "No order of play published for this day" — a confident claim
          about the tournament, made from no information — on a day whose
          order of play was in fact published and on screen a minute earlier.
          Say what actually happened and offer the retry. */}
      {!isLoading && isError && (
        <div className="sched-empty">
          Couldn’t load the schedule just now.
          <div style={{ marginTop: 12 }}>
            <button className="sched-chip sched-chip--on" onClick={() => refetch()}>
              Try again
            </button>
          </div>
        </div>
      )}

      {!isLoading && !isError && entries.length === 0 && (
        <div className="sched-empty">
          No order of play published for this day.
          <div className="sched-empty-sub">
            Schedules appear once the tournament releases them, usually the evening before.
          </div>
        </div>
      )}

      {!isLoading && entries.length > 0 && view === 'time' && (
        <div className="sched-list sched-list--time">
          {timeEntries.map(e => <MatchRow key={e.id} e={e} showCourt zone={zone} venueMode={tzMode === 'venue'}
                                onH2H={setH2H} onChampion={setChampion} onHistory={setScoreHistId}
                                dimmed={champion != null && champion !== e.id} />)}
        </div>
      )}

      {!isLoading && entries.length > 0 && view === 'court' && (
        <div className="sched-courts">
          {byCourt.map(([name, list]) => (
            <section className="sched-courtblock" key={name}>
              <h2 className="sched-courthead">{name}</h2>
              <div className="sched-list">
                {list.map(e => <MatchRow key={e.id} e={e} showCourt={false} zone={zone} venueMode={tzMode === 'venue'}
                                onH2H={setH2H} onChampion={setChampion} onHistory={setScoreHistId}
                                dimmed={champion != null && champion !== e.id} />)}
              </div>
            </section>
          ))}
        </div>
      )}
      </div>
      </div>
    </div>
  )
}
