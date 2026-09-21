/*
 * THE SEASON, WALKED A DAY AT A TIME.
 *
 *   node src/utils/drawStatus.rehearsal.test.mjs
 *
 * WHY A REHEARSAL AND NOT MORE UNIT TESTS. drawStatus.test.mjs asks "on this
 * day, where does this draw belong" and answers it twelve times. Every bucket
 * bug the owner has reported was instead about a TRANSITION — a draw that
 * moved when it should not have, or did not move when it should — and no
 * single-day test can see one, because a transition is a relationship between
 * two days. The owner's words, 2026-09-21: "I want to stop babysitting these
 * constant bugs where draws change their status as we progress through the
 * weeks."
 *
 * So this builds a synthetic season, advances the clock one day at a time
 * across three months, records where every draw sits on every day, and then
 * asserts properties of the WHOLE TIMELINE.
 *
 * WHAT IT DOES NOT DO. The server decides a draw's `status`; that is Python
 * (`Draw.computed_status`) and cannot be imported here. `serverStatus` below
 * models it — released/start/end dates in, one of the four words out — so
 * what this rehearsal tests is the CLIENT's derivation given a plausible
 * server answer. Where the model and the real property disagree the model is
 * wrong and should be corrected here; it deliberately does not try to
 * reproduce the match-by-match locking rules, which do not affect bucketing.
 *
 * VALIDATED BY MUTATION, because a green harness that cannot fail is worse
 * than no harness. Each of these deliberate breakages is caught by at least
 * one property below; two of them survived the first draft and the fixtures
 * were widened until they did not:
 *
 *   recency bound removed                     Last Week reaches back months
 *   a run holding an active draw is skipped   the backwards move this found
 *   cohort by date run alone                  the Guadalajara weld
 *   cohort by tournament_id alone             the Hong Kong weld
 *   a cohort never retires                    nothing ever leaves Active
 *   a completed draw is always Previous       Last Week unreachable
 *   a completed draw is always Active         nothing ever finishes
 *
 * If a property stops catching its mutation, the fixtures have gone stale,
 * not the rule.
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'

/* ── the clock ──────────────────────────────────────────────────────────────
 * drawStatus.js holds today's Pacific date for 60 seconds, so a stub that
 * freezes Date.now() would pin the whole season to its first day. Advancing
 * the simulated instant by a day per step defeats that cache honestly — the
 * same way real time does. */
let NOW = null
const at = (day) => new Date(`${day}T12:00:00Z`).getTime()

const src = readFileSync(new URL('./drawStatus.js', import.meta.url), 'utf8')
const RealDate = Date
globalThis.Date = class extends RealDate {
  constructor(...args) { super(...(args.length ? args : [NOW])) }
  static now() { return NOW }
}
const { computeCohortInfo, getDisplayStatus, getHomeSection, DISPLAY_STATUS_LABELS } =
  await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'))

/* ── the season ─────────────────────────────────────────────────────────────
 * Shapes taken from the real 2026 calendar, including the ones that have
 * caused bugs: a combined event whose halves run different lengths, an 11-day
 * 1000 overlapping a 250, two events sharing a name months apart, and a week
 * whose events finish on four different days. */
const iso = (d) => d.toISOString().slice(0, 10)
const plus = (day, n) => {
  const d = new RealDate(`${day}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + n)
  return iso(d)
}

// id, tournament_id, start, length in days, label
const SEASON = [
  // A combined week: one row, two draws, the women's final a day later.
  [1, 500, '2026-09-14', 6, 'Combined M'],
  [2, 500, '2026-09-14', 7, 'Combined W'],
  // Two unrelated events finishing a day apart — the Guadalajara shape.
  [3, 900, '2026-09-13', 6, 'Guadalajara-like'],
  [4, 901, '2026-09-15', 6, 'SP-Open-like'],
  // A week where four events end on four different days.
  [5, 910, '2026-09-21', 6, 'Ragged week A'],
  [6, 911, '2026-09-21', 5, 'Ragged week B'],
  [7, 912, '2026-09-22', 6, 'Ragged week C'],
  [8, 913, '2026-09-23', 6, 'Ragged week D'],
  // An 11-day 1000 overlapping the 250s that start inside it.
  [9, 920, '2026-09-30', 11, 'Long 1000'],
  [10, 921, '2026-09-30', 6, '250 inside it'],
  [11, 922, '2026-10-05', 7, '250 starting mid-1000'],
  // A Slam fortnight.
  [12, 930, '2026-10-12', 14, 'Slam M'],
  [13, 930, '2026-10-12', 14, 'Slam W'],
  // The Hong Kong shape, now split into two rows as production has it.
  [14, 940, '2026-09-07', 6, 'Namesake (early)'],
  [15, 941, '2026-11-02', 6, 'Namesake (late)'],
  // A draw that never gets a tournament_id — its own event, by the rule.
  [16, null, '2026-10-19', 6, 'Orphan draw'],
  /* ONE ROW HOLDING TWO EVENTS MONTHS APART. Production was in exactly this
     state until 2026-09-21 — four rows each held an ATP and a WTA event that
     share a city's name — and it is the state a regression in
     services/events.py::attach would return it to. Without this pair, a
     cohort grouped by tournament_id alone (the Hong Kong bug) survives the
     whole rehearsal untouched; proven by mutation. */
  [17, 950, '2026-09-07', 6, 'Conflated row (early half)'],
  [18, 950, '2026-11-09', 6, 'Conflated row (late half)'],
]

const DRAWS = SEASON.map(([id, tournament_id, start, len, label]) => ({
  id, tournament_id, label,
  start_date: start,
  end_date: plus(start, len),
  // Draws are released a week out; that is what turns 'upcoming' into 'open'.
  released_on: plus(start, -7),
}))

/* The server's answer, modelled — and CHECKED against the real property on
 * 2026-09-21 by walking Draw.computed_status across a 6-day week, which
 * corrected two things this model had wrong:
 *
 *   ON THE START DATE ITSELF a draw reads 'open', not 'active'. The property
 *   only says 'active' on day 0 once picks have locked or closing_time has
 *   passed; until the first ball the bracket is still pickable.
 *
 *   THE COMPLETION FALLBACK IS `(today - start_date) > 14 days`, which owes
 *   nothing to end_date. It never fires on a healthy draw because the scrapers
 *   stamp status='completed' when the final is decided — which is what this
 *   models — but when a scrape dies mid-event it leaves eight days of a
 *   finished tournament reading Active. That fault is upstream of every line
 *   in drawStatus.js and no client rule can repair it, so it is not modelled
 *   here: it belongs to backend draw_invariants.py's
 *   `not_completed_after_its_end`, which now catches it. */
function serverStatus(draw, day) {
  if (day > draw.end_date) return 'completed'          // the scrapers stamp it
  if (day > draw.start_date) return 'active'
  if (day >= draw.released_on) return 'open'           // incl. the start date
  return 'upcoming'
}

/* The walk runs a month past the last event on purpose: a real calendar has
 * gaps — the weeks after a Slam, and the off-season — and a bucket rule that
 * is only ever asked about a busy week is a rule whose recency handling is
 * never exercised. Proven by mutation: without this tail, raising
 * LAST_WEEK_MAX_AGE_DAYS to 9999 broke nothing. */
const days = []
for (let d = '2026-09-01'; d <= '2026-12-20'; d = plus(d, 1)) days.push(d)

/* ── walk it ────────────────────────────────────────────────────────────── */
const timeline = new Map(DRAWS.map(d => [d.id, []]))
const perDay = new Map()

for (const day of days) {
  NOW = at(day)
  const list = DRAWS.map(d => ({ ...d, status: serverStatus(d, day) }))
  const info = computeCohortInfo(list)
  const today = { day, sections: new Map(), home: new Map() }
  for (const t of list) {
    const section = getDisplayStatus(t, info)
    today.sections.set(t.id, section)
    today.home.set(t.id, getHomeSection(t, info))
    timeline.get(t.id).push({ day, section, status: t.status })
  }
  perDay.set(day, today)
}

/* ── the properties ─────────────────────────────────────────────────────── */
let checks = 0
const failures = []
function property(name, fn) {
  try { fn(); checks += 1; console.log(`  ok  ${name}`) } catch (e) {
    failures.push({ name, message: e.message })
    console.log(`  FAIL ${name}\n       ${e.message}`)
  }
}

const byId = new Map(DRAWS.map(d => [d.id, d]))
const ORDER = ['upcoming', 'open', 'active', 'lastweek', 'previous']

property('every draw lands in a known section on every day', () => {
  for (const [id, steps] of timeline) {
    for (const s of steps) {
      assert.ok(ORDER.includes(s.section),
        `draw ${id} on ${s.day}: section ${JSON.stringify(s.section)}`)
      assert.ok(DISPLAY_STATUS_LABELS[s.section], `no label for ${s.section}`)
    }
  }
})

property('a draw never appears in two Home sections at once', () => {
  for (const { day, home } of perDay.values()) {
    for (const [id, section] of home) {
      if (section !== null) {
        assert.ok(['open', 'active', 'lastweek', 'upcoming'].includes(section),
          `draw ${id} on ${day}: Home section ${section}`)
      }
    }
  }
})

property('a draw never moves backwards through the season', () => {
  /* The whole point of the rehearsal. upcoming → open → active → lastweek →
     previous is the only direction a draw may travel; anything else is a draw
     the owner watches jump about. */
  for (const [id, steps] of timeline) {
    let high = 0
    for (const s of steps) {
      const rank = ORDER.indexOf(s.section)
      if (rank < high) {
        const before = steps.find(x => ORDER.indexOf(x.section) === high)
        assert.fail(
          `draw ${id} (${byId.get(id).label}) went ${ORDER[high]} → ${s.section} ` +
          `on ${s.day} (was ${ORDER[high]} on ${before.day}); ` +
          `end_date ${byId.get(id).end_date}`)
      }
      high = Math.max(high, rank)
    }
  }
})

property('no draw stays Active more than a day past its own event', () => {
  /* A cohort holds until Pacific midnight on its last member's end date. One
     day of grace past the EVENT's end is the rule; more than that is the
     Guadalajara complaint. */
  for (const [id, steps] of timeline) {
    const draw = byId.get(id)
    const sameEvent = DRAWS.filter(d => d.tournament_id != null
      ? d.tournament_id === draw.tournament_id : d.id === draw.id)
    const eventEnd = sameEvent.map(d => d.end_date).sort().at(-1)
    for (const s of steps) {
      if (s.section === 'active' && s.day > eventEnd) {
        assert.fail(`draw ${id} (${draw.label}) still Active on ${s.day}, ` +
          `its event ended ${eventEnd}`)
      }
    }
  }
})

property('a finished event is never held Active by an unrelated event', () => {
  for (const [id, steps] of timeline) {
    const draw = byId.get(id)
    for (const s of steps) {
      if (s.section === 'active' && s.status === 'completed' && s.day > draw.end_date) {
        /* Lawful only if a draw PLAYED WITH THIS ONE is still going: the
           men's final does not retire a combined event while the women's is
           on court. Sharing a tournament_id is not enough — that is the Hong
           Kong bug, where a January draw was excused by a November one ten
           months later. SAME_EVENT_DAYS in services/events.py is 10. */
        const sibling = DRAWS.some(d => d.id !== draw.id
          && d.tournament_id != null && d.tournament_id === draw.tournament_id
          && d.end_date >= s.day
          && Math.abs((new RealDate(d.end_date) - new RealDate(draw.end_date))
                      / 86400000) <= 10)
        assert.ok(sibling, `draw ${id} (${draw.label}) held Active on ${s.day} ` +
          `with no sibling of its own event still playing`)
      }
    }
  }
})

property('Last Week is one week of play, not a run of them', () => {
  for (const { day, sections } of perDay.values()) {
    const lw = [...sections].filter(([, s]) => s === 'lastweek').map(([id]) => byId.get(id))
    if (lw.length < 2) continue
    const ends = lw.map(d => d.end_date).sort()
    const spanDays =
      (new RealDate(ends.at(-1)) - new RealDate(ends[0])) / 86400000
    assert.ok(spanDays <= 3,
      `on ${day} Last Week spans ${spanDays}d: ` +
      lw.map(d => `${d.label} ends ${d.end_date}`).join(', '))
  }
})

property('every draw leaves Active, and only the newest finished week is Last Week', () => {
  /* The first draft of this property asserted every draw ends the walk in
     Previous, which was simply wrong: the most recently finished week keeps
     the Last Week heading until something newer finishes, and at the end of
     the walk that week is the last one played. The real property is that
     nothing is still Active, and that Last Week is the newest finished week. */
  const last = perDay.get(days.at(-1))
  const ended = DRAWS.filter(d => d.end_date <= days.at(-1))
  for (const d of ended) {
    const section = last.sections.get(d.id)
    assert.ok(section === 'previous' || section === 'lastweek',
      `draw ${d.id} (${d.label}) ends the walk as ${section}`)
  }
  const lw = ended.filter(d => last.sections.get(d.id) === 'lastweek')
  const newest = ended.map(d => d.end_date).sort().at(-1)
  for (const d of lw) {
    const gap = (new RealDate(newest) - new RealDate(d.end_date)) / 86400000
    assert.ok(gap <= 3, `draw ${d.id} (${d.label}) ends ${d.end_date} but still ` +
      `wears Last Week with ${newest} finished`)
  }
})

property('a week that has just finished is visible under Last Week', () => {
  /* Without this, deleting the Last Week branch entirely passes every other
     property — proven by mutation. Each event is checked on the day after its
     own cohort finished: unless something newer has finished by then, it must
     wear the heading. */
  for (const d of DRAWS) {
    const dayAfter = plus(d.end_date, 1)
    const today = perDay.get(dayAfter)
    if (!today) continue
    const newerFinished = DRAWS.some(o => o.end_date > d.end_date
      && o.end_date < dayAfter)
    if (newerFinished) continue
    const section = today.sections.get(d.id)
    assert.ok(section === 'lastweek' || section === 'active',
      `draw ${d.id} (${d.label}) finished ${d.end_date} and reads ${section} ` +
      `on ${dayAfter} — Last Week is unreachable`)
  }
  const everLastWeek = new Set()
  for (const { sections } of perDay.values()) {
    for (const [id, s] of sections) if (s === 'lastweek') everLastWeek.add(id)
  }
  assert.ok(everLastWeek.size >= DRAWS.length - 2,
    `only ${everLastWeek.size} of ${DRAWS.length} draws ever reach Last Week`)
})

property('Last Week never reaches back more than a fortnight', () => {
  for (const { day, sections } of perDay.values()) {
    for (const [id, section] of sections) {
      if (section !== 'lastweek') continue
      const d = byId.get(id)
      const age = (new RealDate(day) - new RealDate(d.end_date)) / 86400000
      assert.ok(age <= 14,
        `on ${day}, draw ${id} (${d.label}) ended ${d.end_date} — ${age}d ago — ` +
        `and still reads Last Week`)
    }
  }
})

property('a draw is Active on the day its own final is played', () => {
  for (const [id, steps] of timeline) {
    const draw = byId.get(id)
    const onFinalDay = steps.find(s => s.day === draw.end_date)
    if (!onFinalDay) continue
    assert.equal(onFinalDay.section, 'active',
      `draw ${id} (${draw.label}) reads ${onFinalDay.section} on its last day`)
  }
})

/* ── report ─────────────────────────────────────────────────────────────── */
console.log(`\n  ${days.length} days, ${DRAWS.length} draws, ` +
            `${days.length * DRAWS.length} placements`)
if (failures.length) {
  console.log(`\n  ${failures.length} propert${failures.length === 1 ? 'y' : 'ies'} violated`)
  process.exitCode = 1
} else {
  console.log(`  ${checks} properties hold`)
}
