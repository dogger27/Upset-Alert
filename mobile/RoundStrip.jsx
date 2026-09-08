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
import Animated, { useAnimatedStyle, useSharedValue } from 'react-native-reanimated'
import { scheduleOnUI } from 'react-native-worklets'
import { shortRound } from './rounds'
import { C, S, T } from './theme'

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

  const pillStyle = useAnimatedStyle(() => {
    const f = frames.value
    const p = pos.value
    const lo = Math.floor(p), hi = Math.ceil(p)
    const a = f[lo], b = f[hi]
    if (!a) return { opacity: 0 }
    const t = b ? p - lo : 0
    const x = b ? a.x + (b.x - a.x) * t : a.x
    const w = b ? a.w + (b.w - a.w) * t : a.w
    return { opacity: 1, width: w, transform: [{ translateX: x }] }
  })

  return (
    <View style={s.bar}>
      <View style={s.row}>
        <Animated.View style={[s.pill, pillStyle]} pointerEvents="none" />
        {rounds.flatMap(([num, matches], i) => {
          const on = num === active
          const label = (
            <Pressable key={num} onPress={() => onPick(num)} hitSlop={6}
                       accessibilityRole="button" accessibilityState={{ selected: on }}
                       style={s.round} onLayout={e => onLabelLayout(i, e)}>
              <Label i={i} pos={pos} on={on}>
                {shortRound(matches[0]?.round_name, num)}
              </Label>
            </Pressable>
          )
          if (i === 0) return [label]
          // A dot between every pair of labels, hidden while the pill is
          // on either of them — so "R32 • [R16] • QF" reads "R32 [R16] QF"
          // and the labels never move.
          return [<Dot key={`dot${num}`} i={i} pos={pos} />, label]
        })}
      </View>
    </View>
  )
}

function Label({ i, pos, on, children }) {
  const style = useAnimatedStyle(() => ({
    color: Math.abs(pos.value - i) < 0.5 ? C.greenBright : C.muted,
  }), [i])
  return (
    <Animated.Text style={[s.roundText, on && s.roundTextOn, style]} numberOfLines={1}
                   adjustsFontSizeToFit minimumFontScale={0.6}>
      {children}
    </Animated.Text>
  )
}

function Dot({ i, pos }) {
  const style = useAnimatedStyle(() => {
    const p = pos.value
    return { opacity: Math.abs(p - i) < 0.5 || Math.abs(p - (i - 1)) < 0.5 ? 0 : 1 }
  }, [i])
  return <Animated.Text style={[s.dot, style]}>•</Animated.Text>
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
     and the pill adds a point each side, so the bar is about 20pt. The
     labels may shrink together (flexShrink on each, the type shrinking to
     fit inside) so seven rounds always fit the width, at any text size. */
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 4, paddingHorizontal: S.lg },
  round: {
    paddingHorizontal: 5, paddingVertical: 1, borderRadius: 5, borderWidth: 1, borderColor: 'transparent',
    flexShrink: 1, minWidth: 0,
    zIndex: 1,   // above the pill, whatever a renderer makes of sibling order
  },
  // The pill: a filled, edged rounded rectangle the size of a label's frame,
  // behind whichever label pos says — the only bright thing here.
  pill: {
    position: 'absolute', left: 0, top: 0, bottom: 0,
    borderRadius: 5, borderWidth: 1,
    backgroundColor: C.greenDeep, borderColor: C.greenLit,
  },
  // Dimmed but still READ — these are the control, not decoration.
  roundText: { ...T.smallMed, lineHeight: undefined, color: C.muted },
  roundTextOn: { fontFamily: 'Archivo_700Bold' },
  // Punctuation, so it sits below the labels it separates without vanishing.
  dot: { ...T.smallMed, lineHeight: undefined, color: C.borderLit },
})
