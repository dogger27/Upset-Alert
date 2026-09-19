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
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import Animated, { runOnJS, useAnimatedStyle, useSharedValue } from 'react-native-reanimated'
import { getFinalGuess, putFinalGuess } from './api'
import { leading } from './fontScale.js'
import { Sheet } from './sheet'
import { Card, Muted, Title } from './ui'
import { C, PICK, R, S, T, TOUR } from './theme'
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
export function ValueSlider({ value, min = 0, max = 1, onChange, disabled, accessibilityLabel }) {
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
      <View style={s.track} onLayout={e => setWidth(e.nativeEvent.layout.width)}
            accessible accessibilityRole="adjustable" accessibilityLabel={accessibilityLabel}
            accessibilityValue={{ min, max, now: value ?? min }}>
        <View style={s.rail} />
        <Animated.View style={[s.fill, fillStyle]} />
        <Animated.View style={[s.knob, knobStyle, disabled && s.knobOff]} />
      </View>
    </GestureDetector>
  )
}

const perSet = (r, key) => (r && r[key] != null ? r[key] : null)

/* THE REFERENCES AS A TABLE, NOT SENTENCES.
   Three numbers exist to be COMPARED — that is the whole reason three are
   shown — and as prose bullets ("Ostapenko on hard: 1.66 aces per set (70
   matches)") the reader had to parse each one to do it. One label column, one
   right-aligned numeric column with the unit stated once in its head, and the
   sample size trailing faint: the eye runs down the numbers.
   Widest evidence first, narrowest last — against this opponent, then on this
   surface, then the tour at large — so the most specific figure is the one the
   reader meets first. */
function refRows(data, which) {
  const ref = data?.reference || {}
  const key = which === 'aces' ? 'aces_per_set' : 'minutes_per_set'
  const champ = surname(data?.champion?.name)
  const run = surname(data?.runner_up?.name)
  const surf = (data?.surface || '').toLowerCase()
  const rows = []
  const add = (label, r, note) => {
    const v = perSet(r, key)
    if (v != null) rows.push({ label, value: String(v), note })
  }
  const vs = ref.champion?.vs_finalist
  if (run) add(`v ${run}`, vs, vs ? `${vs.matches} ${vs.matches === 1 ? 'meeting' : 'meetings'}` : null)
  const surface = ref.champion?.on_surface
  if (surface) add(`${champ} on ${surf}`, surface, `${surface.matches} matches`)
  else if (ref.champion?.overall) add(champ, ref.champion.overall, `${ref.champion.overall.matches} matches`)
  add(`${data?.tour} on ${surf}`, ref.tour, 'all players')
  return rows
}

function StatTable({ rows, unit }) {
  if (!rows.length) return null
  return (
    <View style={s.table}>
      <View style={s.tableHead}>
        <View style={{ flex: 1 }} />
        <Text style={s.tableUnit}>{unit}</Text>
        <View style={s.sampleCol} />
      </View>
      {rows.map((r, i) => (
        <View key={r.label} style={[s.tr, i > 0 && s.trRule]}>
          <Text style={s.tdLabel} numberOfLines={1}>{r.label}</Text>
          <Text style={s.tdValue}>{r.value}</Text>
          <Text style={s.tdNote} numberOfLines={1}>{r.note || ''}</Text>
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

/* THE MEETINGS, AS A RESULTS STRIP (owner, 2026-09-19).
   The question a reader has about a head-to-head is "did my pick beat this
   person?", so each meeting leads with a W or an L from the CHAMPION's point
   of view — in the bracket's own pick colours, which already mean "your pick
   came off" everywhere else in this app.
   Sackmann's score is written from the winner's side, so the score is printed
   winner-first and the W/L chip says whose side that is. The aces pair is
   champion-first to match the chip. */
function Meetings({ data }) {
  const h = data?.h2h
  if (!h?.matches?.length) return null
  const a = surname(data?.champion?.name)
  return (
    <View style={s.section}>
      <View style={s.sectionHead}>
        <Text style={s.sectionTitle}>When they have met</Text>
        <View style={s.sectionRule} />
        <Text style={s.record}>{h.champion_wins}–{h.opponent_wins}</Text>
      </View>
      {h.matches.map((m, i) => (
        <View key={`${m.date}-${i}`} style={s.meet}>
          <View style={[s.wl, m.champion_won ? s.wlWon : s.wlLost]}>
            <Text style={[s.wlText, { color: m.champion_won ? PICK.correct.border : PICK.wrong.border }]}>
              {m.champion_won ? 'W' : 'L'}
            </Text>
          </View>
          <View style={s.meetBody}>
            <Text style={s.meetWhen} numberOfLines={1}>
              <Text style={s.meetYear}>{m.year}</Text>
              {`  ${[m.tournament, m.round].filter(Boolean).join('  ')}`}
              {m.surface ? `  ${m.surface.toLowerCase()}` : ''}
            </Text>
            <Text style={s.meetScore} numberOfLines={1}>
              {m.score}
              {m.minutes ? <Text style={s.meetTime}>{`   ${fmtLong(m.minutes)}`}</Text> : null}
            </Text>
          </View>
          <View style={s.meetAces}>
            <Text style={s.meetAcesN}>
              {m.champion_aces ?? '–'}<Text style={s.meetAcesDash}> – </Text>{m.opponent_aces ?? '–'}
            </Text>
            <Text style={s.meetAcesLabel}>aces</Text>
          </View>
        </View>
      ))}
      {h.total > h.shown ? (
        <Text style={s.more}>{`The ${h.shown} most recent of ${h.total}`}</Text>
      ) : null}
      {/* One short line, because the chip and the champion-first ace pair are
          nearly self-evident — this only has to name whose side they are. */}
      <Text style={s.meetKey} numberOfLines={1}>{`Read from ${a}’s side`}</Text>
    </View>
  )
}

export function FinalGuessSheet({ tournamentId, visible, onClose, onSaved }) {
  const ctx = useApi(visible ? `final-guess:${tournamentId}` : null, () => getFinalGuess(tournamentId), { enabled: !!visible })
  const data = ctx.data
  const [aces, setAces] = useState(null)
  const [minutes, setMinutes] = useState(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const acesMax = Math.max(1, data?.ceilings?.aces_max || 0)
  const durMax = Math.max(1, data?.ceilings?.duration_max_min || 0)
  /* THE SLIDERS OPEN ON THE DEFAULT — what this bracket is taken to have
     said if it never touches them (owner, 2026-09-18): last year's average
     for this gender, on this surface, in this format. So the dialog opens on
     the answer you already have, and the references beside each slider are
     there to help you beat it. */
  useEffect(() => {
    if (!data) return
    if (data.guess) { setAces(data.guess.final_aces); setMinutes(data.guess.final_duration_min); return }
    const d = data.default
    if (d) { setAces(d.aces); setMinutes(d.minutes); return }
    const ref = data.reference || {}
    const r = ref.champion?.vs_finalist || ref.champion?.on_surface || ref.champion?.overall || ref.tour
    const sets = data.best_of === 5 ? 4 : 2.5
    setAces(r?.aces_per_set != null ? Math.round(r.aces_per_set * sets) : Math.round(acesMax / 4))
    setMinutes(r?.minutes_per_set != null ? Math.round(r.minutes_per_set * sets) : Math.round(durMax / 3))
  }, [data, acesMax, durMax])

  const save = async () => {
    setSaving(true); setError(null)
    try {
      await putFinalGuess(tournamentId, { final_aces: aces, final_duration_min: minutes })
      onSaved?.(); onClose?.()
    } catch (e) {
      setError(e?.message || 'Could not save')
    } finally { setSaving(false) }
  }
  const rec = data?.ceilings
  /* The finalists wear their TOUR's colour, the way every other name in this
     app does — the one place colour is spent on data here. */
  const tint = data?.tour === 'WTA' ? TOUR.F : TOUR.M
  const champ = surname(data?.champion?.name)
  const run = surname(data?.runner_up?.name)
  /* ONE NAME THROUGH THE FLOW: the card on the draw page says "Tiebreak", so
     the drawer it opens says Tiebreak. It used to say "The final", which the
     hero line then repeated two rows lower. */
  return (
    <Sheet visible={visible} onClose={onClose} title="Tiebreak">
      {!data || aces == null ? <Muted>Loading the history…</Muted> : (
        /* TWO QUESTIONS, TWO SLIDERS, TWO STAT TABLES AND A HEAD-TO-HEAD DO NOT
           FIT AN 80% SHEET (owner, 2026-09-19: "it's longer than the page").
           The sheet itself does not scroll — its children are a plain column —
           so a sheet that overflows brings its own ScrollView, the way league
           settings does. flexShrink lets it give up height inside the sheet's
           maxHeight; without it the column keeps its full content height and
           the overflow is simply clipped. */
        <ScrollView style={{ flexShrink: 1 }} contentContainerStyle={s.body}>
          {/* ── THE MATCH THIS IS ABOUT ──────────────────────────────────────
              The names are the hero: they are the bracket's own answer to
              "which final?", and the two questions below are meaningless
              without them. The champion carries the weight and the tour's
              colour; "def." is furniture and stays out of the way. */}
          <View style={s.hero}>
            <Text style={s.heroLabel}>Your current prediction for the final:</Text>
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
            {/* THE TAIL IS THE LIVE SLIDER STATE, not the saved answer, so
                dragging a knob cannot leave a sentence above it claiming
                something else (owner's wording, 2026-09-19). Quiet, because
                the two plates below say the same thing loudly — at these two
                weights it reads as a summary rather than a repeat. */}
            <Text style={s.heroNote}>
              Final score ties broken by the questions below — {aces} aces · {fmtLong(minutes)}
            </Text>
          </View>

          {/* ── QUESTION ONE ─────────────────────────────────────────────────
              Both questions take the SAME anatomy — heading and plate, then
              the slider full width, its two ends, then the evidence. That
              repetition is the structure, which is why neither is boxed in a
              card of its own: identical rounded cards would say "two things"
              where the rule and the spacing already do. */}
          <View style={s.q}>
            <View style={s.qHead}>
              <Text style={s.qTitle}>Aces by the champion</Text>
              <Plate value={String(aces)} />
            </View>
            <ValueSlider value={aces} min={0} max={acesMax} onChange={setAces}
                         disabled={data.locked} accessibilityLabel="Aces in the final" />
            {/* THE TWO ENDS OF THE TRACK, as value over meaning — no separator
                between them, because the line break is the separator. Only the
                NUMBER takes the clay: the words beside it are ordinary labels,
                and the brand's one warm note is worth less the more of it
                there is. */}
            <View style={s.ends}>
              <View>
                <Text style={s.endValue}>0</Text>
                <Text style={s.endWho}>a walkover</Text>
              </View>
              <View style={s.endRight}>
                <Text style={[s.endValue, s.endRecord]}>{acesMax}</Text>
                <Text style={[s.endWho, s.endWhoRight]} numberOfLines={2}>
                  {/* "the record" implied all time, and the ends read the
                      past 12 months now (final_stats.ceilings). */}
                  {rec?.aces_record
                    ? `the most in 12 months — ${surname(rec.aces_record.player)}, ${rec.aces_record.tournament} ${rec.aces_record.year}`
                    : 'the most in 12 months'}
                </Text>
              </View>
            </View>
            <StatTable rows={refRows(data, 'aces')} unit="aces / set" />
          </View>

          {/* ── QUESTION TWO ── */}
          <View style={[s.q, s.qRule]}>
            <View style={s.qHead}>
              <Text style={s.qTitle}>Length of the final</Text>
              <Plate value={fmtMinutes(minutes)} sub={`${minutes} min`} />
            </View>
            <ValueSlider value={minutes} min={0} max={durMax} onChange={setMinutes}
                         disabled={data.locked} accessibilityLabel="Length of the final" />
            <View style={s.ends}>
              <View>
                <Text style={s.endValue}>0</Text>
                <Text style={s.endWho}>a walkover</Text>
              </View>
              <View style={s.endRight}>
                <Text style={[s.endValue, s.endRecord]}>{fmtLong(durMax)}</Text>
                <Text style={[s.endWho, s.endWhoRight]} numberOfLines={2}>
                  {rec?.duration_record
                    ? `the longest in 12 months — ${rec.duration_record.tournament} ${rec.duration_record.year}`
                    : 'the longest in 12 months'}
                </Text>
              </View>
            </View>
            <StatTable rows={refRows(data, 'minutes')} unit="min / set" />
          </View>

          <Meetings data={data} />

          {/* WHAT LEAVING IT ALONE MEANS. Last, not first: it is the answer for
              somebody who has decided not to answer, and until then it is the
              least useful line in the drawer (owner, 2026-09-18). */}
          {!data.guess && data.default ? (
            <Text style={s.default}>
              {`Leave this alone and you hold ${data.tour} ${data.surface.toLowerCase()}’s ${data.default.year} average: `}
              <Text style={s.defaultStrong}>{`${data.default.aces} aces, ${fmtLong(data.default.minutes)}`}</Text>
            </Text>
          ) : null}
          {data.actual ? (
            <Text style={s.actual}>
              {`The final: ${data.actual.final_aces} aces, ${fmtLong(data.actual.final_duration_min)}.`}
            </Text>
          ) : null}
          {error ? <Text style={s.error}>{error}</Text> : null}
          <View style={s.actions}>
            <Pressable onPress={onClose} style={[s.btn, s.btnQuiet]} accessibilityRole="button">
              <Text style={s.btnQuietText}>{data.locked ? 'Close' : 'Later'}</Text>
            </Pressable>
            {!data.locked && (
              <Pressable onPress={save} disabled={saving} style={[s.btn, saving && { opacity: 0.6 }]} accessibilityRole="button">
                <Text style={s.btnText}>{saving ? 'Saving…' : 'Save answers'}</Text>
              </Pressable>
            )}
          </View>
        </ScrollView>
      )}
    </Sheet>
  )
}

export function FinalGuessCard({ tournamentId, enabled, onOpen, refreshKey }) {
  const ctx = useApi(enabled ? `final-guess:${tournamentId}:card:${refreshKey || 0}` : null, () => getFinalGuess(tournamentId), { enabled: !!enabled })
  const data = ctx.data
  // Hidden until the draw is open for picks, or this bracket has answered
  // (owner, 2026-09-18) — scoring.tiebreakVisible.
  if (!enabled || !tiebreakVisible(data)) return null
  const g = data.guess
  return (
    <Pressable onPress={onOpen} accessibilityRole="button"
               accessibilityLabel="Your prediction for the final, and the tiebreak questions">
      <Card>
        <View style={s.cardRow}>
          <View style={{ flex: 1 }}>
            {/* ONE LINE AND THE ANSWERS, nothing more (owner, 2026-09-19).
                The picked final and the sentence about ties belong to the
                sheet — "only visible once you click in" — because this card
                sits in the draw between match groups, and a four-line panel
                there is reading matter in the way of the bracket. */}
            <Title>Tiebreak</Title>
            <Muted>{g ? `${g.final_aces} aces · ${fmtMinutes(g.final_duration_min)}`
                      : data.default ? `Holding the average: ${data.default.aces} aces · ${fmtMinutes(data.default.minutes)}`
                      : (data.locked ? 'No answers given' : 'Answer the two questions about the final')}</Muted>
          </View>
          {data.actual ? <Muted>final: {data.actual.final_aces} · {fmtMinutes(data.actual.final_duration_min)}</Muted> : null}
        </View>
      </Card>
    </Pressable>
  )
}

const s = StyleSheet.create({
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
  heroNote: { ...T.tiny, color: C.faint, marginTop: 2 },

  /* ── A question ────────────────────────────────────────────────────────── */
  q: { gap: S.sm },
  // The rule between the two questions, and the only one in this half.
  qRule: { borderTopWidth: 1, borderTopColor: C.border, paddingTop: S.lg },
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
  ends: { flexDirection: 'row', justifyContent: 'space-between', gap: S.md, marginTop: -2 },
  endRight: { flexShrink: 1, alignItems: 'flex-end' },
  // Right-aligned only on the right end; the left keeps the default.

  endValue: { ...T.smallMed, color: C.muted, fontVariant: ['tabular-nums'] },
  endRecord: { color: C.clay },
  endWho: { ...T.tiny, color: C.faint },
  endWhoRight: { textAlign: 'right' },

  /* ── The evidence, as a table ──────────────────────────────────────────── */
  table: { marginTop: S.xs },
  tableHead: { flexDirection: 'row', alignItems: 'flex-end', gap: S.sm, paddingBottom: 2 },
  tableUnit: { ...T.tiny, color: C.muted, minWidth: 54, textAlign: 'right' },
  sampleCol: { width: 78 },
  tr: { flexDirection: 'row', alignItems: 'center', gap: S.sm, paddingVertical: 4 },
  trRule: { borderTopWidth: 1, borderTopColor: C.border },
  tdLabel: { ...T.small, color: C.inkBody, flex: 1 },
  /* The numeric spine: one width, right-aligned, tabular figures. Three
     numbers in a column can be compared without being read. */
  tdValue: {
    ...T.score, color: C.ink, minWidth: 54, textAlign: 'right',
    fontVariant: ['tabular-nums'],
  },
  tdNote: { ...T.tiny, color: C.faint, width: 78, textAlign: 'right' },

  /* ── A section heading: title, rule, and a number on the end ───────────── */
  section: { gap: S.xs },
  sectionHead: { flexDirection: 'row', alignItems: 'center', gap: S.sm },
  sectionTitle: { ...T.h2, color: C.ink },
  sectionRule: { flex: 1, height: 1, backgroundColor: C.border },
  record: { ...T.score, color: C.muted, fontVariant: ['tabular-nums'] },

  /* ── One meeting ───────────────────────────────────────────────────────── */
  meet: { flexDirection: 'row', alignItems: 'center', gap: S.sm, paddingVertical: 6 },
  /* W or L from the CHAMPION's side, in the bracket's own pick colours. */
  wl: {
    width: 26, height: 26, borderRadius: R.sm, borderWidth: 1,
    alignItems: 'center', justifyContent: 'center',
  },
  wlWon: { backgroundColor: PICK.correct.bg, borderColor: PICK.correct.border },
  wlLost: { backgroundColor: PICK.wrong.bg, borderColor: PICK.wrong.border },
  wlText: { ...T.eyebrow, fontSize: 13 },
  meetBody: { flex: 1, gap: 0 },
  meetWhen: { ...T.tiny, color: C.faint },
  meetYear: { ...T.tiny, color: C.muted },
  meetScore: { ...T.smallMed, color: C.ink },
  meetTime: { ...T.tiny, color: C.faint },
  meetAces: { alignItems: 'flex-end' },
  meetAcesN: { ...T.score, color: C.ink, fontVariant: ['tabular-nums'] },
  meetAcesDash: { color: C.faint },
  meetAcesLabel: { ...T.tiny, color: C.faint, marginTop: -3 },
  more: { ...T.tiny, color: C.faint, paddingTop: 2 },
  /* Which number belongs to whom, said once at the bottom rather than on
     every row. */
  meetKey: { ...T.tiny, color: C.faint, paddingTop: S.xs },

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
  cardRow: { flexDirection: 'row', alignItems: 'center', gap: S.sm },
})
