import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams, Link } from 'react-router-dom'
import clsx from 'clsx'
import { getScheduleDay } from '../api/schedule'
import { nationalityIso2, splitPlayerName } from '../utils/flags'
import './Schedule.css'

const VIEW_KEY = 'ua-schedule-view'

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

/** The sheet's own wording, verbatim — the whole point of the court view. */
function printedStart(e) {
  if (e.start_type === 'followed_by') return 'Followed by'
  if (e.start_type === 'not_before') return `Not before ${e.start_time_local ?? ''}`.trim()
  if (e.start_type === 'after_event') return 'After preceding'
  if (e.start_time_local) return e.start_time_local
  return 'TBA'
}

/** Estimated starts are hedged with a tilde so they never read as announced. */
function expectedStart(e) {
  if (!e.expected_start_at) return printedStart(e)
  const t = new Date(e.expected_start_at).toLocaleTimeString([], {
    hour: 'numeric', minute: '2-digit',
  })
  return e.expected_source === 'printed' ? t : `~${t}`
}

function liveLine(e) {
  // ESPN only. Doubles and qualifying carry no score by design — the sheet's
  // own score is a stale snapshot and is never shown.
  const ls = e.live_scores
  if (Array.isArray(ls) && ls.length >= 2 && Array.isArray(ls[0])) {
    const a = ls[0].join(' ')
    const b = ls[1].join(' ')
    if (a.trim() || b.trim()) return `${a}  |  ${b}`
  }
  const s = e.scores
  if (Array.isArray(s) && s.length) {
    try { return s.map(x => Array.isArray(x) ? x.join('-') : String(x)).join('  ') } catch { return null }
  }
  return null
}

/**
 * One player: flag, then name. Doubles shows surnames only — four full names on
 * one row does not fit a phone, and the surname is what identifies a pair
 * anyway.
 */
function PlayerName({ raw, surnameOnly, hideSeed }) {
  const { seed, first, last, nat } = splitPlayerName(raw)
  const iso2 = nationalityIso2(nat)
  return (
    <span className="sched-player">
      {/* The placeholder keeps names aligned when a nationality is missing, but
          it must be invisible — as a filled box it reads as a broken image. */}
      {iso2
        ? <span className={`fi fi-${iso2.toLowerCase()} sched-flag`} title={nat} />
        : <span className="sched-flag sched-flag--none" aria-hidden="true" />}
      <span className="sched-pname">
        {!hideSeed && seed && <span className="sched-seed">{seed}</span>}
        {surnameOnly ? last : [first, last].filter(Boolean).join(' ')}
      </span>
    </span>
  )
}

function Side({ players, doubles }) {
  if (!players.length) return <span className="sched-side">TBD</span>
  // A doubles seed belongs to the TEAM. The sheet repeats it against both
  // partners, which reads as two separately-seeded players.
  const teamSeed = doubles
    ? players.map(p => splitPlayerName(p.name).seed).find(Boolean) ?? null
    : null
  return (
    <span className="sched-side">
      {teamSeed && <span className="sched-seed sched-seed--team">{teamSeed}</span>}
      {players.map((p, i) => (
        <PlayerName key={`${p.side}${p.position}${i}`} raw={p.name}
                    surnameOnly={doubles} hideSeed={doubles} />
      ))}
    </span>
  )
}

function MatchRow({ e, showCourt }) {
  const a = e.players.filter(p => p.side === 'a')
  const b = e.players.filter(p => p.side === 'b')
  const score = liveLine(e)
  const done = e.status === 'completed'
  return (
    <div className={clsx('sched-row', {
      'sched-row--mine': e.is_my_pick,
      'sched-row--done': done,
      'sched-row--live': e.status === 'live',
    })}>
      <div className="sched-row-when">
        <span className="sched-time">{showCourt ? expectedStart(e) : printedStart(e)}</span>
        {showCourt && e.court && <span className="sched-court">{e.court}</span>}
      </div>
      <div className="sched-row-main">
        <div className="sched-tags">
          {e.tour && <span className={clsx('sched-tag', `sched-tag--${e.tour.toLowerCase()}`)}>{e.tour}</span>}
          {e.round_label && <span className="sched-tag sched-tag--round">{e.round_label}</span>}
          {e.stage === 'qualifying' && <span className="sched-tag sched-tag--quali">Q</span>}
          {e.discipline !== 'singles' && <span className="sched-tag">{e.discipline === 'mixed' ? 'Mixed' : 'Doubles'}</span>}
        </div>
        <div className={clsx('sched-players', { 'sched-players--pairs': e.discipline !== 'singles' })}>
          <Side players={a} doubles={e.discipline !== 'singles'} />
          <span className="sched-vs">vs</span>
          <Side players={b} doubles={e.discipline !== 'singles'} />
          {e.is_tbd && <span className="sched-tbd">opponent not settled</span>}
        </div>
        {score && <div className="sched-score">{score}</div>}
      </div>
      {e.draw_id && (
        <Link className="sched-jump" to={`/tournaments/${e.draw_id}`} title="Open this draw">›</Link>
      )}
    </div>
  )
}

export default function Schedule() {
  const [params, setParams] = useSearchParams()
  const [view, setView] = useState(storedView)
  const [hideDone, setHideDone] = useState(false)

  const day = params.get('date') || isoDay(new Date())
  const tournamentId = params.get('tournament') ? Number(params.get('tournament')) : undefined

  useEffect(() => { try { localStorage.setItem(VIEW_KEY, view) } catch {} }, [view])

  const { data, isLoading } = useQuery({
    queryKey: ['schedule', day, tournamentId ?? 'all'],
    queryFn: () => getScheduleDay({ date: day, tournamentId }),
    staleTime: 30_000,
  })

  const setDay = (iso) => {
    const next = new URLSearchParams(params)
    next.set('date', iso)
    setParams(next, { replace: true })
  }

  const entries = useMemo(() => {
    const all = data?.entries ?? []
    return all.filter(e => {
      // Discipline follows the VIEW rather than a toggle. Time view answers
      // "what is on today", so it carries everything — doubles, mixed and
      // qualifying included. Court view answers "what order is this court
      // running", where doubles is noise around the draws people play.
      if (view === 'court' && e.discipline !== 'singles') return false
      if (hideDone && e.status === 'completed') return false
      return true
    })
  }, [data, view, hideDone])

  const byCourt = useMemo(() => {
    const m = new Map()
    for (const e of entries) {
      const k = e.court || 'Unassigned'
      if (!m.has(k)) m.set(k, [])
      m.get(k).push(e)
    }
    for (const list of m.values()) list.sort((x, y) => x.court_order - y.court_order)
    return [...m.entries()]
  }, [entries])

  return (
    <div className="sched-page">
      <div className="sched-head">
        <div className="sched-daynav">
          <button className="sched-nav-btn" onClick={() => setDay(shiftDay(day, -1))} aria-label="Previous day">‹</button>
          <div className="sched-day">
            <span className="sched-day-label">{prettyDay(day)}</span>
          </div>
          <button className="sched-nav-btn" onClick={() => setDay(shiftDay(day, 1))} aria-label="Next day">›</button>
        </div>

        {(data?.tournaments ?? []).filter(t => t.oop_url).map(t => (
          <a key={t.id} className="sched-pdf" href={t.oop_url}
             target="_blank" rel="noopener noreferrer"
             title={`${t.name} — official order of play (PDF)`}>
            PDF
          </a>
        ))}

        <div className="sched-viewswitch" role="tablist">
          <button role="tab" aria-selected={view === 'time'}
                  className={clsx('sched-viewbtn', { 'sched-viewbtn--on': view === 'time' })}
                  onClick={() => setView('time')}>Time</button>
          <button role="tab" aria-selected={view === 'court'}
                  className={clsx('sched-viewbtn', { 'sched-viewbtn--on': view === 'court' })}
                  onClick={() => setView('court')}>Court</button>
        </div>
      </div>

      <div className="sched-filters">
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
          {entries.map(e => <MatchRow key={e.id} e={e} showCourt />)}
        </div>
      )}

      {!isLoading && entries.length > 0 && view === 'court' && (
        <div className="sched-courts">
          {byCourt.map(([name, list]) => (
            <section className="sched-courtblock" key={name}>
              <h2 className="sched-courthead">{name}</h2>
              <div className="sched-list">
                {list.map(e => <MatchRow key={e.id} e={e} showCourt={false} />)}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}
