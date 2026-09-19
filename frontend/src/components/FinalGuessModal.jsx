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
import { useEffect, useMemo, useState } from 'react'
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

/* One line of reference, in words a person would say. */
function Reference({ ctx, which }) {
  const champ = ctx?.champion?.name
  const run = ctx?.runner_up?.name
  const ref = ctx?.reference || {}
  const key = which === 'aces' ? 'aces_per_set' : 'minutes_per_set'
  const unit = which === 'aces' ? 'aces' : 'min'
  const lines = []
  const vs = perSet(ref.champion?.vs_finalist, key)
  const surf = perSet(ref.champion?.on_surface, key)
  const all = perSet(ref.champion?.overall, key)
  const tour = perSet(ref.tour, key)
  if (champ && vs != null) lines.push(`${champ} v ${run}: ${vs} ${unit} per set (${ref.champion.vs_finalist.matches} meeting${ref.champion.vs_finalist.matches === 1 ? '' : 's'})`)
  if (champ && surf != null) lines.push(`${champ} on ${ctx.surface.toLowerCase()}: ${surf} ${unit} per set (${ref.champion.on_surface.matches} matches, 3 seasons)`)
  else if (champ && all != null) lines.push(`${champ}: ${all} ${unit} per set (${ref.champion.overall.matches} matches, 3 seasons)`)
  if (tour != null) lines.push(`${ctx.tour} on ${ctx.surface.toLowerCase()}: ${tour} ${unit} per set`)
  if (!lines.length) lines.push(champ ? `No history held for ${champ} yet` : 'Pick your champion to see their history here')
  return <ul className="fg-ref">{lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
}

/* THE MEETINGS THEMSELVES (owner, 2026-09-19). The reference lines give the
   RATE; this gives the matches behind it — who won, the score, the length and
   the aces each player hit. Sackmann's score is written from the winner's
   side, so naming the winner in front of it makes "6-4 6-3" read the right
   way round. */
function Meetings({ ctx }) {
  const h = ctx?.h2h
  if (!h?.matches?.length) return null
  const a = surname(ctx?.champion?.name)
  const b = surname(ctx?.runner_up?.name)
  return (
    <section className="fg-q">
      <span className="fg-label">
        When they have met{h.total > 1 ? ` — ${a} ${h.champion_wins}, ${b} ${h.opponent_wins}` : ''}
      </span>
      <ul className="fg-meets">
        {h.matches.map((m, i) => (
          <li key={`${m.date}-${i}`}>
            <span className="fg-meet-when">
              {[m.year, m.tournament, m.round, m.surface].filter(Boolean).join(' · ')}
            </span>
            <span className="fg-meet-score">
              {surname(m.winner_name)} {m.score}{m.minutes ? ` · ${fmtLong(m.minutes)}` : ''}
            </span>
            <span className="fg-meet-aces">
              {m.champion_aces != null || m.opponent_aces != null
                ? `${a} ${m.champion_aces ?? '–'} aces · ${b} ${m.opponent_aces ?? '–'}`
                : 'Aces not recorded for this match'}
            </span>
          </li>
        ))}
      </ul>
      {h.total > h.shown && (
        <p className="fg-muted">The {h.shown} most recent of {h.total} meetings</p>
      )}
    </section>
  )
}

export default function FinalGuessModal({ tournamentId, open, onClose, reason }) {
  const qc = useQueryClient()
  const { data: ctx, isLoading } = useFinalGuess(tournamentId, open)
  const [aces, setAces] = useState(null)
  const [minutes, setMinutes] = useState(null)
  const acesMax = Math.max(1, ctx?.ceilings?.aces_max || 0)
  const durMax = Math.max(1, ctx?.ceilings?.duration_max_min || 0)
  const bestOf = ctx?.best_of || 3

  // Seed the sliders once the context arrives: the saved answers, else a
  // sensible middle — the champion's rate times a typical number of sets.
  useEffect(() => {
    if (!ctx) return
    if (ctx.guess) { setAces(ctx.guess.final_aces); setMinutes(ctx.guess.final_duration_min); return }
    // THE SLIDERS OPEN ON THE DEFAULT — what this bracket holds if it never
    // touches them (owner, 2026-09-18): last year's average for this gender,
    // surface and format.
    if (ctx.default) { setAces(ctx.default.aces); setMinutes(ctx.default.minutes); return }
    const ref = ctx.reference || {}
    const r = ref.champion?.vs_finalist || ref.champion?.on_surface || ref.champion?.overall || ref.tour
    const sets = bestOf === 5 ? 4 : 2.5
    setAces(r?.aces_per_set != null ? Math.round(r.aces_per_set * sets) : Math.round(acesMax / 4))
    setMinutes(r?.minutes_per_set != null ? Math.round(r.minutes_per_set * sets) : Math.round(durMax / 3))
  }, [ctx, bestOf, acesMax, durMax])

  const save = useMutation({
    mutationFn: () => putFinalGuess(tournamentId, { final_aces: aces, final_duration_min: minutes }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: finalGuessKey(tournamentId) }); onClose?.() },
  })

  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') onClose?.() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const record = ctx?.ceilings
  const title = useMemo(() => (reason === 'entered' ? 'One more thing: the final' : 'Your tiebreak answers'), [reason])
  if (!open) return null
  return createPortal(
    <div className="profile-modal-backdrop" onClick={onClose}>
      <div className="profile-modal fg-modal" onClick={e => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Tiebreak">
        <div className="profile-edit-form">
          <p className="profile-edit-title">{title}</p>
          {/* The bracket's own answer to "which final?", so the two questions
              below are about a match the reader can see named (owner,
              2026-09-19). */}
          <p className="fg-intro">
            Your current prediction for the final:
            <strong className="fg-final">{finalLine(ctx) || 'No champion picked yet'}</strong>
          </p>
          {/* The tail is the LIVE slider state, not the saved answer, so
              dragging a knob cannot leave a sentence above it saying something
              else (owner's wording, 2026-09-19). */}
          <p className="fg-intro">
            Final score ties broken by the questions below
            {aces != null ? ` — ${aces} aces · ${fmtLong(minutes)}` : ''}
          </p>
          {ctx && !ctx.guess && ctx.default && (
            <p className="fg-intro">
              Leave this alone and you hold {ctx.tour} {ctx.surface.toLowerCase()}'s {ctx.default.year} average:
              {` ${ctx.default.aces} aces, ${fmtLong(ctx.default.minutes)}`}.
            </p>
          )}
          {isLoading || aces == null ? <p className="fg-muted">Loading the history…</p> : (
            <>
              <section className="fg-q">
                <label className="fg-label" htmlFor="fg-aces">How many aces will the champion hit in the final?</label>
                <div className="fg-row">
                  <input id="fg-aces" type="range" min={0} max={acesMax} step={1} value={aces}
                         onChange={e => setAces(Number(e.target.value))} disabled={ctx?.locked} />
                  <output className="fg-value" htmlFor="fg-aces">{aces}</output>
                </div>
                <div className="fg-ends"><span>0 · walkover</span><span>{acesMax} · most ever{record?.aces_record ? ` (${record.aces_record.player}, ${record.aces_record.tournament} ${record.aces_record.year})` : ''}</span></div>
                <Reference ctx={ctx} which="aces" />
              </section>
              <section className="fg-q">
                <label className="fg-label" htmlFor="fg-min">How long will the final last?</label>
                <div className="fg-row">
                  <input id="fg-min" type="range" min={0} max={durMax} step={1} value={minutes}
                         onChange={e => setMinutes(Number(e.target.value))} disabled={ctx?.locked} />
                  <output className="fg-value" htmlFor="fg-min">{fmtMinutes(minutes)}<small>{minutes} min</small></output>
                </div>
                <div className="fg-ends"><span>0 · walkover</span><span>{fmtLong(durMax)} · longest on {ctx.surface.toLowerCase()}{record?.duration_record ? ` (${record.duration_record.tournament} ${record.duration_record.year})` : ''}</span></div>
                <Reference ctx={ctx} which="minutes" />
              </section>
              <Meetings ctx={ctx} />
              {ctx?.actual && (
                <p className="fg-actual">The final: {ctx.actual.final_aces} aces, {fmtLong(ctx.actual.final_duration_min)}.</p>
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
  return (
    <button type="button" className="fg-bar" onClick={onOpen}>
      {/* ONE LINE AND THE ANSWERS (owner, 2026-09-19). The picked final and the
          sentence about ties live in the dialog — "only visible once you click
          in" — so this stays the quiet way in that it was. */}
      <span className="fg-bar-label">Tiebreak</span>
      {g ? <span className="fg-bar-value">{g.final_aces} aces · {fmtMinutes(g.final_duration_min)}</span>
         : ctx.default ? <span className="fg-bar-value fg-bar-value--ask">Holding the average: {ctx.default.aces} aces · {fmtMinutes(ctx.default.minutes)}</span>
         : <span className="fg-bar-value fg-bar-value--ask">{ctx.locked ? 'No answers given' : 'Answer the two questions about the final'}</span>}
      {ctx.actual && <span className="fg-bar-actual">final: {ctx.actual.final_aces} · {fmtMinutes(ctx.actual.final_duration_min)}</span>}
    </button>
  )
}
