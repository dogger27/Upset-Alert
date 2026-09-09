/*
 * The draw's round bar: every round on one line, ruled above and below.
 *
 * Tap a round to go to it. SCRUBBING is the whole screen's gesture
 * (RoundScrub.jsx), this bar included — a gesture that worked only while
 * the finger was on these few glyphs was the complaint that produced it.
 *
 * THE PILL GLIDES. It is one view of its own behind the labels, placed by
 * the scrub's `pos` on the UI thread: at 2.4 it sits forty percent of the
 * way from the third label's frame to the fourth's, so the bar moves with
 * the bracket under it rather than jumping when the pull lands. The labels
 * keep their places — the dots either side of the selected round are hidden,
 * not removed, so nothing measured ever shifts — and each label's colour
 * turns as the pill crosses its middle. The weight still changes on the
 * commit: a heavier face is a wider word, and a width that changed
 * mid-glide would pull the frames out from under the pill.
 *
 * A ROW OF VIEWS, not one Text with pressable spans, because the pill is a
 * bordered view and a nested Text cannot carry a border on iOS.
 */
import { useCallback, useRef } from 'react'
import { Pressable, StyleSheet, View } from 'react-native'
import Animated, { useDerivedValue, useSharedValue } from 'react-native-reanimated'
import { scheduleOnUI } from 'react-native-worklets'
import { shortRound } from './rounds'
import { C, S, T } from './theme'

const PILL_W = 40   // the pill's layout width; scaled to each label

export function RoundStrip({ rounds, active, onPick, scrub }) {
  const activeIdx = rounds.findIndex(([n]) => n === active)
  // Without a scrub to follow (none is wired), the pill sits on the active round.
  const stillPos = useSharedValue(activeIdx)
  stillPos.value = activeIdx
  const pos = scrub?.pos ?? stillPos

  // Each label's frame within the row, measured as it lays out.
  const frames = useSharedValue([])
  const framesRef = useRef([])
  const onLabelLayout = useCallback((i, e) => {
    const { x, width } = e.nativeEvent.layout
    const next = framesRef.current.slice()
    next[i] = { x, w: width }
    framesRef.current = next
    scheduleOnUI(() => { 'worklet'; frames.value = next })
  }, [frames])

  /* BY TRANSFORM ONLY. A width is a layout prop, and a layout prop changing
     every frame of a pull is a shadow-tree commit every frame — the whole
     draw laid out again to move one pill. The pill is a fixed PILL_W wide
     and scaled in X to the label under it; its border grows a hair with it,
     which is invisible at these widths. */
  /* Inline shared values, not an animated style: this bar re-renders on
     every landing (the bold label moves), and an animated style would send
     its first render's pill position again each time — a frame of the pill
     back on the round the draw opened on (see RoundScrub.jsx). */
  const pillAt = useDerivedValue(() => {
    const f = frames.value
    const p = pos.value
    const lo = Math.floor(p), hi = Math.ceil(p)
    const a = f[lo], b = f[hi]
    if (!a) return { x: 0, w: PILL_W, on: 0 }
    const t = b ? p - lo : 0
    const x = b ? a.x + (b.x - a.x) * t : a.x
    const w = b ? a.w + (b.w - a.w) * t : a.w
    return { x: x + (w - PILL_W) / 2, w, on: 1 }
  })
  const pillOpacity = useDerivedValue(() => pillAt.value.on)
  const pillX = useDerivedValue(() => pillAt.value.x)
  const pillScale = useDerivedValue(() => pillAt.value.w / PILL_W)

  return (
    <View style={s.bar}>
      <View style={s.row}>
        <Animated.View style={[s.pill,
                               { opacity: pillOpacity.value, transform: [{ translateX: pillX.value }, { scaleX: pillScale.value }] },
                               { opacity: pillOpacity, transform: [{ translateX: pillX }, { scaleX: pillScale }] }]}
                       pointerEvents="none" />
        {rounds.map(([num, matches], i) => {
          const on = num === active
          return (
            <Pressable key={num} onPress={() => onPick(num)} hitSlop={6}
                       accessibilityRole="button" accessibilityState={{ selected: on }}
                       style={s.round} onLayout={e => onLabelLayout(i, e)}>
              <Label i={i} pos={pos} on={on}>
                {shortRound(matches[0]?.round_name, num)}
              </Label>
            </Pressable>
          )
        })}
      </View>
    </View>
  )
}

function Label({ i, pos, on, children }) {
  const color = useDerivedValue(() => (Math.abs(pos.value - i) < 0.5 ? C.greenBright : C.muted), [i])
  return (
    <Animated.Text style={[s.roundText, on && s.roundTextOn, { color: color.value }, { color }]} numberOfLines={1}>
      {children}
    </Animated.Text>
  )
}

const s = StyleSheet.create({
  /* Its own field, ruled top and bottom, so the bar reads as a control
     strip rather than a line of text floating between the banner and the
     draw. The fill is this bar's alone — nothing else on the screen is
     this teal-black — so it is found at a glance. marginTop matches the
     banner's own air. */
  bar: {
    // Black above and below, so the bar is a band between the banner and
    // the draw rather than glued to either.
    marginTop: S.md, marginBottom: S.xs,
    /* EDGE TO EDGE: the screen pads its body S.lg a side, and a ruled bar
       that stopped short of the edges read as a box, not a bar. The row
       inside keeps that padding so the labels do not touch the glass. */
    marginHorizontal: -S.lg,
    backgroundColor: '#12262a',
    borderTopWidth: 1, borderBottomWidth: 1, borderColor: C.borderLit,
    paddingVertical: 3,
  },
  /* THIN: no padding of its own; the line box is the type's own height
     and the pill adds a point each side, so the bar is about 20pt. EVERY
     LABEL AT ONE SIZE, spread across the bar with the space shared out
     between them: nothing shrinks, nothing is cut. The labels used to give
     way to fit (flexShrink, the type scaling down), and with eight of them
     the F came out half the size and the trophy lost its edge (owner,
     2026-09-09). No dots between them either. */
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: S.md },
  round: {
    paddingHorizontal: 5, paddingVertical: 1, borderRadius: 5, borderWidth: 1, borderColor: 'transparent',
    flexShrink: 0,
    zIndex: 1,   // above the pill, whatever a renderer makes of sibling order
  },
  // The pill: a filled, edged rounded rectangle the size of a label's frame,
  // behind whichever label pos says — the only bright thing here.
  pill: {
    position: 'absolute', left: 0, top: 0, bottom: 0, width: PILL_W,
    borderRadius: 5, borderWidth: 1,
    backgroundColor: C.greenDeep, borderColor: C.greenLit,
  },
  // Dimmed but still READ — these are the control, not decoration.
  roundText: { ...T.smallMed, lineHeight: undefined, color: C.muted },
  roundTextOn: { fontFamily: 'Archivo_700Bold' },
})
