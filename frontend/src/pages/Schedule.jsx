import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useLiveUpdates } from '../hooks/useLiveUpdates'
import useFlashOnChange from '../hooks/useFlashOnChange'
import useScoreEvent from '../hooks/useScoreEvent'
import useServiceBreak from '../hooks/useServiceBreak'
import ChampionFanfare from '../components/ChampionFanfare'
import H2HPanel from '../components/H2HPanel'
import { useSearchParams, Link } from 'react-router-dom'
import clsx from 'clsx'
import { getScheduleDay } from '../api/schedule'
import { updateMe } from '../api/auth'
import { useAuth } from '../store/auth'
import { nationalityIso2, splitPlayerName } from '../utils/flags'
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

function shiftDay(iso, delta) {
  const [y, m, d] = iso.split('-').map(Number)
  const dt = new Date(y, m - 1, d)
  dt.setDate(dt.getDate() + delta)
  return isoDay(dt)
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
  'Followed by': 'Fol. By',
}

function TimeLine({ text, className }) {
  const { label, time } = splitTimeLine(text)
  const short = MOBILE_ABBR[label]
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
function PlayerName({ raw, surnameOnly, hideSeed, nationality, seed: seedProp }) {
  const { seed: printedSeed, first, last, nat } = splitPlayerName(raw)
  // A seeding sent as a field beats one parsed out of the name: a resolved
  // player's name comes from the bracket and never carried brackets to parse.
  const seed = seedProp != null ? `[${seedProp}]` : printedSeed
  // Our own record wins over whatever the sheet printed: it drops the country
  // when space is tight, and a slot resolved from an "OR" carries the bracket's
  // name, which never had one inline.
  const iso2 = nationalityIso2(nationality || nat)

  /* Two forms of a singles name, and CSS picks. On a phone the name column is
     about 180px and a long one — "Amanda ANISIMOVA [9]" — ran under the result
     mark and the score. An initial is how a draw sheet prints a name it has no
     room for, and it still names the same person; a cut or shrunk one does not.
     Whether it fits depends on the width, which only CSS knows, so both forms
     are rendered and the breakpoint chooses. The length test is a pure function
     of the string — nothing is measured, so there is nothing to oscillate.
     THE SEED COUNTS. It is part of the same run of text — "Madison KEYS" fits
     and "Madison KEYS [20]" does not, and measuring the name alone let exactly
     that case through, with the seed sitting on top of the set score.
     15 characters is where the column runs out, flag and three sets included. */
  const full = [first, last].filter(Boolean).join(' ')
  const shown = full + (!hideSeed && seed ? ` ${seed}` : '')
  const longName = !surnameOnly && shown.length > 15
  const initialled = first ? `${first.trim()[0]}. ${last}` : last

  return (
    <span className="sched-player">
      {/* No placeholder when there is no flag. A missing nationality here is
          not missing DATA — the tours list Russian and Belarusian players as
          neutral athletes with no flag, and the sheet omits it deliberately, so
          reserving the space just indents those names forever. Tennis Explorer
          does hold a country for them, and we deliberately do not use it: the
          official order of play withholds it on purpose. */}
      {iso2 && <span className={`fi fi-${iso2.toLowerCase()} sched-flag`} title={nat} />}
      <span className={clsx('sched-pname', { 'sched-pname--long': longName })}>
        {surnameOnly ? last : longName ? (
          <>
            <span className="sched-name-full">{full}</span>
            <span className="sched-name-abbr">{initialled}</span>
          </>
        ) : full}
        {/* AFTER the name. Leading it, the seed was the first thing on the line
            and pushed every name to a different starting column depending on
            whether it had one — so the names never formed an edge to scan. It
            also read as the more important fact, which it is not. */}
        {!hideSeed && seed && <span className="sched-seed">{seed}</span>}
      </span>
    </span>
  )
}

function Side({ players, doubles, tbd }) {
  if (!players.length) return <span className="sched-side">TBD</span>

  // An unresolved side is a choice between two whole teams, not a list of
  // players — "O. Luz / R. Matos OR C. Harrison / N. Skupski". Rendering it as
  // four names in a row says nothing about who partners whom. Each alternative
  // is already one entry, so they only need separating.
  if (tbd && players.length > 1) {
    return (
      <span className="sched-side sched-side--alt">
        {players.map((p, i) => (
          <span key={i} className="sched-altteam">
            {i > 0 && <span className="sched-or">or</span>}
            {/* Surnames for singles. Two candidates and a separator have to fit
                the ONE line this side is given, and a slot that has not
                resolved is by definition the least important thing on the card
                — it is two names neither of which may turn out to be playing.
                A doubles alternative is a whole team in one string
                ("O. Luz / R. Matos"), which has no surname to take. */}
            <span className="sched-pname">
              {doubles ? p.name : (splitPlayerName(p.name).last || p.name)}
            </span>
          </span>
        ))}
      </span>
    )
  }
  // A doubles seed belongs to the TEAM. The sheet repeats it against both
  // partners, which reads as two separately-seeded players.
  const teamSeed = doubles
    ? players.map(p => (p.seed != null ? `[${p.seed}]`
                                       : splitPlayerName(p.name).seed)).find(Boolean) ?? null
    : null
  return (
    <span className="sched-side">
      {players.map((p, i) => (
        <Fragment key={`${p.side}${p.position}${i}`}>
          {/* Partners are separated by a slash, the way every draw sheet writes
              a pair. A bare space read as two unrelated names once the flags
              sat between them. */}
          {i > 0 && <span className="sched-slash">/</span>}
          <PlayerName raw={p.name} surnameOnly={doubles} hideSeed={doubles}
                      nationality={p.nationality} seed={p.seed} />
        </Fragment>
      ))}
      {/* Same placement as a singles seed, and for the same reason. */}
      {teamSeed && <span className="sched-seed sched-seed--team">{teamSeed}</span>}
    </span>
  )
}

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
function ServeBall() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" className="sched-ball" aria-label="serving">
      <circle cx="12" cy="12" r="11" fill="#7ba81f" />
      <g fill="none" stroke="#fff" strokeWidth="2">
        <path d="M12 1A12.04 12.04 0 0 1 1 12" />
        <path d="M12 23A12.04 12.04 0 0 1 23 12" />
      </g>
      <circle cx="12" cy="12" r="11" fill="none" stroke="#1b4332" strokeWidth="2" />
    </svg>
  )
}

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
  // A final is the only match that also ends a draw. Both tiers fire on the
  // same update and the higher one wins, which is what ranking them is for.
  const isFinal = /^(f|final)$/i.test(String(e.round_label ?? '').trim())
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
function SetCell({ cell, bold }) {
  const { g, tb } = parseSet(cell)
  // Before the early return, not after — a games count that goes from a number
  // to nothing still has to run the hook. (See the note in Schedule.css on what
  // the flash is for.)
  const flash = useFlashOnChange(`${g}|${tb ?? ''}`)
  if (g === '' && tb == null) return <span className="sched-set empty">·</span>
  return (
    <span className={clsx('sched-set', { 'sched-set--won': bold, 'sched-score--bump': flash })}>
      {g}{tb != null && <sup>{tb}</sup>}
    </span>
  )
}

/* The point, which is the number that actually moves while you are watching.
   Its own component so it can hold the hook — the games beside it change every
   few minutes and this changes every few seconds, and they should not flash
   together. */
function PointCell({ point, tiebreak }) {
  const flash = useFlashOnChange(point)
  return (
    <span className={clsx('sched-point', { 'sched-point--tb': tiebreak,
                                           'sched-score--bump': flash })}
          title={tiebreak ? 'Tiebreak points' : 'Current game'}>
      {point}
    </span>
  )
}

/* Both competitors, one per line, each with their own scores.
   Built from ONE source per render — the live snapshot when a match is under
   way, the final scores when it is over. Mixing them is what put a point score
   beside a set score that had already moved on. */
function CompetitorRows({ e, a, b }) {
  const doubles = e.discipline !== 'singles'
  const lp = e.live_point ?? null
  const live = e.status === 'live'

  // Games: prefer the snapshot's own, exactly as the draw page does.
  const g = lp?.games ?? null
  const fromLive = live ? (g ? [g[0], g[1]] : (e.live_scores ? [e.live_scores[0], e.live_scores[1]] : null)) : null
  const fromFinal = !live && e.scores ? [e.scores[0], e.scores[1]] : null
  const sets = fromLive ?? fromFinal
  const n = sets ? Math.max(sets[0]?.length ?? 0, sets[1]?.length ?? 0) : 0

  // Who took each completed set, for the bolding. The set in play has no winner
  // and must stay unbolded — that is what makes "in progress" legible.
  const setWon = (i, side) => {
    if (!sets) return false
    // The last set present is normally the one being played, so it has no
    // winner yet. In a match tiebreak it is not — the tiebreak stands in for
    // the deciding set and is scored as a point, so every set in this list is
    // finished and the second one keeps the bold it earned.
    if (live && i === n - 1 && !lp?.match_tiebreak) return false
    const x = Number(parseSet(sets[0]?.[i]).g), y = Number(parseSet(sets[1]?.[i]).g)
    if (Number.isNaN(x) || Number.isNaN(y)) return false
    return side === 0 ? x > y : y > x
  }

  const winnerSide = (() => {
    if (e.status !== 'completed' || !e.scores) return null
    let x = 0, y = 0
    for (let i = 0; i < n; i++) { if (setWon(i, 0)) x++; if (setWon(i, 1)) y++ }
    return x === y ? null : (x > y ? 0 : 1)
  })()

  const serving = live ? (lp?.serving ?? e.live_scores?.[2] ?? null) : null
  const point = live && lp?.point ? lp.point : null

  /* How the match ENDED, when it did not end normally.
     parseSet strips the trailing "r" to read the games off a cell, so without
     this the schedule showed a retirement as an ordinary 4-1 win — a different
     match from the one that was played.

     Read off whichever side carries the marker, matching the bracket: a
     retirement marks the player who QUIT, a walkover marks the player who
     ADVANCED ("won by walkover"). The two sit on opposite sides on purpose;
     that is how they are stored. */
  const endedWith = (side) => {
    const cells = (e.scores || [])[side] || []
    if (cells.some(c => /^w\/?o$/i.test(String(c ?? '').trim()))) return 'w/o'
    if (cells.some(c => /r$/i.test(String(c ?? '')))) return 'ret.'
    return null
  }

  const rows = [
    { players: a, side: 0, tbd: !!e.tbd_side?.includes('a') },
    { players: b, side: 1, tbd: !!e.tbd_side?.includes('b') },
  ]

  return (
    <div className={clsx('sched-competitors', { 'sched-competitors--doubles': doubles })}>
      {rows.map(({ players, side, tbd }) => (
        <div key={side}
             className={clsx('sched-competitor', {
               'sched-competitor--won': winnerSide === side,
               'sched-competitor--lost': winnerSide != null && winnerSide !== side,
             })}>
          <span className="sched-competitor-name">
            <Side players={players} doubles={doubles} tbd={tbd} />
          </span>
          {/* A SLOT, always present, not a conditional element. The ball
              appears on one line only, so rendering it inline shifted that
              line's scores left of the other's and broke the column. */}
          <span className="sched-ball-slot">
            {serving === side + 1 && <ServeBall />}
          </span>
          {/* BEFORE the tick/cross, not between it and the scores.
              Everything here is fixed-width and right-packed, so an element's
              position depends on the total width of everything after it. With
              "ret." sitting after the mark, the row that had one pushed its
              cross left of the other row's tick — and the two stopped lining
              up. In front of the mark it is absorbed by the flexible name
              instead, and the marks stay in a column.
              Still ahead of the scores, where it qualifies them; after the
              numbers it read as another set. */}
          {endedWith(side) && (
            <span className={clsx('sched-end', { 'sched-end--wo': endedWith(side) === 'w/o' })}>
              {endedWith(side)}
            </span>
          )}
          {winnerSide != null && (
            <span className={clsx('sched-mark', winnerSide === side ? 'sched-mark--win' : 'sched-mark--loss')}>
              {winnerSide === side ? '\u2713' : '\u2717'}
            </span>
          )}
          <span className="sched-sets">
            {Array.from({ length: n }, (_, i) => (
              <SetCell key={i} cell={sets?.[side]?.[i]} bold={setWon(i, side)} />
            ))}
            {/* The point last, tinted apart from the games — it is a different
                kind of number and changes every few seconds. */}
            {point && (
              <PointCell point={point[side] ?? '0'} tiebreak={lp.tiebreak} />
            )}
          </span>
        </div>
      ))}
    </div>
  )
}

function MatchRow({ e, showCourt, zone, venueMode, onH2H }) {
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
    <div className={clsx('sched-row', fx && `score-fx--${fx}`, {
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
      {e.status === 'live' && <span className="in-progress-badge sched-status">In progress</span>}
      {e.status === 'completed' && <span className="sched-status sched-status--done">Completed</span>}

      <div className="sched-row-when">
        <TimeLine
          className={clsx('sched-time', {
            'sched-time--est': !started && showCourt && e.expected_source === 'estimated',
          })}
          text={started ?? (showCourt ? expectedStart(e, zone, venueMode)
                                      : printedStart(e, zone, venueMode))} />
        {showCourt && e.court && <span className="sched-court">{e.court}</span>}
        {/* Court view keeps the sheet's wording, but "Followed by" alone does
            not tell you when to turn up. The chained estimate goes underneath.
            Only when it ADDS something: a slot whose expected time is simply
            the printed one would just repeat the line above it. */}
        {!started && !showCourt && e.expected_source === 'estimated' && e.expected_start_at && (
          <TimeLine className="sched-est" text={expectedStart(e, zone, venueMode)} />
        )}
      </div>
      <div className="sched-row-main">
        <div className="sched-tags">
          {e.tour && <span className={clsx('sched-tag', `sched-tag--${e.tour.toLowerCase()}`)}>{e.tour}</span>}
          {e.round_label && <span className="sched-tag sched-tag--round">{e.round_label}</span>}
          {e.stage === 'qualifying' && <span className="sched-tag sched-tag--quali">Q</span>}
          {e.discipline !== 'singles' && <span className="sched-tag">{e.discipline === 'mixed' ? 'Mixed' : 'Doubles'}</span>}
        </div>
        {/* One competitor per line, with that competitor's own set scores in
            columns beside them — the same statement the draw page makes.
            "A vs B" with a combined "6-4, 7-6" score forced the reader to work
            out which number belonged to whom, and on a phone it wrapped into an
            unreadable block. Names shrink and fall back to surnames rather than
            wrapping: a line per player is the invariant. */}
        <CompetitorRows e={e} a={a} b={b} />
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

  const day = params.get('date') || isoDay(new Date())
  const tournamentId = params.get('tournament') ? Number(params.get('tournament')) : undefined
  // The draw we arrived from, if any. Drives both the back link and which tour
  // the time view opens on.
  const fromDraw = params.get('draw') ? Number(params.get('draw')) : undefined
  // A SET of tours, not one. Any combination shows, so ATP+WTA is expressible
  // and is the default on a combined event. null until the day's data has
  // arrived and the default can be worked out.
  const [tourSel, setTourSel] = useState(null)

  useEffect(() => { try { localStorage.setItem(VIEW_KEY, view) } catch {} }, [view])
  useEffect(() => { try { localStorage.setItem(TZ_KEY, tzMode) } catch {} }, [tzMode])

  const { data, isLoading } = useQuery({
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
   * the name takes whatever is left after the fixed columns. No JavaScript
   * measures anything, so there is nothing to oscillate.
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
      {h2h && (
        <H2HPanel
          slug1={h2h.p1.te_slug}
          slug2={h2h.p2.te_slug}
          player1={{ ...h2h.p1, name: h2h.p1.entry_name || h2h.p1.name }}
          player2={{ ...h2h.p2, name: h2h.p2.entry_name || h2h.p2.name }}
          tournSurface={h2h.entry?.surface}
          tournGender={h2h.entry?.gender || (h2h.entry?.tour === 'WTA' ? 'F' : 'M')}
          beforeDrawId={h2h.entry?.draw_id}
          match={null}
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
            <button className="sched-nav-btn" onClick={() => setDay(shiftDay(day, -1))} aria-label="Previous day">‹</button>
            {/* Fixed width, so the arrows hold their position as the date
                changes — "Wed, Aug 19" and "Thu, Sep 3" are different widths and
                the buttons would otherwise shuffle under the cursor. */}
            <span className="sched-day-label">{prettyDay(day)}</span>
            <button className="sched-nav-btn" onClick={() => setDay(shiftDay(day, 1))} aria-label="Next day">›</button>
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
               title={`${t.name} — official order of play (PDF)`}>
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
        {fromDraw && (
          <Link className="sched-back" to={`/tournaments/${fromDraw}`}>Back</Link>
        )}
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

      {!isLoading && entries.length === 0 && (
        <div className="sched-empty">
          No order of play published for this day.
          <div className="sched-empty-sub">
            Schedules appear once the tournament releases them, usually the evening before.
          </div>
        </div>
      )}

      {!isLoading && entries.length > 0 && view === 'time' && (
        <div className="sched-list sched-list--time">
          {timeEntries.map(e => <MatchRow key={e.id} e={e} showCourt zone={zone} venueMode={tzMode === 'venue'} onH2H={setH2H} />)}
        </div>
      )}

      {!isLoading && entries.length > 0 && view === 'court' && (
        <div className="sched-courts">
          {byCourt.map(([name, list]) => (
            <section className="sched-courtblock" key={name}>
              <h2 className="sched-courthead">{name}</h2>
              <div className="sched-list">
                {list.map(e => <MatchRow key={e.id} e={e} showCourt={false} zone={zone} venueMode={tzMode === 'venue'} onH2H={setH2H} />)}
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
