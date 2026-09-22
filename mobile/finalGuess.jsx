/* THE TIEBREAK QUESTIONS (owner, 2026-09-18), in the app.
 *
 * Two answers about the singles final — how many aces the champion will
 * hit, and how long it will last — break ties on points once the final is
 * played: closest on aces, then on minutes. Each slider runs from 0 (a
 * walkover) to the most it has ever been on this tour, in this format, on
 * this surface, and beside it sits the most useful figure we hold about
 * the player this bracket has picked to win.
 *
 * The slider is our own: a track, a knob, and a pan that maps the finger's
 * x to a whole number. Nothing in the project's dependencies draws one, and
 * this stays inside the gesture library the draw already uses.
 */
import { useEffect, useMemo, useState } from 'react'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import Animated, { runOnJS, useAnimatedStyle, useSharedValue } from 'react-native-reanimated'
import { getFinalGuess, putFinalGuess } from './api'
import { leading } from './fontScale.js'
import { ScrollPane } from './scrollPane'
import { Sheet } from './sheet'
import { Muted } from './ui'
import { C, R, S, T, TOUR } from './theme'
import { useApi } from './useApi'
import { tiebreakVisible } from './scoring'

export function fmtMinutes(m) {
  if (m == null) return '–'
  const h = Math.floor(m / 60), mm = m % 60
  return h ? `${h}h ${String(mm).padStart(2, '0')}m` : `${mm}m`
}

/* EVERY DURATION IN THE DRAWER CARRIES BOTH FORMS (owner, 2026-09-19): the
   clock reading and the plain minutes. The slider answers in minutes and the
   references read in hours, and leaving the reader to convert between the two
   while comparing them is the one job this dialog should not hand back.
   Under an hour the two forms are the same number, so it is said once. */
export function fmtLong(m) {
  if (m == null) return '–'
  return m >= 60 ? `${fmtMinutes(m)} (${m} min)` : `${m} min`
}

/* THE PICKED FINAL, IN A LINE (owner, 2026-09-19): "Ostapenko def. Birrell".
   Surnames, because that is what identifies a player in a line about two of
   them, and it is the reading the bracket's own boxes use — everything after
   the first token is the surname, so "Díaz Acosta" survives whole
   (bracket.jsx lastNameOf). */
function surname(full) {
  const parts = String(full || '').trim().split(/\s+/)
  return parts.length > 1 ? parts.slice(1).join(' ') : parts[0]
}


const KNOB = 28

/* A draggable whole-number slider. `onChange` fires as the knob moves. */
export function ValueSlider({ value, min = 0, max = 1, onChange, disabled, accessibilityLabel, style }) {
  const [width, setWidth] = useState(0)
  const usable = Math.max(1, width - KNOB)
  const span = Math.max(1, max - min)
  const x = useSharedValue(0)
  useEffect(() => { x.value = ((Math.min(Math.max(value ?? min, min), max) - min) / span) * usable }, [value, min, max, usable, span, x])
  const startX = useSharedValue(0)
  const emit = (px) => {
    const v = Math.round(min + (Math.min(Math.max(px, 0), usable) / usable) * span)
    onChange?.(v)
  }
  const pan = useMemo(() => Gesture.Pan()
    .enabled(!disabled)
    /* HORIZONTAL DRAGS ONLY, now that the sheet around this scrolls. With no
       offset the pan activated on ANY movement, so a finger that came down on
       a knob and pulled down to scroll dragged the value instead of the page.
       activeOffsetX claims the touch only once it has travelled sideways, and
       a vertical pull is left to the ScrollView.
       No failOffsetY, deliberately: once the drag belongs to the slider,
       drifting off-axis must not abandon it half way along the track. */
    .activeOffsetX([-8, 8])
    .onBegin(() => { startX.value = x.value })
    .onUpdate(e => {
      const nx = Math.min(Math.max(startX.value + e.translationX, 0), usable)
      x.value = nx
      runOnJS(emit)(nx)
    }), [disabled, usable, span, min])   // eslint-disable-line react-hooks/exhaustive-deps
  const tap = useMemo(() => Gesture.Tap().enabled(!disabled).onEnd(e => {
    const nx = Math.min(Math.max(e.x - KNOB / 2, 0), usable)
    x.value = nx
    runOnJS(emit)(nx)
  }), [disabled, usable, span, min])     // eslint-disable-line react-hooks/exhaustive-deps
  const knobStyle = useAnimatedStyle(() => ({ transform: [{ translateX: x.value }] }))
  const fillStyle = useAnimatedStyle(() => ({ width: x.value + KNOB / 2 }))
  return (
    <GestureDetector gesture={Gesture.Race(pan, tap)}>
      <View style={[s.track, style]} onLayout={e => setWidth(e.nativeEvent.layout.width)}
            accessible accessibilityRole="adjustable" accessibilityLabel={accessibilityLabel}
            accessibilityValue={{ min, max, now: value ?? min }}>
        <View style={s.rail} />
        <Animated.View style={[s.fill, fillStyle]} />
        <Animated.View style={[s.knob, knobStyle, disabled && s.knobOff]} />
      </View>
    </GestureDetector>
  )
}

/* The three per-question reference builders live beside the wizard below —
   setsRows, acesRows and minutesRows. This table renders whichever it is
   given: a sentence per row with its figure and the sample it was taken over
   on the line beneath. Three numbers are shown so they can be COMPARED, and
   prose bullets made the reader parse each one to do it. */
/* EVERY ROW IS AN AVERAGE, AND EVERY FIGURE CARRIES ITS UNIT (owner,
 * 2026-09-22). The rows read as bare facts — "WTA 500 finals on hard, past 10
 * years … 2.4" — which is a count of finals as easily as an average per final,
 * and 2.4 of nothing in particular. The builders below say WHAT each row is
 * about; the one word they all share is said once, here.
 *
 * `unit` is the word after each figure — sets, aces — and is omitted where the
 * figure already reads as its own unit: "1h 46m" needs no noun after it.
 *
 * THE SET COUNT IS IN THE LABELS, NOT A COLUMN HEAD (owner, 2026-09-22). While
 * the figures sat in a column, "3 sets" over it said the aces and minutes
 * rows were scaled to the set count just chosen. With each figure on its own
 * line under its sentence there is no column for a head to sit over, so every
 * scaled row states the set count itself — which is where the reader is
 * looking anyway.
 */
function StatTable({ rows, unit }) {
  if (!rows.length) return null
  return (
    <View style={s.table}>
      {/* THE BLOCK SAYS WHAT IT IS (owner, 2026-09-22). Under a question and
          its answer sat a run of sentences with numbers, and nothing said they
          were evidence rather than more of the question. The title takes the
          left, where reading starts; the column's note keeps the right it
          already had, so one line carries both. */}
      <Text style={s.tableTitle}>Reference data</Text>
      {/* TWO LINES, NOT THREE COLUMNS (owner, 2026-09-22). The description is
          the longest thing here and it was sharing a row with a number column
          and a sample column, so it wrapped to two lines on every row while
          two thirds of the width sat empty beside it. Given the full width it
          reads on one line, and the figure and its sample go underneath —
          which is also their real relationship: they are both about the
          sentence above them.

          "OVER 82 finals": the count is the SAMPLE the average was taken
          over, and a bare "82 finals" reads as a fact about the final rather
          than about the figure. Said here, once, for the same reason "Average
          for" is — the builders supply the count and the noun and no
          preposition of their own. */}
      {rows.map((r, i) => (
        <View key={r.label} style={[s.tr, i > 0 && s.trRule]}>
          {/* "Avg", not "Average" (owner, 2026-09-22): the word is on every
              row and the description after it is the part that differs. The
              colon is what makes the figure below read as this sentence's
              answer rather than as the next line. */}
          <Text style={s.tdLabel} numberOfLines={2}>Avg for {r.label}:</Text>
          <View style={s.trFigures}>
            <Text style={s.tdValue}>
              {r.value}{unit ? <Text style={s.tdUnit}> {unit}</Text> : null}
            </Text>
            {/* BRACKETED AND SET FURTHER OFF (owner, 2026-09-22): the sample
                is an aside about the figure, not a second figure, and at a
                small gap the two read as one phrase. */}
            {r.note ? (
              <Text style={s.tdNote} numberOfLines={1}>(Over {r.note})</Text>
            ) : null}
          </View>
        </View>
      ))}
    </View>
  )
}

/* THE ANSWER, ON A PLATE. The one bold object in the drawer: a recess in the
   scoreboard face, at the top right of its question where the eye lands after
   reading it. Everything else here is hairlines and quiet type — this is the
   number the reader is actually setting, and it should be unmistakable. */
function Plate({ value, sub }) {
  return (
    <View style={s.plate}>
      <Text style={s.plateValue} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.5}>{value}</Text>
      {sub ? <Text style={s.plateSub} numberOfLines={1}>{sub}</Text> : null}
    </View>
  )
}

/* ONE QUESTION PER PAGE (owner, 2026-09-19). Four pages: what the questions
   decide, then sets, then aces, then the duration, with Next between them.
   The pages are deliberately not a scrolling list of three — each question
   carries its own reference figures, and three questions' worth of evidence on
   one page is the wall of numbers this replaced. */
const PAGES = ['intro', 'sets', 'aces', 'minutes']

/* How many sets a final of this format can go. A best-of-three cannot be four,
   and offering the choice would be nonsense. */
const setChoices = (bestOf) => (bestOf === 5 ? [3, 4, 5] : [2, 3])

/* A ROW OF CHOICES, not a slider. Two or three whole numbers is a question
   with a handful of answers, and a track with two stops is a worse control
   than two buttons. */
function SetPicker({ value, options, onChange, disabled }) {
  return (
    <View style={s.setRow}>
      {options.map(n => {
        const on = value === n
        return (
          <Pressable key={n} onPress={() => !disabled && onChange(n)}
                     accessibilityRole="button"
                     accessibilityState={{ selected: on, disabled: !!disabled }}
                     accessibilityLabel={`${n} sets`}
                     style={({ pressed }) => [s.setBtn, on && s.setBtnOn,
                                              pressed && !disabled && { opacity: 0.7 }]}>
            <Text style={[s.setBtnN, on && s.setBtnNOn]}>{n}</Text>
            <Text style={[s.setBtnLabel, on && s.setBtnLabelOn]}>sets</Text>
          </Pressable>
        )
      })}
    </View>
  )
}

/* ── The reference rows, per question ─────────────────────────────────────
   Every label names the real conditions of THIS draw — its tour, its tier,
   its surface, the two players picked — because a WTA 250 on clay answered
   with ATP hard numbers is worse than no figure at all. Every window is
   stated: rules change and the reader deserves to know how current a number
   is (owner, 2026-09-19).

   `sets` scales the per-set figures into a whole-match one, which is why the
   sets question comes first: these rows change as soon as it is answered. */
const round1 = (n) => (n == null ? null : Math.round(n * 10) / 10)

function setsRows(data) {
  const tier = data?.sets_question?.tier_finals
  const h = data?.sets_question?.h2h
  const a = surname(data?.champion?.name), b = surname(data?.runner_up?.name)
  const where = tier?.surface_scoped === false ? 'all surfaces' : (data?.surface || '').toLowerCase()
  const rows = []
  if (tier?.sets_per_match != null) {
    rows.push({ label: `recent ${data.tier_label} finals on ${where}`,
                value: String(tier.sets_per_match), note: `${tier.matches} finals` })
  }
  const met = (n) => `${n} H2H ${n === 1 ? 'match' : 'matches'}`
  if (h?.on_surface) {
    rows.push({ label: `${a} v ${b} on ${(data.surface || '').toLowerCase()}`,
                value: String(h.on_surface.sets_per_match), note: met(h.on_surface.matches) })
  }
  // Only worth a row when there are meetings the surface row does not cover.
  if (h?.overall && h.off_surface > 0) {
    rows.push({ label: `${a} v ${b}, all surfaces`,
                value: String(h.overall.sets_per_match), note: met(h.overall.matches) })
  }
  return rows
}

function acesRows(data, sets) {
  const q = data?.aces_question || {}
  const a = surname(data?.champion?.name), b = surname(data?.runner_up?.name)
  const surf = (data?.surface || '').toLowerCase()
  const where = q.tier_finals?.surface_scoped === false ? 'all surfaces' : surf
  const rows = []
  const scale = (r) => (r?.aces_per_set == null ? null : round1(r.aces_per_set * sets))
  if (q.tier_finals?.aces_per_set != null) {
    rows.push({ label: `recent ${sets}-set ${data.tier_label} finals on ${where}`,
                value: String(scale(q.tier_finals)), note: `${q.tier_finals.matches} finals` })
  }
  if (q.champion_vs?.aces_per_set != null) {
    rows.push({ label: `${sets}-set ${a} v ${b} matches on ${surf}`, value: String(scale(q.champion_vs)),
                note: `${q.champion_vs.matches} ${q.champion_vs.matches === 1 ? 'match' : 'matches'}` })
  }
  if (q.champion_on_surface?.aces_per_set != null) {
    rows.push({ label: `${sets}-set ${a} matches on ${surf}`, value: String(scale(q.champion_on_surface)),
                note: `${q.champion_on_surface.matches} matches` })
  }
  return rows
}

function minutesRows(data, sets) {
  const q = data?.minutes_question || {}
  const a = surname(data?.champion?.name), b = surname(data?.runner_up?.name)
  const surf = (data?.surface || '').toLowerCase()
  const where = q.tier_finals?.surface_scoped === false ? 'all surfaces' : surf
  const key = String(sets)
  const rows = []
  /* EVERY DURATION COMES PRE-COMPUTED PER SET COUNT, and the client
     deliberately does no arithmetic of its own: a per-set duration is PLAYING
     time with the changeovers stripped out, and putting the right number of
     them back for the reader's predicted length is the server's job. Doing it
     here with a multiply would count the history's breaks instead of this
     prediction's (owner's correction, 2026-09-19). */
  const tierMins = q.tier_minutes_by_sets?.[key]
  if (tierMins != null) {
    rows.push({ label: `recent ${sets}-set ${data.tier_label} finals on ${where}`,
                value: fmtMinutes(tierMins), note: `${q.tier_finals?.matches ?? ''} finals`.trim() })
  }
  const champMins = q.champion_on_surface?.by_sets?.[key]
  if (champMins != null) {
    rows.push({ label: `recent ${sets}-set ${a} matches on ${surf}`,
                value: fmtMinutes(champMins),
                note: `${q.champion_on_surface.matches} matches` })
  }
  const est = q.h2h_estimate?.by_sets?.[key]
  if (est != null) {
    rows.push({ label: `${sets}-set ${a} v ${b} matches on ${surf}, estimated`, value: fmtMinutes(est),
                note: `${q.h2h_estimate.matches} H2H ${q.h2h_estimate.matches === 1 ? 'match' : 'matches'}` })
  }
  return rows
}

export function FinalGuessSheet({ tournamentId, visible, onClose, onSaved }) {
  const ctx = useApi(visible ? `final-guess:${tournamentId}` : null, () => getFinalGuess(tournamentId), { enabled: !!visible })
  const data = ctx.data
  const [step, setStep] = useState(0)
  const [sets, setSets] = useState(null)
  const [aces, setAces] = useState(null)
  const [minutes, setMinutes] = useState(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const acesMax = Math.max(1, data?.ceilings?.aces_max || 0)
  const durMax = Math.max(1, data?.ceilings?.duration_max_min || 0)
  const options = setChoices(data?.best_of || 3)

  /* THE ANSWERS OPEN ON THE DEFAULT — what this bracket is taken to have said
     if it never touches them (owner, 2026-09-18): last year's average for
     this gender, surface and format. So the wizard opens on an answer the
     reader already holds, and the references are there to help them beat it. */
  useEffect(() => {
    if (!data) return
    const g = data.guess
    const d = data.default
    const firstSet = options[0]
    const fallbackSets = Math.min(Math.max(
      Math.round(data.sets_question?.tier_finals?.sets_per_match ?? firstSet), options[0]),
      options[options.length - 1])
    setSets(g?.final_sets ?? d?.sets ?? fallbackSets)
    if (g) { setAces(g.final_aces); setMinutes(g.final_duration_min); return }
    if (d) { setAces(d.aces); setMinutes(d.minutes); return }
    setAces(Math.round(acesMax / 4))
    setMinutes(Math.round(durMax / 3))
  }, [data, acesMax, durMax])     // eslint-disable-line react-hooks/exhaustive-deps

  // A fresh open starts at the beginning rather than wherever it was left.
  useEffect(() => { if (visible) { setStep(0); setError(null) } }, [visible])

  const save = async () => {
    setSaving(true); setError(null)
    try {
      await putFinalGuess(tournamentId, {
        final_sets: sets, final_aces: aces, final_duration_min: minutes,
      })
      onSaved?.(); onClose?.()
    } catch (e) {
      setError(e?.message || 'Could not save')
    } finally { setSaving(false) }
  }

  const rec = data?.ceilings
  const tint = data?.tour === 'WTA' ? TOUR.F : TOUR.M
  const champ = surname(data?.champion?.name)
  const run = surname(data?.runner_up?.name)
  const locked = !!data?.locked
  const page = PAGES[step]
  const last = step === PAGES.length - 1

  /* ONE NAME THROUGH THE FLOW: the card on the draw page and the drawer it
     opens carry the same words. "Tiebreak" alone was too ambiguous about what
     it breaks a tie IN (owner, 2026-09-19) — it is the league standings, not
     a tiebreak in the tennis sense, which on a draw page is the more obvious
     reading of the word. */
  return (
    <Sheet visible={visible} onClose={onClose} title="Standings Tiebreak Questions">
      {!data || sets == null || aces == null ? <Muted>Loading the history…</Muted> : (
        /* A PANE WITH A BAR ON IT, not a bare ScrollView (owner, 2026-09-22):
           Back and Next sit under the reference block, and on a long question
           they fall past the fold with nothing on screen to say so. */
        <ScrollPane contentContainerStyle={s.body}>
          {page === 'intro' ? (
            <>
              <Text style={s.intro}>
                Ties occurring in the final standings of all leagues will be decided
                by the questions which follow.
              </Text>
              <View style={s.hero}>
                {/* WHAT THE PAIR IS FOR, not just what it is (owner,
                    2026-09-22). "Your current prediction for the final" named
                    the pair and left the reader to work out why a tiebreak
                    sheet was showing it. */}
                <Text style={s.heroLabel}>
                  Reference data will be provided to you based on your predicted champion (and finalist):
                </Text>
                {champ ? (
                  <View style={s.heroNames}>
                    <Text style={[s.champ, { color: tint.text }]} numberOfLines={1}
                          adjustsFontSizeToFit minimumFontScale={0.6}>{champ}</Text>
                    {run ? <Text style={s.def}>def.</Text> : null}
                    {run ? (
                      <Text style={[s.runner, { color: tint.muted }]} numberOfLines={1}
                            adjustsFontSizeToFit minimumFontScale={0.6}>{run}</Text>
                    ) : null}
                  </View>
                ) : (
                  <Text style={s.heroEmpty}>Pick a champion in the draw and this fills in</Text>
                )}
                <Text style={s.heroWhere}>
                  {[data.tier_label, (data.surface || '').toLowerCase(),
                    data.best_of === 5 ? 'best of five' : 'best of three'].filter(Boolean).join(' · ')}
                </Text>
              </View>
            </>
          ) : null}

          {page === 'sets' ? (
            <View style={s.q}>
              <Step n={1} of={3} />
              <Text style={s.qTitle}>How many sets will the final be?</Text>
              <SetPicker value={sets} options={options} onChange={setSets} disabled={locked} />
              <StatTable rows={setsRows(data)} unit="sets" />
            </View>
          ) : null}

          {page === 'aces' ? (
            <View style={s.q}>
              <Step n={2} of={3} />
              <View style={s.qHead}>
                <Text style={s.qTitle}>How many aces will the champion hit in the final?</Text>
                <Plate value={String(aces)} />
              </View>
              {/* No floor label and no "the most in 12 months" — see Scale. */}
              <Scale value={aces} max={acesMax} onChange={setAces} disabled={locked}
                     label="Aces in the final" rec={rec?.aces_record} />
              {/* Scaled to the sets just chosen, which is why that question
                  comes first (owner, 2026-09-19). */}
              <StatTable rows={acesRows(data, sets)} unit="aces" />
            </View>
          ) : null}

          {page === 'minutes' ? (
            <View style={s.q}>
              <Step n={3} of={3} />
              <View style={s.qHead}>
                <Text style={s.qTitle}>What will be the match duration of the final?</Text>
                <Plate value={fmtMinutes(minutes)} sub={`${minutes} min`} />
              </View>
              {/* The clock reading alone: the raw minutes under it were a
                  third line on an end that is already two (owner, 2026-09-22). */}
              <Scale value={minutes} max={durMax} maxLabel={fmtMinutes(durMax)} onChange={setMinutes}
                     disabled={locked} label="Length of the final"
                     what="12 month max" zero="a walkover" />
              {/* No unit: fmtMinutes already reads as one ("1h 46m"). */}
              <StatTable rows={minutesRows(data, sets)} />
              {!data.guess && data.default ? (
                <Text style={s.default}>
                  {`Leave these alone and you hold ${data.tour} ${(data.surface || '').toLowerCase()}’s ${data.default.year} average: `}
                  <Text style={s.defaultStrong}>
                    {`${data.default.sets ?? options[0]} sets, ${data.default.aces} aces, ${fmtLong(data.default.minutes)}`}
                  </Text>
                </Text>
              ) : null}
              {data.actual ? (
                <Text style={s.actual}>
                  {`The final: ${data.actual.final_sets ?? '–'} sets, ${data.actual.final_aces} aces, ${fmtLong(data.actual.final_duration_min)}.`}
                </Text>
              ) : null}
            </View>
          ) : null}

          {error ? <Text style={s.error}>{error}</Text> : null}
          <View style={s.actions}>
            {step > 0 ? (
              <Pressable onPress={() => setStep(n => n - 1)} style={[s.btn, s.btnQuiet]}
                         accessibilityRole="button">
                <Text style={s.btnQuietText}>Back</Text>
              </Pressable>
            ) : (
              <Pressable onPress={onClose} style={[s.btn, s.btnQuiet]} accessibilityRole="button">
                <Text style={s.btnQuietText}>{locked ? 'Close' : 'Later'}</Text>
              </Pressable>
            )}
            {last ? (
              locked ? null : (
                <Pressable onPress={save} disabled={saving} style={[s.btn, saving && { opacity: 0.6 }]}
                           accessibilityRole="button">
                  <Text style={s.btnText}>{saving ? 'Saving…' : 'Save answers'}</Text>
                </Pressable>
              )
            ) : (
              <Pressable onPress={() => setStep(n => n + 1)} style={s.btn} accessibilityRole="button">
                <Text style={s.btnText}>Next</Text>
              </Pressable>
            )}
          </View>
        </ScrollPane>
      )}
    </Sheet>
  )
}

/* Where the reader is, in three. Small: it orients rather than instructs. */
function Step({ n, of }) {
  return <Text style={s.step}>{`Question ${n} of ${of}`}</Text>
}

/* THE SLIDER AND ITS TWO ENDS, and what each of them means.
 *
 * `zero` EXPLAINS THE FLOOR ONLY WHERE IT NEEDS EXPLAINING. A final of zero
 * MINUTES is a walkover, and saying so is the only way that end of the scale
 * makes sense. Zero ACES is an ordinary afternoon — "women will often hit 0
 * aces over a full match" (owner, 2026-09-22) — so calling it a walkover was
 * wrong, and no label is the right amount to say about a number that speaks
 * for itself.
 *
 * `what` names what the TOP of the scale is. The two questions want opposite
 * halves of it: the aces end passes only a `rec`, because the holder is the
 * part a reader gets something from and the phrase in front of it repeated
 * what the clay-coloured number already implies; the minutes end passes only
 * a `what`, and that is now the three words "12 month max" — "3h 33m — the
 * longest in 12 months — Ningbo 2025" ran to three lines to say what its own
 * number says (owner, 2026-09-22).
 */
/* THE ENDS SIT ON THE TRACK'S OWN ROW (owner, 2026-09-22). Under it they were
 * two numbers floating in a band of their own, and the reader had to carry
 * them back up to the line they belong to. Flanking the track they are where
 * it starts and where it ends, which is what they mean. What the ends SAY —
 * the floor's meaning, the record holder — stays on the line beneath, under
 * the number it is about. */
function Scale({ value, max, maxLabel, onChange, disabled, label, rec, what, zero }) {
  const holder = rec
    ? `${rec.player ? `${surname(rec.player)}, ` : ''}${rec.tournament} ${rec.year}`
    : null
  const who = [what, holder].filter(Boolean).join(' — ')
  return (
    <View style={s.scale}>
      <View style={s.scaleRow}>
        <Text style={s.endValue}>0</Text>
        <ValueSlider style={s.scaleTrack} value={value} min={0} max={max} onChange={onChange}
                     disabled={disabled} accessibilityLabel={label} />
        <Text style={[s.endValue, s.endRecord]}>{maxLabel ?? max}</Text>
      </View>
      {zero || who ? (
        <View style={s.ends}>
          {zero ? <Text style={s.endWho}>{zero}</Text> : null}
          {who ? (
            <View style={s.endRight}>
              <Text style={[s.endWho, s.endWhoRight]} numberOfLines={2}>{who}</Text>
            </View>
          ) : null}
        </View>
      ) : null}
    </View>
  )
}

/* THE WAY IN, ALWAYS ON SCREEN (owner, 2026-09-22): "move the button to
 * access the tiebreaker data to be a bar above the round selector, always
 * visible in the draw view. Just like the PWA."
 *
 * It was a Card rendered INSIDE the bracket, after the final-round match — so
 * reaching the tiebreak questions meant scrolling to the end of the draw, and
 * on a 32 bracket that is four rounds away from where anyone is picking. The
 * web has had it as a bar under the header all along; this is the same object,
 * in the same place relative to the round strip.
 *
 * RED WHEN THE ANSWERS NO LONGER DESCRIBE THE PICKED FINAL. `stale` is the
 * server's answer, comparing the final these answers were saved for against
 * the one the bracket now predicts (models/final_guess.answers_are_stale) —
 * not a timestamp, and not "have you opened it", because opening changes
 * nothing about answers that are for the wrong two players. Saving clears it.
 *
 * Border and label only, never a red fill: this sits above the round strip on
 * every visit, and a solid red bar across the draw reads as a broken screen
 * rather than as one thing needing a look.
 */
export function FinalGuessBar({ tournamentId, enabled, onOpen, refreshKey }) {
  const ctx = useApi(enabled ? `final-guess:${tournamentId}:bar:${refreshKey || 0}` : null,
                     () => getFinalGuess(tournamentId), { enabled: !!enabled })
  const data = ctx.data
  // Hidden until the draw is open for picks, or this bracket has answered
  // (owner, 2026-09-18) — scoring.tiebreakVisible.
  if (!enabled || !tiebreakVisible(data)) return null
  const g = data.guess
  const stale = !!data.stale
  const answers = g
    ? [g.final_sets ? `${g.final_sets} sets` : null,
       `${g.final_aces} aces`, fmtMinutes(g.final_duration_min)].filter(Boolean).join(' · ')
    : data.default
      ? `Holding the average: ${[data.default.sets ? `${data.default.sets} sets` : null,
           `${data.default.aces} aces`, fmtMinutes(data.default.minutes)].filter(Boolean).join(' · ')}`
      : (data.locked ? 'No answers given' : 'Answer the three questions about the final')
  return (
    <Pressable onPress={onOpen} accessibilityRole="button"
               style={({ pressed }) => [s.bar, stale && s.barStale, pressed && s.barDown]}
               accessibilityLabel={
                 'Standings tiebreak questions: your answers about the final'
                 + (stale ? ' — given for a different final' : '')}>
      {stale ? (
        <View style={s.staleTag}><Text style={s.staleTagText}>!</Text></View>
      ) : null}
      <View style={s.barText}>
        <Text style={[s.barLabel, stale && s.barLabelStale]} numberOfLines={1}>
          STANDINGS TIEBREAK QUESTIONS
        </Text>
        <Text style={s.barValue} numberOfLines={1}>{answers}</Text>
      </View>
      {data.actual ? (
        <Text style={s.barActual} numberOfLines={1}>
          final: {data.actual.final_aces} · {fmtMinutes(data.actual.final_duration_min)}
        </Text>
      ) : null}
    </Pressable>
  )
}


const s = StyleSheet.create({
  /* Edge to edge under the header, like the strip below it. */
  bar: {
    flexDirection: 'row', alignItems: 'center', gap: S.sm,
    marginHorizontal: -S.lg, paddingHorizontal: S.lg, paddingVertical: 6,
    borderTopWidth: 1, borderBottomWidth: 1, borderColor: C.border,
    backgroundColor: C.card,
  },
  barDown: { backgroundColor: C.raised },
  barStale: { borderColor: C.bad },
  barText: { flex: 1, minWidth: 0 },
  barLabel: { ...T.tiny, color: C.muted, letterSpacing: 0.6 },
  barLabelStale: { color: C.bad },
  barValue: { ...T.smallMed, color: C.ink },
  barActual: { ...T.tiny, color: C.faint, flexShrink: 0 },
  /* A GLYPH, not an icon: it survives whatever the icon font does, and the
     circle is drawn by the view rather than by the character. */
  staleTag: {
    width: leading(17), height: leading(17), borderRadius: leading(17) / 2,
    backgroundColor: C.bad, alignItems: 'center', justifyContent: 'center', flexShrink: 0,
  },
  staleTagText: { fontFamily: 'Archivo_700Bold', fontSize: 11, color: C.bg },

  track: { height: 36, justifyContent: 'center' },
  rail: { position: 'absolute', left: KNOB / 2, right: KNOB / 2, height: 4, borderRadius: 2, backgroundColor: C.border },
  fill: { position: 'absolute', left: KNOB / 2, height: 4, borderRadius: 2, backgroundColor: C.greenLit },
  knob: { position: 'absolute', left: 0, width: KNOB, height: KNOB, borderRadius: KNOB / 2, backgroundColor: C.greenLit, borderWidth: 2, borderColor: C.bg },
  knobOff: { backgroundColor: C.muted },

  /* The drawer's rhythm. Sections are separated by SPACE and one hairline —
     not by cards — so the two questions read as two of a kind. */
  body: { gap: S.lg, paddingBottom: S.md },

  /* ── The match ─────────────────────────────────────────────────────────── */
  hero: { gap: 2 },
  heroLabel: { ...T.small, color: C.faint },
  /* Baseline-aligned rather than centred: three words of different sizes on
     one line, reading as a result. */
  heroNames: { flexDirection: 'row', alignItems: 'baseline', gap: S.sm },
  champ: { ...T.h1, flexShrink: 1 },
  def: { ...T.tiny, color: C.faint },
  runner: { ...T.h2, flexShrink: 1 },
  heroEmpty: { ...T.bodyMed, color: C.muted },
  /* The one line of explanation in the drawer, directly under its title. */
  intro: { ...T.small, color: C.inkBody },

  step: { ...T.tiny, color: C.faint },
  /* A row of whole-number choices, sized as controls rather than as chips:
     two or three answers deserve a target, not a track. */
  setRow: { flexDirection: 'row', gap: S.sm },
  setBtn: {
    flex: 1, alignItems: 'center', paddingVertical: S.sm,
    borderRadius: R.sm, borderWidth: 1, borderColor: C.border, backgroundColor: C.sunken,
  },
  setBtnOn: { borderColor: C.greenLit, backgroundColor: C.greenDeep },
  setBtnN: { ...T.h1, color: C.muted },
  setBtnNOn: { color: C.greenBright },
  setBtnLabel: { ...T.tiny, color: C.faint, marginTop: -4 },
  setBtnLabelOn: { color: C.greenLit },
  heroWhere: { ...T.tiny, color: C.faint, marginTop: 2 },

  /* ── A question ────────────────────────────────────────────────────────── */
  q: { gap: S.sm },
  qHead: { flexDirection: 'row', alignItems: 'center', gap: S.md },
  qTitle: { ...T.h2, color: C.ink, flex: 1 },

  /* THE ONE BOLD OBJECT: a recess in the scoreboard face. The only rounded
     thing in the drawer, so nothing competes with it. */
  plate: {
    minWidth: 92, alignItems: 'center', justifyContent: 'center',
    paddingHorizontal: S.sm, paddingVertical: 6,
    backgroundColor: C.sunken, borderRadius: R.sm,
    borderWidth: 1, borderColor: C.borderOn,
  },
  plateValue: { ...T.display, color: C.greenBright, lineHeight: leading(32) },
  plateSub: { ...T.tiny, color: C.faint, marginTop: -2 },

  /* The slider's two ends. The left is a floor nobody aims at; the right is a
     record, which is the one number here worth a name under it. */
  scale: { gap: 2 },
  scaleRow: { flexDirection: 'row', alignItems: 'center', gap: S.sm },
  scaleTrack: { flex: 1 },
  /* The captions keep to the ends they belong to: the right one is pushed
     over rather than spaced apart, so it stays right when it is alone. */
  ends: { flexDirection: 'row', gap: S.md },
  /* THE RIGHT END KEEPS TO ITS OWN HALF (owner, 2026-09-22: wrap it "so that
     it does not go too far to the left"). Two lines of a record holder ran
     back across the slider and read as a sentence about the left end as much
     as the right. 55% leaves the 0 its room and still fits "Tauson, Indian
     Wells 2026" in the two lines the Text allows. */
  endRight: { flexShrink: 1, alignItems: 'flex-end', maxWidth: '55%', marginLeft: 'auto' },
  // Right-aligned only on the right end; the left keeps the default.

  endValue: { ...T.smallMed, color: C.muted, fontVariant: ['tabular-nums'] },
  endRecord: { color: C.clay },
  endWho: { ...T.tiny, color: C.faint },
  endWhoRight: { textAlign: 'right' },

  /* ── The evidence, as a table ──────────────────────────────────────────── */
  table: { marginTop: S.xs },
  tableTitle: { ...T.smallMed, color: C.muted, marginTop: S.xs, marginBottom: 3 },
  /* A ROW IS TWO LINES NOW: the description across the full width, then the
     figure and the sample it was taken over. */
  tr: { gap: 1, paddingVertical: 5 },
  trRule: { borderTopWidth: 1, borderTopColor: C.border },
  // Baseline-aligned, so the small sample sits on the figure's own line
  // rather than floating at the middle of its height.
  // THE ANSWER SITS UNDER ITS QUESTION (owner, 2026-09-22): the indent is
  // what makes the figure belong to the sentence above rather than start a
  // new one.
  trFigures: { flexDirection: 'row', alignItems: 'baseline', gap: S.lg,
               paddingLeft: S.md },
  tdLabel: { ...T.small, color: C.inkBody },
  // Room for '1h 44m' without squeezing the label beside it.
  /* The numeric spine: one width, right-aligned, tabular figures. Three
     numbers in a column can be compared without being read. */
  // The unit rides with the figure and stays quieter than it: the number is
  // what the eye is comparing down the column, the noun only says of what.
  tdUnit: { ...T.tiny, color: C.muted, fontVariant: [] },
  // No fixed width and no right alignment any more: the figures lead their
  // own line, so they line up down the left edge on their own.
  tdValue: { ...T.score, color: C.ink, fontVariant: ['tabular-nums'] },
  tdNote: { ...T.tiny, color: C.faint, flexShrink: 1 },

  /* ── A section heading: title, rule, and a number on the end ───────────── */

  /* ── One meeting ───────────────────────────────────────────────────────── */
  /* W or L from the CHAMPION's side, in the bracket's own pick colours. */
  /* Which number belongs to whom, said once at the bottom rather than on
     every row. */

  /* ── The tail ──────────────────────────────────────────────────────────── */
  default: { ...T.small, color: C.muted },
  defaultStrong: { ...T.smallMed, color: C.inkBody },
  actual: { ...T.bodyMed, color: C.ink },
  error: { ...T.small, color: C.lossMark },
  actions: { flexDirection: 'row', justifyContent: 'flex-end', gap: S.sm, marginTop: S.xs },
  btn: { backgroundColor: C.green, borderRadius: R.sm, paddingHorizontal: 14, paddingVertical: 10 },
  btnText: { ...T.bodyMed, color: '#fff' },
  btnQuiet: { backgroundColor: 'transparent', borderWidth: 1, borderColor: C.border },
  btnQuietText: { ...T.bodyMed, color: C.ink },

  /* ── The card on the draw page (outside the drawer) ────────────────────── */
})
