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
import { Sheet } from './sheet'
import { Card, Muted, Title } from './ui'
import { C, R, S, T } from './theme'
import { useApi } from './useApi'
import { tiebreakVisible } from './scoring'

export function fmtMinutes(m) {
  if (m == null) return '–'
  const h = Math.floor(m / 60), mm = m % 60
  return h ? `${h}h ${String(mm).padStart(2, '0')}m` : `${mm}m`
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

function finalLine(data) {
  const champ = data?.champion?.name
  if (!champ) return null
  const run = data?.runner_up?.name
  return run ? `${surname(champ)} def. ${surname(run)}` : surname(champ)
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

function refLines(ctx, which) {
  const champ = ctx?.champion?.name, run = ctx?.runner_up?.name, ref = ctx?.reference || {}
  const key = which === 'aces' ? 'aces_per_set' : 'minutes_per_set'
  const unit = which === 'aces' ? 'aces' : 'min'
  const out = []
  const vs = perSet(ref.champion?.vs_finalist, key), surf = perSet(ref.champion?.on_surface, key)
  const all = perSet(ref.champion?.overall, key), tour = perSet(ref.tour, key)
  if (champ && vs != null) out.push(`${champ} v ${run}: ${vs} ${unit} per set (${ref.champion.vs_finalist.matches} meeting${ref.champion.vs_finalist.matches === 1 ? '' : 's'})`)
  if (champ && surf != null) out.push(`${champ} on ${ctx.surface.toLowerCase()}: ${surf} ${unit} per set (${ref.champion.on_surface.matches} matches)`)
  else if (champ && all != null) out.push(`${champ}: ${all} ${unit} per set (${ref.champion.overall.matches} matches)`)
  if (tour != null) out.push(`${ctx.tour} on ${ctx.surface.toLowerCase()}: ${tour} ${unit} per set`)
  if (!out.length) out.push(champ ? `No history held for ${champ} yet` : 'Pick your champion to see their history here')
  return out
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
  return (
    <Sheet visible={visible} onClose={onClose} title="The final">
      {!data || aces == null ? <Muted>Loading the history…</Muted> : (
        <View style={{ gap: S.md }}>
          {/* The bracket's own answer to "which final?", so the two questions
              below are about a match the reader can see named (owner,
              2026-09-19). */}
          <View style={{ gap: 2 }}>
            <Muted>Your current prediction for the final:</Muted>
            <Text style={s.finalLine}>{finalLine(data) || 'No champion picked yet'}</Text>
          </View>
          <Muted>Final score ties broken by the questions below:</Muted>
          {!data.guess && data.default ? (
            <Muted>
              Leave this alone and you hold {data.tour} {data.surface.toLowerCase()}&apos;s {data.default.year} average:
              {` ${data.default.aces} aces, ${fmtMinutes(data.default.minutes)}`}.
            </Muted>
          ) : null}
          <View style={s.q}>
            <Text style={s.label}>How many aces will the champion hit in the final?</Text>
            <View style={s.row}>
              <View style={{ flex: 1 }}>
                <ValueSlider value={aces} min={0} max={acesMax} onChange={setAces} disabled={data.locked} accessibilityLabel="Aces in the final" />
              </View>
              <Text style={s.value}>{aces}</Text>
            </View>
            <View style={s.ends}>
              <Text style={s.end}>0 · walkover</Text>
              <Text style={[s.end, { textAlign: 'right', flexShrink: 1 }]} numberOfLines={2}>{acesMax} · most ever{rec?.aces_record ? ` (${rec.aces_record.player}, ${rec.aces_record.tournament} ${rec.aces_record.year})` : ''}</Text>
            </View>
            {refLines(data, 'aces').map((l, i) => <Text key={i} style={s.ref}>• {l}</Text>)}
          </View>
          <View style={s.q}>
            <Text style={s.label}>How long will the final last?</Text>
            <View style={s.row}>
              <View style={{ flex: 1 }}>
                <ValueSlider value={minutes} min={0} max={durMax} onChange={setMinutes} disabled={data.locked} accessibilityLabel="Length of the final" />
              </View>
              <Text style={s.value}>{fmtMinutes(minutes)}</Text>
            </View>
            <View style={s.ends}>
              <Text style={s.end}>0 · walkover</Text>
              <Text style={[s.end, { textAlign: 'right', flexShrink: 1 }]} numberOfLines={2}>{fmtMinutes(durMax)} · longest on {data.surface.toLowerCase()}{rec?.duration_record ? ` (${rec.duration_record.tournament} ${rec.duration_record.year})` : ''}</Text>
            </View>
            {refLines(data, 'minutes').map((l, i) => <Text key={i} style={s.ref}>• {l}</Text>)}
          </View>
          {data.actual ? <Text style={s.actual}>The final: {data.actual.final_aces} aces, {fmtMinutes(data.actual.final_duration_min)}.</Text> : null}
          {error ? <Text style={s.error}>{error}</Text> : null}
          <View style={s.actions}>
            <Pressable onPress={onClose} style={[s.btn, s.btnQuiet]} accessibilityRole="button"><Text style={s.btnQuietText}>{data.locked ? 'Close' : 'Later'}</Text></Pressable>
            {!data.locked && (
              <Pressable onPress={save} disabled={saving} style={[s.btn, saving && { opacity: 0.6 }]} accessibilityRole="button">
                <Text style={s.btnText}>{saving ? 'Saving…' : 'Save answers'}</Text>
              </Pressable>
            )}
          </View>
        </View>
      )}
    </Sheet>
  )
}

/* The card on the draw screen: the answers as they stand, and the way in. */
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
            <Title>Your current prediction for the final</Title>
            <Text style={s.finalLine}>{finalLine(data) || 'No champion picked yet'}</Text>
            <Muted style={s.cardNote}>Final score ties broken by the questions below</Muted>
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
  q: { gap: 4 },
  // The picked final itself: the loudest line in either surface, because it
  // is the thing being talked about.
  finalLine: { ...T.h2, color: C.ink },
  cardNote: { marginTop: 2 },
  label: { ...T.bodyMed, color: C.ink },
  row: { flexDirection: 'row', alignItems: 'center', gap: S.sm },
  value: { ...T.score, color: C.ink, minWidth: 64, textAlign: 'right' },
  ends: { flexDirection: 'row', justifyContent: 'space-between', gap: S.sm },
  end: { ...T.tiny, color: C.muted },
  ref: { ...T.small, color: C.ink, marginTop: 2 },
  actual: { ...T.bodyMed, color: C.ink },
  error: { ...T.small, color: C.lossMark },
  actions: { flexDirection: 'row', justifyContent: 'flex-end', gap: S.sm, marginTop: S.xs },
  btn: { backgroundColor: C.green, borderRadius: R.sm, paddingHorizontal: 14, paddingVertical: 10 },
  btnText: { ...T.bodyMed, color: '#fff' },
  btnQuiet: { backgroundColor: 'transparent', borderWidth: 1, borderColor: C.border },
  btnQuietText: { ...T.bodyMed, color: C.ink },
  cardRow: { flexDirection: 'row', alignItems: 'center', gap: S.sm },
})
