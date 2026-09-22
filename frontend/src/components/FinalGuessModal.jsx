/* THE TIEBREAK QUESTIONS (owner, 2026-09-18).
 *
 * When a user enters a draw they are asked two things about the singles
 * final: how many aces the champion will hit, and how long it will last.
 * Level on points, brackets are separated by whoever came closest on aces,
 * then on minutes, once the final is played. Each slider runs from 0 — a
 * walkover — to the most it has ever been on this tour, in this format, on
 * this surface, and beside it sits the most useful figure we hold about the
 * player the user has picked to win: their aces and minutes per set on this
 * surface, and against the runner-up they picked whenever the two have met.
 */
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getFinalGuess, putFinalGuess } from '../api/tournaments'
import './FinalGuessModal.css'

export const finalGuessKey = (id) => ['final-guess', String(id)]

/* WHERE IT SHOWS AT ALL (owner, 2026-09-18: "do not show the tiebreak button
   or popup at all until next week's draw start"). The questions are about a
   final nobody has played and can only be answered while the picks are open,
   so: an open draw asks, an answered draw reads back, and this week's locked
   unanswered draws show nothing. No date is written down — next week's draws
   open for picks and it appears by itself. */
export const tiebreakVisible = (ctx) => !!ctx && (!ctx.locked || !!ctx.guess)

export function useFinalGuess(id, enabled) {
  return useQuery({ queryKey: finalGuessKey(id), queryFn: () => getFinalGuess(id), enabled: !!enabled && !!id })
}

export function fmtMinutes(m) {
  if (m == null) return '–'
  const h = Math.floor(m / 60), mm = m % 60
  return h ? `${h}h ${String(mm).padStart(2, '0')}m` : `${mm}m`
}

/* EVERY DURATION IN THE DIALOG CARRIES BOTH FORMS (owner, 2026-09-19): the
   clock reading and the plain minutes. The slider answers in minutes and the
   references read in hours, and converting between them while comparing the
   two is the one job this dialog should not hand back. Under an hour the two
   forms are the same number, so it is said once. */
export function fmtLong(m) {
  if (m == null) return '–'
  return m >= 60 ? `${fmtMinutes(m)} (${m} min)` : `${m} min`
}

const perSet = (r, key) => (r && r[key] != null ? r[key] : null)

/* THE PICKED FINAL, IN A LINE (owner, 2026-09-19): "Ostapenko def. Birrell".
   Surnames, on the bracket's own reading of where a surname starts — every
   token after the first — so "Díaz Acosta" survives whole (CombinedView's
   lastNameOf). */
const surname = (full) => {
  const parts = String(full || '').trim().split(/\s+/)
  return parts.length > 1 ? parts.slice(1).join(' ') : parts[0]
}

function finalLine(ctx) {
  const champ = ctx?.champion?.name
  if (!champ) return null
  const run = ctx?.runner_up?.name
  return run ? `${surname(champ)} def. ${surname(run)}` : surname(champ)
}

/* ── The reference rows, per question ─────────────────────────────────────
   Conditioned on THIS draw — its tour, its tier, its surface — and on the two
   players picked, with each window stated. Same figures and same rules as the
   app's wizard (mobile/finalGuess.jsx); the site keeps them on one page.

   Durations arrive PRE-COMPUTED for each set count. A per-set duration is
   playing time with the changeovers stripped out, so putting the right number
   back for the predicted length is the server's job — a multiply here would
   carry the history's break count instead (owner's correction, 2026-09-19). */
const met = (n) => `${n} H2H ${n === 1 ? 'match' : 'matches'}`
const round1 = (n) => (n == null ? null : Math.round(n * 10) / 10)

function rowsFor(ctx, which, sets) {
  if (!ctx) return []
  const a = surname(ctx.champion?.name), b = surname(ctx.runner_up?.name)
  const surf = (ctx.surface || '').toLowerCase()
  const rows = []
  if (which === 'sets') {
    const q = ctx.sets_question || {}
    const where = q.tier_finals?.surface_scoped === false ? 'all surfaces' : surf
    if (q.tier_finals?.sets_per_match != null) {
      rows.push([`recent ${ctx.tier_label} finals on ${where}`,
                 q.tier_finals.sets_per_match, `${q.tier_finals.matches} finals`])
    }
    if (q.h2h?.on_surface) {
      rows.push([`${a} v ${b} on ${surf}`, q.h2h.on_surface.sets_per_match,
                 met(q.h2h.on_surface.matches)])
    }
    if (q.h2h?.overall && q.h2h.off_surface > 0) {
      rows.push([`${a} v ${b}, all surfaces`, q.h2h.overall.sets_per_match,
                 met(q.h2h.overall.matches)])
    }
    return rows
  }
  if (which === 'aces') {
    const q = ctx.aces_question || {}
    const where = q.tier_finals?.surface_scoped === false ? 'all surfaces' : surf
    const scale = (r) => (r?.aces_per_set == null ? null : round1(r.aces_per_set * sets))
    if (q.tier_finals?.aces_per_set != null) {
      rows.push([`recent ${sets}-set ${ctx.tier_label} finals on ${where}`,
                 scale(q.tier_finals), `${q.tier_finals.matches} finals`])
    }
    if (q.champion_vs?.aces_per_set != null) {
      rows.push([`${sets}-set ${a} v ${b} matches on ${surf}`, scale(q.champion_vs),
                 met(q.champion_vs.matches)])
    }
    if (q.champion_on_surface?.aces_per_set != null) {
      rows.push([`${sets}-set ${a} matches on ${surf}`, scale(q.champion_on_surface),
                 `${q.champion_on_surface.matches} matches`])
    }
    return rows
  }
  const q = ctx.minutes_question || {}
  const where = q.tier_finals?.surface_scoped === false ? 'all surfaces' : surf
  const key = String(sets)
  if (q.tier_minutes_by_sets?.[key] != null) {
    rows.push([`recent ${sets}-set ${ctx.tier_label} finals on ${where}`,
               fmtMinutes(q.tier_minutes_by_sets[key]), `${q.tier_finals?.matches ?? ''} finals`.trim()])
  }
  if (q.champion_on_surface?.by_sets?.[key] != null) {
    rows.push([`recent ${sets}-set ${a} matches on ${surf}`,
               fmtMinutes(q.champion_on_surface.by_sets[key]),
               `${q.champion_on_surface.matches} matches`])
  }
  if (q.h2h_estimate?.by_sets?.[key] != null) {
    rows.push([`${sets}-set ${a} v ${b} matches on ${surf}, estimated`, fmtMinutes(q.h2h_estimate.by_sets[key]),
               met(q.h2h_estimate.matches)])
  }
  return rows
}

/* EVERY ROW IS AN AVERAGE, AND EVERY FIGURE CARRIES ITS UNIT (owner,
   2026-09-22). The rows read as bare facts — "WTA 500 finals on hard, past 10
   years … 2.4" — which is a count of finals as easily as an average per final,
   and 2.4 of nothing in particular. The row says WHAT it is about; the one
   word they all share is said once, here.

   `unit` is the word after each figure, omitted where the figure already
   reads as its own — "1h 46m" needs no noun after it.

   THE SET COUNT IS IN THE LABELS, NOT A COLUMN HEAD (owner, 2026-09-22). With
   each figure on its own line under its sentence there is no column left for a
   head to sit over, so every scaled row states the set count itself. */
function Reference({ ctx, which, sets, unit }) {
  const rows = rowsFor(ctx, which, sets)
  if (!rows.length) {
    return <p className="fg-muted">{ctx?.champion?.name
      ? `No history held for ${surname(ctx.champion.name)} yet`
      : 'Pick your champion in the draw to see their history here'}</p>
  }
  return (
    /* TWO LINES PER ROW, NOT THREE COLUMNS (owner, 2026-09-22). The
       description is the longest thing here and it was sharing a row with a
       figure column and a sample column, so it wrapped while two thirds of the
       width sat empty beside it. Given the full width it reads on one line,
       and the figure and its sample go underneath — which is their real
       relationship anyway: both are about the sentence above them.

       A list rather than a table, because with the columns gone there is no
       grid left to be a table OF. */
    <div className="fg-refs">
      {/* The block says what it is: under a question and its answer sat a run
          of sentences with numbers, and nothing said they were evidence. */}
      <p className="fg-refs-title">Reference data:</p>
      {rows.map(([label, value, note]) => (
        <div className="fg-ref" key={label}>
          {/* "Avg", not "Average": the word is on every row and what follows
              it is the part that differs. The colon is what makes the figure
              below read as this sentence's answer rather than a new line. */}
          <p className="fg-ref-label">Avg for {label}:</p>
          <p className="fg-ref-figures">
            <span className="fg-td-value">
              {value}{unit && <span className="fg-td-unit"> {unit}</span>}
            </span>
            {/* "(Over 82 finals)" — the count is the SAMPLE the average was
                taken over, said once here as "Avg for" is. Bracketed because
                it is an aside about the figure, not a second figure. */}
            {note && <span className="fg-td-note">(Over {note})</span>}
          </p>
        </div>
      ))}
    </div>
  )
}

export default function FinalGuessModal({ tournamentId, open, onClose, reason }) {
  const qc = useQueryClient()
  const { data: ctx, isLoading } = useFinalGuess(tournamentId, open)
  const [sets, setSets] = useState(null)
  const [aces, setAces] = useState(null)
  const [minutes, setMinutes] = useState(null)
  const acesMax = Math.max(1, ctx?.ceilings?.aces_max || 0)
  /* The end of the duration track is the longest match of the length being
     predicted — see mobile/finalGuess.jsx, where the rule is written out. It
     moves with the sets answer, and the old any-length end is the fallback. */
  const durMax = Math.max(1, ctx?.ceilings?.duration_max_by_sets?.[String(sets)]
                             || ctx?.ceilings?.duration_max_min || 0)
  const durYears = ctx?.ceilings?.duration_ceiling_years || 3
  const bestOf = ctx?.best_of || 3

  // Seed the sliders once the context arrives: the saved answers, else a
  // sensible middle — the champion's rate times a typical number of sets.
  useEffect(() => {
    if (!ctx) return
    const lengths = (ctx.best_of === 5) ? [3, 4, 5] : [2, 3]
    setSets(ctx.guess?.final_sets ?? ctx.default?.sets ?? lengths[0])
    if (ctx.guess) { setAces(ctx.guess.final_aces); setMinutes(ctx.guess.final_duration_min); return }
    // THE SLIDERS OPEN ON THE DEFAULT — what this bracket holds if it never
    // touches them (owner, 2026-09-18): last year's average for this gender,
    // surface and format.
    if (ctx.default) { setAces(ctx.default.aces); setMinutes(ctx.default.minutes); return }
    // Read off `ctx`, not off the derived ceilings: this effect sets the set
    // count and durMax is derived FROM it, so listing durMax here seeded the
    // answer back on every change — see mobile/finalGuess.jsx for the incident.
    setAces(Math.round(Math.max(1, ctx.ceilings?.aces_max || 0) / 4))
    setMinutes(Math.round(Math.max(1, ctx.ceilings?.duration_max_min || 0) / 3))
  }, [ctx])     // eslint-disable-line react-hooks/exhaustive-deps

  // An answer cannot outlive its scale: the ceiling moves with the set count.
  useEffect(() => {
    setMinutes(m => (m == null ? m : Math.min(m, durMax)))
  }, [durMax])

  const save = useMutation({
    mutationFn: () => putFinalGuess(tournamentId, {
      final_sets: sets, final_aces: aces, final_duration_min: minutes,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: finalGuessKey(tournamentId) }); onClose?.() },
  })

  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') onClose?.() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const record = ctx?.ceilings
  /* THE SAME WORDS AS THE APP (owner, 2026-09-19). "Tiebreak" alone did not
     say what it breaks a tie IN — the league standings, not a tiebreak in the
     tennis sense, which is the more obvious reading of the word on a draw
     page. `reason` no longer changes the heading: the dialog is the same thing
     however it was opened. */
  const title = 'Standings Tiebreak Questions'
  if (!open) return null
  return createPortal(
    <div className="profile-modal-backdrop" onClick={onClose}>
      <div className="profile-modal fg-modal" onClick={e => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Tiebreak">
        <div className="profile-edit-form">
          <p className="profile-edit-title">{title}</p>
          {/* WHAT THE QUESTIONS ARE FOR, before the match they are about. This
              replaces a line that sat lower and said the same thing more
              narrowly — "final score ties" read as a tie in the final's SCORE
              rather than a tie in the table (owner, 2026-09-19). */}
          <p className="fg-intro">
            Ties occurring in the final standings of all leagues will be decided
            by the questions which follow.
          </p>
          {/* The bracket's own answer to "which final?", so the two questions
              below are about a match the reader can see named. */}
          <p className="fg-intro">
            Reference data will be provided to you based on your predicted champion (and finalist):
            <strong className="fg-final">{finalLine(ctx) || 'No champion picked yet'}</strong>
          </p>
          {ctx && !ctx.guess && ctx.default && (
            <p className="fg-intro">
              Leave this alone and you hold {ctx.tour} {ctx.surface.toLowerCase()}'s {ctx.default.year} average:
              {` ${ctx.default.sets ?? ''} sets, ${ctx.default.aces} aces, ${fmtLong(ctx.default.minutes)}`}.
            </p>
          )}
          {isLoading || aces == null || sets == null ? <p className="fg-muted">Loading the history…</p> : (
            <>
              {/* THE SETS QUESTION COMES FIRST — it is compared first, and it
                  is the multiplier the other two questions' figures are scaled
                  by (owner, 2026-09-19). The app asks the three one per page;
                  the site keeps them on one. */}
              <section className="fg-q">
                <span className="fg-label">How many sets will the final be?</span>
                <div className="fg-setrow">
                  {((ctx.best_of === 5) ? [3, 4, 5] : [2, 3]).map(n => (
                    <button key={n} type="button" disabled={ctx?.locked}
                            aria-pressed={sets === n}
                            className={`fg-setbtn${sets === n ? ' fg-setbtn--on' : ''}`}
                            onClick={() => setSets(n)}>
                      <strong>{n}</strong> sets
                    </button>
                  ))}
                </div>
                <Reference ctx={ctx} which="sets" sets={sets} unit="sets" />
              </section>
              <section className="fg-q">
                <label className="fg-label" htmlFor="fg-aces">How many aces will the champion hit in the final?</label>
                <div className="fg-row">
                  <input id="fg-aces" type="range" min={0} max={acesMax} step={1} value={aces}
                         onChange={e => setAces(Number(e.target.value))} disabled={ctx?.locked} />
                  <output className="fg-value" htmlFor="fg-aces">{aces}</output>
                </div>
                {/* NO FLOOR LABEL AND NO "the most in 12 months" (owner,
                    2026-09-22). Zero MINUTES is a walkover and needs saying;
                    zero ACES is an ordinary afternoon — "women will often hit
                    0 aces over a full match" — so the label was wrong. And the
                    record holder is the part a reader gets something from; the
                    phrase in front of it only repeated what the number is. */}
                <div className="fg-ends">
                  <span>0</span>
                  <span className="fg-ends-max">
                    {acesMax}
                    {record?.aces_record && ` · ${record.aces_record.player}, ${record.aces_record.tournament} ${record.aces_record.year}`}
                  </span>
                </div>
                <Reference ctx={ctx} which="aces" sets={sets} unit="aces" />
              </section>
              <section className="fg-q">
                <label className="fg-label" htmlFor="fg-min">How long will the final last?</label>
                <div className="fg-row">
                  <input id="fg-min" type="range" min={0} max={durMax} step={1} value={minutes}
                         onChange={e => setMinutes(Number(e.target.value))} disabled={ctx?.locked} />
                  <output className="fg-value" htmlFor="fg-min">{fmtMinutes(minutes)}<small>{minutes} min</small></output>
                </div>
                <div className="fg-ends">
                  <span>0 · walkover</span>
                  {/* "12 month max", not "the longest on hard in 12 months
                      (Ningbo 2025)" (owner, 2026-09-22): three lines to say
                      what the number beside them already says. */}
                  <span className="fg-ends-max">{fmtMinutes(durMax)} · {sets}-set max, {durYears} yrs</span>
                </div>
                {/* No unit: fmtMinutes already reads as one ("1h 46m"). */}
                <Reference ctx={ctx} which="minutes" sets={sets} />
              </section>
              {ctx?.actual && (
                <p className="fg-actual">The final: {ctx.actual.final_sets ?? '–'} sets, {ctx.actual.final_aces} aces, {fmtLong(ctx.actual.final_duration_min)}.</p>
              )}
              <div className="fg-actions">
                <button type="button" className="fg-btn fg-btn--quiet" onClick={onClose}>{ctx?.locked ? 'Close' : 'Later'}</button>
                {!ctx?.locked && (
                  <button type="button" className="fg-btn" onClick={() => save.mutate()} disabled={save.isPending}>
                    {save.isPending ? 'Saving…' : 'Save answers'}
                  </button>
                )}
              </div>
              {save.isError && <p className="fg-error">Could not save — {save.error?.response?.data?.detail || 'try again'}.</p>}
            </>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}

/* The line on the draw page: the answers as they stand, and the way in. */
export function FinalGuessBar({ tournamentId, enabled, onOpen }) {
  const { data: ctx } = useFinalGuess(tournamentId, enabled)
  if (!enabled || !tiebreakVisible(ctx)) return null
  const g = ctx.guess
  /* RED WHEN THE ANSWERS NO LONGER DESCRIBE THE PICKED FINAL (owner,
     2026-09-22). `stale` is the server's answer, not a guess from a timestamp:
     it compares the final these answers were saved for against the one the
     bracket now predicts (models/final_guess.answers_are_stale). Opening the
     dialog does not clear it — SAVING does, because re-reading answers that
     are about the wrong two players changes nothing. */
  return (
    <button type="button" className={`fg-bar${ctx.stale ? ' fg-bar--stale' : ''}`}
            onClick={onOpen}
            title={ctx.stale ? 'Your answers were given for a different final' : undefined}
            aria-label={ctx.stale
              ? 'Standings tiebreak questions — your answers were given for a different final'
              : undefined}>
      {ctx.stale && <span className="fg-bar-stale-tag" aria-hidden="true">!</span>}
      {/* ONE LINE AND THE ANSWERS (owner, 2026-09-19). The picked final and the
          sentence about ties live in the dialog — "only visible once you click
          in" — so this stays the quiet way in that it was. */}
      <span className="fg-bar-label">Standings Tiebreak Questions</span>
      {g ? <span className="fg-bar-value">{[g.final_sets ? `${g.final_sets} sets` : null, `${g.final_aces} aces`, fmtMinutes(g.final_duration_min)].filter(Boolean).join(' · ')}</span>
         : ctx.default ? <span className="fg-bar-value fg-bar-value--ask">Holding the average: {ctx.default.aces} aces · {fmtMinutes(ctx.default.minutes)}</span>
         : <span className="fg-bar-value fg-bar-value--ask">{ctx.locked ? 'No answers given' : 'Answer the two questions about the final'}</span>}
      {ctx.actual && <span className="fg-bar-actual">final: {ctx.actual.final_aces} · {fmtMinutes(ctx.actual.final_duration_min)}</span>}
    </button>
  )
}
