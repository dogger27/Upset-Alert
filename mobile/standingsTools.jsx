/*
 * The two instruments under a standings table, ported from the site's
 * standings panel: the match timeline (a slider that rewinds the table
 * through the matches that produced it) and What if (from the semis on,
 * every way the last matches can go, one label each, the table re-scored
 * under the chosen one). The screens own the state; this file draws.
 *
 * The slider is our own: a track with a pan, not a native slider, so no
 * native module and no rebuild. Position comes from the finger's x inside
 * the track — never a translation, which RNGH on web resets at activation.
 */
import { useMemo, useState } from 'react'
import { Pressable, StyleSheet, Switch, Text, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import { C, T } from './theme'
import { roundTag, scrubEntries, surname, worldEntries, worldLine } from './scoring'

const THUMB = 28

/* ── The view a standings screen shows ──────────────────────────────────── */

/* The rows as they stand, rewound to a point in the timeline, or under a
   chosen world — one of the three, never two: moving the slider leaves the
   world and choosing a world drops the slider. `finalPlayed` is what the
   medals key on: a chosen world has played its final. */
export function useStandingsView(data, t) {
  const [pos, setPosRaw] = useState(null)
  const [worldIdx, setWorldIdxRaw] = useState(null)
  const timeline = useMemo(() => data?.matches_timeline ?? [], [data])
  const worlds = data?.worlds ?? null
  const numRounds = t?.num_rounds ?? (t?.draw_size ? Math.round(Math.log2(t.draw_size)) : 7)
  const world = worlds && worldIdx != null && worldIdx < worlds.length ? worlds[worldIdx] : null
  const scrubbing = !world && pos != null && pos < timeline.length
  const entries = useMemo(() => {
    const base = data?.entries ?? []
    if (world) return worldEntries(base, world, data?.world_predictions ?? {})
    if (scrubbing) return scrubEntries(base, timeline, pos, data?.user_predictions ?? {}, data?.finish_history ?? {})
    return base
  }, [data, world, scrubbing, timeline, pos])
  const finishFrom = data?.finish_from ?? null
  return {
    entries, world, scrubbing, finalPlayed: !!world, finishFrom,
    pos, setPos: p => { setPosRaw(p); setWorldIdxRaw(null) },
    /* Sorted by Finish, the slider stops where the column begins: a table
       ordered by the range cannot sit at a position where it is dashes. */
    clampToFinish: () => { if (pos != null && finishFrom != null && pos < finishFrom) setPosRaw(finishFrom >= timeline.length ? null : finishFrom) },
    worldIdx, setWorldIdx: i => { setWorldIdxRaw(i); setPosRaw(null) },
    timeline, worlds, tailMatches: data?.tail_matches ?? [], numRounds,
  }
}

/* The instruments under the table. The slider goes while a world is chosen:
   it rewinds the past, and a chosen future has none. */
export function StandingsFoot({ view, minPos = 0 }) {
  return (
    <>
      {!view.world && view.timeline.length > 0 ? (
        <Scrubber timeline={view.timeline} pos={view.pos} onChange={view.setPos} numRounds={view.numRounds} min={minPos} />
      ) : null}
      {view.worlds && view.worlds.length > 0 ? (
        <WhatIf worlds={view.worlds} tailMatches={view.tailMatches} numRounds={view.numRounds}
                worldIdx={view.worldIdx} onChange={view.setWorldIdx} />
      ) : null}
    </>
  )
}

/* ── The match timeline ─────────────────────────────────────────────────── */

export function Scrubber({ timeline, pos, onChange, numRounds, min = 0 }) {
  const max = timeline.length
  const lo = Math.min(min, max)
  const at = pos ?? max
  const scrubbing = at < max
  const [width, setWidth] = useState(0)
  /* At 0 there is no last match: the board before a ball was struck. */
  const last = at > 0 ? timeline[at - 1] : null
  const flash = scrubbing ? last : null
  const fromX = x => {
    const usable = Math.max(1, width - THUMB)
    const v = lo + Math.round(Math.max(0, Math.min(1, (x - THUMB / 2) / usable)) * (max - lo))
    onChange(v >= max ? null : v)
  }
  /* A horizontal pan inside a vertical scroller: claim sideways moves early
     and yield to the scroller on a vertical one, the round scrub's rule. A
     touch-down already sets the position, so a tap on the track lands. */
  const pan = Gesture.Pan().runOnJS(true)
    .activeOffsetX([-4, 4]).failOffsetY([-10, 10])
    .onBegin(e => fromX(e.x)).onUpdate(e => fromX(e.x))
  const left = width ? ((at - lo) / Math.max(1, max - lo)) * (width - THUMB) : 0
  const label = !scrubbing
    ? `All ${max} match${max !== 1 ? 'es' : ''}`
    : `${at} / ${max} matches${last ? ` (through ${roundTag(last.round_number, numRounds)})` : ''}`
  return (
    <View style={s.scrub}>
      {/* The answer to "what happened here" sits ABOVE the slider, so the
          slider never moves under the finger when it appears. */}
      {flash ? (
        <Text style={s.flash} numberOfLines={2}>
          {roundTag(flash.round_number, numRounds)}: {flash.winner_name ?? '?'} def. {flash.loser_name ?? '?'}
          {flash.completed_at ? <Text style={s.flashWhen}>{'\n'}{when(flash.completed_at)}</Text> : null}
        </Text>
      ) : null}
      <GestureDetector gesture={pan}>
        <View style={s.track} onLayout={e => setWidth(e.nativeEvent.layout.width)} hitSlop={{ top: 10, bottom: 10 }}
              accessibilityRole="adjustable" accessibilityLabel="Match timeline"
              accessibilityValue={{ min: lo, max, now: at }}>
          <View style={s.rail} />
          <View style={[s.fill, { width: left + THUMB / 2 }]} />
          <View style={[s.thumb, { left }]} />
        </View>
      </GestureDetector>
      <Text style={[s.label, scrubbing && s.labelOn]}>{label}</Text>
    </View>
  )
}

function when(iso) {
  try {
    return new Date(iso).toLocaleString('en-US', { month: 'short', day: '2-digit', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })
  } catch { return '' }
}

/* ── What if ────────────────────────────────────────────────────────────── */

export function WhatIf({ worlds, tailMatches, numRounds, worldIdx, onChange }) {
  const n = worlds.length
  const world = worldIdx != null && worldIdx < n ? worlds[worldIdx] : null
  const step = d => onChange(((worldIdx ?? 0) + d + n) % n)
  const WORDS = { 2: 'two', 4: 'four', 8: 'eight' }
  return (
    <View style={[s.whatif, world && s.whatifOn]}>
      <View style={s.head}>
        <Switch value={!!world} onValueChange={v => onChange(v ? 0 : null)}
                trackColor={{ false: C.border, true: C.green }} thumbColor="#ffffff"
                ios_backgroundColor={C.border} accessibilityLabel="What if" />
        {world ? (
          <Text style={s.hintStrong}>What if</Text>
        ) : null}
        {world ? (
          <View style={s.rail2}>
            <View style={s.dots} accessibilityElementsHidden>
              {worlds.map((_, i) => <View key={i} style={[s.dot, i === worldIdx && s.dotOn]} />)}
            </View>
            <Text style={s.count}>{worldIdx + 1} / {n}</Text>
          </View>
        ) : (
          <Text style={s.hint} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.75}>
            <Text style={s.hintStrong}>What if</Text> · {WORDS[n] ?? n} ways it can end
          </Text>
        )}
      </View>
      {world ? (
        <>
          <View style={s.nameRow}>
            <Arrow d={-1} onPress={() => step(-1)} />
            <Text style={s.name} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.6}>{worldLine(world)}</Text>
            <Arrow d={1} onPress={() => step(1)} />
          </View>
          <MiniBracket world={world} tailMatches={tailMatches} numRounds={numRounds} />
        </>
      ) : null}
    </View>
  )
}

function Arrow({ d, onPress }) {
  return (
    <Pressable onPress={onPress} hitSlop={6} style={({ pressed }) => [s.arrow, pressed && s.arrowDown]}
               accessibilityRole="button" accessibilityLabel={d < 0 ? 'Previous world' : 'Next world'}>
      {/* A drawn chevron, not a glyph: text sits on a baseline and a "‹" rode
          high in the ring however the line height was set. Two borders of a
          square, turned — dead centre by construction. */}
      <View style={[s.chevron, d < 0 ? s.chevronLeft : s.chevronRight]} />
    </Pressable>
  )
}

/* Semis, final, winner: three columns of equal-width surname pills joined by
   braces. The winner of each match is the lit pill; the champion wears the
   podium's gold. A name shrinks to its pill rather than losing its tail. */
function MiniBracket({ world, tailMatches, numRounds }) {
  const won = Object.fromEntries(world.results.map(r => [r.match_id, r.winner_id]))
  const winnerOf = m => won[m.match_id] ?? m.winner_id
  const names = {}
  for (const m of tailMatches) { names[m.player1_id] = m.player1; names[m.player2_id] = m.player2 }
  names[world.final.winner_id] ??= world.final.winner
  names[world.final.loser_id] ??= world.final.loser
  const semis = tailMatches.filter(m => m.round_number === numRounds - 1)
  const fin = tailMatches.find(m => m.round_number === numRounds)
  if (semis.length !== 2) return null
  const finalists = semis.map(winnerOf)
  const champion = fin ? winnerOf(fin) : world.final.winner_id
  const Pill = ({ id, state }) => (
    <View style={[s.pill, state === 'on' && s.pillOn, state === 'champ' && s.pillChamp]}>
      <Text style={[s.pillText, state === 'on' && s.pillTextOn, state === 'champ' && s.pillTextChamp]}
            numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.6}>{surname(names[id])}</Text>
    </View>
  )
  return (
    <View style={s.mini} accessibilityLabel="The bracket in this world">
      <View style={s.heads}>
        <Text style={[s.headCell, { width: PILL }]}>SF</Text><View style={{ width: BRACE }} />
        <Text style={[s.headCell, { width: PILL }]}>F</Text><View style={{ width: BRACE }} />
        <Text style={[s.headCell, s.headW, { width: PILL }]}>W</Text>
      </View>
      <View style={s.rows}>
        <View style={s.colSf}>
          {semis.map(m => (
            <View style={s.pair} key={m.match_id}>
              <Pill id={m.player1_id} state={winnerOf(m) === m.player1_id ? 'on' : ''} />
              <Pill id={m.player2_id} state={winnerOf(m) === m.player2_id ? 'on' : ''} />
            </View>
          ))}
        </View>
        <View style={s.braces}><Brace h={PAIR_H} /><Brace h={PAIR_H} /></View>
        <View style={s.colF}>
          {finalists.map((id, i) => <Pill key={i} id={id} state={champion === id ? 'on' : ''} />)}
        </View>
        <View style={[s.braces, s.bracesF]}><Brace h={60} /></View>
        <View style={s.colW}><Pill id={champion} state="champ" /></View>
      </View>
    </View>
  )
}

/* A right-opening brace joining two rows, with a stub out to the next column. */
function Brace({ h }) {
  return (
    <View style={[s.brace, { height: h }]}>
      <View style={s.braceStub} />
    </View>
  )
}

const PILL = 84, BRACE = 18, PILL_H = 22, PAIR_H = PILL_H * 2 + 4, COL_H = PAIR_H * 2 + 12

const s = StyleSheet.create({
  /* Timeline */
  scrub: { marginTop: 10, gap: 6 },
  flash: { ...T.small, color: C.muted, marginBottom: 2 },
  flashWhen: { ...T.tiny, color: C.muted },
  track: { height: THUMB, justifyContent: 'center' },
  rail: { position: 'absolute', left: 0, right: 0, height: 4, borderRadius: 2, backgroundColor: C.border },
  fill: { position: 'absolute', left: 0, height: 4, borderRadius: 2, backgroundColor: C.greenBright },
  thumb: {
    position: 'absolute', width: THUMB, height: THUMB, borderRadius: THUMB / 2,
    backgroundColor: C.green, borderWidth: 3, borderColor: '#ffffff',
  },
  label: { ...T.small, color: C.muted },
  labelOn: { color: C.greenBright, fontFamily: 'Archivo_700Bold' },

  /* What if */
  whatif: {
    marginTop: 12, padding: 12, gap: 10,
    borderWidth: 1, borderColor: C.border, borderRadius: 12, backgroundColor: C.raised,
  },
  whatifOn: {},
  head: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  hint: { ...T.small, color: C.muted, flex: 1 },
  hintStrong: { ...T.small, color: C.ink, fontFamily: 'Archivo_700Bold' },
  rail2: { flexDirection: 'row', alignItems: 'center', gap: 10, marginLeft: 'auto' },
  dots: { flexDirection: 'row', gap: 5, alignItems: 'center' },
  /* On the raised strip the hairline border vanishes; the lit one reads. */
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: C.borderLit },
  dotOn: { backgroundColor: C.greenBright },
  count: { fontFamily: 'Archivo_700Bold', fontSize: 12, color: C.muted, fontVariant: ['tabular-nums'] },
  nameRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  name: { flex: 1, textAlign: 'center', fontFamily: 'Archivo_700Bold', fontSize: 18, color: C.greenBright, letterSpacing: -0.2 },
  arrow: {
    width: 46, height: 46, borderRadius: 23, borderWidth: 1.5, borderColor: C.borderLit,
    alignItems: 'center', justifyContent: 'center',
  },
  arrowDown: { borderColor: C.greenBright },
  chevron: { width: 12, height: 12, borderTopWidth: 2.5, borderRightWidth: 2.5, borderColor: C.ink },
  chevronLeft: { transform: [{ translateX: 3 }, { rotate: '-135deg' }] },
  chevronRight: { transform: [{ translateX: -3 }, { rotate: '45deg' }] },

  /* Mini bracket */
  mini: { alignSelf: 'center' },
  heads: { flexDirection: 'row', marginBottom: 4 },
  headCell: { ...T.eyebrow, fontSize: 11, textAlign: 'center', color: C.muted },
  headW: { color: C.gold },
  rows: { flexDirection: 'row', alignItems: 'center' },
  colSf: { width: PILL, gap: 12 },
  pair: { gap: 4 },
  colF: { width: PILL, height: COL_H, justifyContent: 'space-between', paddingVertical: 13 },
  colW: { width: PILL, height: COL_H, justifyContent: 'center' },
  braces: { width: BRACE, gap: 12 },
  bracesF: { height: COL_H, justifyContent: 'center' },
  /* The feeder lines: the site's --border-strong, which on this darker
     strip needs the lifted green-grey to be seen at all. */
  brace: {
    width: 10, borderWidth: 1.5, borderLeftWidth: 0, borderColor: C.borderLit,
    borderTopRightRadius: 6, borderBottomRightRadius: 6,
  },
  braceStub: { position: 'absolute', right: -8, top: '50%', width: 8, borderTopWidth: 1.5, borderColor: C.borderLit },
  pill: {
    width: PILL, height: PILL_H, borderRadius: PILL_H / 2, paddingHorizontal: 6,
    borderWidth: 1.5, borderColor: C.borderLit, alignItems: 'center', justifyContent: 'center',
  },
  pillOn: { backgroundColor: C.green, borderColor: 'transparent' },
  pillChamp: { backgroundColor: '#2a2415', borderWidth: 1.5, borderColor: C.gold },
  pillText: { fontFamily: 'Archivo_500Medium', fontSize: 12, color: C.muted },
  pillTextOn: { fontFamily: 'Archivo_700Bold', color: '#ffffff' },
  pillTextChamp: { fontFamily: 'Archivo_700Bold', color: C.gold },
})
