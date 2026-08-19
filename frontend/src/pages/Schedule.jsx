import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams, Link } from 'react-router-dom'
import clsx from 'clsx'
import { getScheduleDay } from '../api/schedule'
import { nationalityIso2, splitPlayerName } from '../utils/flags'
import { scoreNodes, liveScoreNodes } from '../utils/score'
import './Schedule.css'

const VIEW_KEY = 'ua-schedule-view'
const TZ_KEY = 'ua-schedule-tz'

// Venue time by default: the sheet prints venue local, so showing anything else
// puts our estimates on a different clock from the times beside them.
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
function printedStart(e, zone, venueMode) {
  // Venue mode shows the sheet's line untouched — it is already venue-local.
  // In "my time" the wording stays but the clock inside it is rewritten, or the
  // switch would move the estimates and leave "Not before 3:00 PM" behind on a
  // different clock.
  if (e.start_note && !venueMode && e.printed_start_at && e.start_time_local) {
    const t = new Date(e.printed_start_at).toLocaleTimeString([], {
      hour: 'numeric', minute: '2-digit', ...(zone ? { timeZone: zone } : {}),
    })
    return e.start_note.replace(e.start_time_local, t)
  }
  if (e.start_note) return e.start_note
  if (e.start_type === 'followed_by') return 'Followed by'
  if (e.start_type === 'not_before') return `Not before ${e.start_time_local ?? ''}`.trim()
  if (e.start_type === 'after_event') return 'After suitable rest'
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
 * The seed number in a printed name, or null.
 *
 * Only digits count. The same brackets carry [Q], [WC], [LL], [PR] and [Alt],
 * which say how a player entered rather than how highly they are ranked — and a
 * name can carry both, as in "[WC] [2]".
 */
function seedNumber(raw) {
  const { seed } = splitPlayerName(raw)
  const nums = seed && seed.match(/\d+/g)
  return nums ? Math.min(...nums.map(Number)) : null
}

/* ESPN only, and formatted the way the draw page formats it — "6-4, 7-6³"
   rather than the raw game counts this first rendered as "5 | 4". */
function liveLine(e) {
  if (e.status === 'live' && e.live_scores) return liveScoreNodes(e.live_scores)
  if (e.scores) return scoreNodes(e.scores)
  return null
}

/**
 * One player: flag, then name. Doubles shows surnames only — four full names on
 * one row does not fit a phone, and the surname is what identifies a pair
 * anyway.
 */
function PlayerName({ raw, surnameOnly, hideSeed, nationality }) {
  const { seed, first, last, nat } = splitPlayerName(raw)
  // Our own record wins over whatever the sheet printed: it drops the country
  // when space is tight, and a slot resolved from an "OR" carries the bracket's
  // name, which never had one inline.
  const iso2 = nationalityIso2(nationality || nat)
  return (
    <span className="sched-player">
      {/* No placeholder when there is no flag. A missing nationality here is
          not missing DATA — the tours list Russian and Belarusian players as
          neutral athletes with no flag, and the sheet omits it deliberately, so
          reserving the space just indents those names forever. Tennis Explorer
          does hold a country for them, and we deliberately do not use it: the
          official order of play withholds it on purpose. */}
      {iso2 && <span className={`fi fi-${iso2.toLowerCase()} sched-flag`} title={nat} />}
      <span className="sched-pname">
        {!hideSeed && seed && <span className="sched-seed">{seed}</span>}
        {surnameOnly ? last : [first, last].filter(Boolean).join(' ')}
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
            <span className="sched-pname">{p.name}</span>
          </span>
        ))}
      </span>
    )
  }
  // A doubles seed belongs to the TEAM. The sheet repeats it against both
  // partners, which reads as two separately-seeded players.
  const teamSeed = doubles
    ? players.map(p => splitPlayerName(p.name).seed).find(Boolean) ?? null
    : null
  return (
    <span className="sched-side">
      {teamSeed && <span className="sched-seed sched-seed--team">{teamSeed}</span>}
      {players.map((p, i) => (
        <Fragment key={`${p.side}${p.position}${i}`}>
          {/* Partners are separated by a slash, the way every draw sheet writes
              a pair. A bare space read as two unrelated names once the flags
              sat between them. */}
          {i > 0 && <span className="sched-slash">/</span>}
          <PlayerName raw={p.name} surnameOnly={doubles} hideSeed={doubles}
                      nationality={p.nationality} />
        </Fragment>
      ))}
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
  if (!e.started_at) return null
  if (e.status !== 'live' && e.status !== 'completed') return null
  const opts = { hour: 'numeric', minute: '2-digit' }
  if (zone) opts.timeZone = zone
  return `Started ${new Date(e.started_at).toLocaleTimeString([], opts)}`
}

function MatchRow({ e, showCourt, zone, venueMode }) {
  const a = e.players.filter(p => p.side === 'a')
  const b = e.players.filter(p => p.side === 'b')
  const score = liveLine(e)
  const done = e.status === 'completed'
  const started = startedLine(e, zone)
  return (
    <div className={clsx('sched-row', {
      'sched-row--done': done,
      'sched-row--live': e.status === 'live',
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
      {e.status === 'live' && <span className="in-progress-badge sched-status">In progress</span>}
      {e.status === 'completed' && <span className="sched-status sched-status--done">Completed</span>}

      <div className="sched-row-when">
        <span className={clsx('sched-time', {
          'sched-time--est': !started && showCourt && e.expected_source === 'estimated',
        })}>{started ?? (showCourt ? expectedStart(e, zone, venueMode)
                                   : printedStart(e, zone, venueMode))}</span>
        {showCourt && e.court && <span className="sched-court">{e.court}</span>}
        {/* Court view keeps the sheet's wording, but "Followed by" alone does
            not tell you when to turn up. The chained estimate goes underneath.
            Only when it ADDS something: a slot whose expected time is simply
            the printed one would just repeat the line above it. */}
        {!started && !showCourt && e.expected_source === 'estimated' && e.expected_start_at && (
          <span className="sched-est">{expectedStart(e, zone, venueMode)}</span>
        )}
      </div>
      <div className="sched-row-main">
        <div className="sched-tags">
          {e.tour && <span className={clsx('sched-tag', `sched-tag--${e.tour.toLowerCase()}`)}>{e.tour}</span>}
          {e.round_label && <span className="sched-tag sched-tag--round">{e.round_label}</span>}
          {e.stage === 'qualifying' && <span className="sched-tag sched-tag--quali">Q</span>}
          {e.discipline !== 'singles' && <span className="sched-tag">{e.discipline === 'mixed' ? 'Mixed' : 'Doubles'}</span>}
        </div>
        <div className="sched-playrow">
        <div className={clsx('sched-players', { 'sched-players--pairs': e.discipline !== 'singles' })}>
          {/* "vs" rides with the FIRST team rather than sitting on its own
              line. Stacked pairs otherwise put it alone between them, which
              reads as a third row of the match. Singles are unaffected: the
              wrapper is inline, so "A vs B" still flows on one line. */}
          <span className="sched-teamline">
            <Side players={a} doubles={e.discipline !== 'singles'} tbd={!!e.tbd_side?.includes('a')} />
            <span className="sched-vs">vs</span>
          </span>
          <Side players={b} doubles={e.discipline !== 'singles'} tbd={!!e.tbd_side?.includes('b')} />
        </div>
        {score && <div className="sched-score">{score}</div>}
        </div>
      </div>
    </div>
  )
}

export default function Schedule() {
  const [params, setParams] = useSearchParams()
  const [view, setView] = useState(storedView)
  const [hideDone, setHideDone] = useState(false)
  const [tzMode, setTzMode] = useState(storedTz)

  const day = params.get('date') || isoDay(new Date())
  const tournamentId = params.get('tournament') ? Number(params.get('tournament')) : undefined
  // The draw we arrived from, if any. Drives both the back link and which tour
  // the time view opens on.
  const fromDraw = params.get('draw') ? Number(params.get('draw')) : undefined
  const [tour, setTour] = useState(null)      // null = not yet defaulted

  useEffect(() => { try { localStorage.setItem(VIEW_KEY, view) } catch {} }, [view])
  useEffect(() => { try { localStorage.setItem(TZ_KEY, tzMode) } catch {} }, [tzMode])

  const { data, isLoading } = useQuery({
    queryKey: ['schedule', day, tournamentId ?? 'all'],
    queryFn: () => getScheduleDay({ date: day, tournamentId }),
    staleTime: 30_000,
  })

  // Open on the tour of the draw we came from — someone who clicked OOP on the
  // men's draw wants the men's matches first. Only defaulted once, so a manual
  // choice is not overwritten when the day's data refreshes.
  const defaulted = useRef(false)
  useEffect(() => {
    if (defaulted.current || !data?.entries?.length) return
    defaulted.current = true
    if (!fromDraw) return
    const origin = data.entries.find(e => e.draw_id === fromDraw)
    if (origin?.tour) setTour(origin.tour)
  }, [data, fromDraw])

  // undefined => render in the reader's own zone, which is what toLocaleTimeString
  // does with no timeZone option.
  const venueTz = data?.tournaments?.find(t => t.venue_timezone)?.venue_timezone
  const zone = tzMode === 'venue' ? venueTz : undefined

  const tours = useMemo(() => {
    const t = new Set((data?.entries ?? []).filter(e => e.tour).map(e => e.tour))
    return [...t].sort()
  }, [data])

  const setDay = (iso) => {
    const next = new URLSearchParams(params)
    next.set('date', iso)
    setParams(next, { replace: true })
  }

  const entries = useMemo(() => {
    const all = data?.entries ?? []
    return all.filter(e => {
      // Discipline follows the VIEW rather than a toggle. Court view reproduces
      // the sheet — every match on it, doubles and mixed included — because the
      // running order of a court only makes sense if nothing is missing from
      // it. Time view is the curated list of what people are playing for, so
      // singles only.
      if (view === 'time' && e.discipline !== 'singles') return false
      // Tour filter is a TIME-view control. The court view reproduces the sheet,
      // and a court running both tours would read as if matches were missing.
      if (view === 'time' && tour && e.tour !== tour) return false
      if (hideDone && e.status === 'completed') return false
      return true
    })
  }, [data, view, hideDone, tour])

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
          const n = seedNumber(p.name)
          if (n != null && n < best) best = n
        }
      }
      return { name, list, best, count }
    })
    ranked.sort((a, b) =>
      a.best - b.best || b.count - a.count || a.name.localeCompare(b.name))
    return ranked.map(r => [r.name, r.list])
  }, [entries])

  return (
    <div className="sched-page">
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

      <div className="sched-filters">
        {fromDraw && (
          <Link className="sched-back" to={`/tournaments/${fromDraw}`}>‹ Back to draw</Link>
        )}
        {view === 'time' && tours.length > 1 && (
          <>
            {tours.map(t => (
              <button key={t}
                      className={clsx('sched-chip', `sched-chip--${t.toLowerCase()}`,
                                      { 'sched-chip--on': tour === t })}
                      onClick={() => setTour(tour === t ? null : t)}>{t}</button>
            ))}
          </>
        )}
        <button className={clsx('sched-chip', { 'sched-chip--on': hideDone })}
                onClick={() => setHideDone(v => !v)}>Hide completed</button>
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
        <div className="sched-list">
          {entries.map(e => <MatchRow key={e.id} e={e} showCourt zone={zone} venueMode={tzMode === 'venue'} />)}
        </div>
      )}

      {!isLoading && entries.length > 0 && view === 'court' && (
        <div className="sched-courts">
          {byCourt.map(([name, list]) => (
            <section className="sched-courtblock" key={name}>
              <h2 className="sched-courthead">{name}</h2>
              <div className="sched-list">
                {list.map(e => <MatchRow key={e.id} e={e} showCourt={false} zone={zone} venueMode={tzMode === 'venue'} />)}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}
