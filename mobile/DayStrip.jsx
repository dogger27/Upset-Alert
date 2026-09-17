/* DayStrip — the schedule's day selector: Q1, Q2, 1, 2 … one chip per day
 * that has a sheet, the chosen day lit and a size up, the strip sliding
 * sideways when the days outnumber the width and keeping the chosen chip
 * as near the centre as the ends allow.
 *
 * NO SCROLLVIEW. A programmatic scrollTo on a Fabric ScrollView paints one
 * stale frame before it settles (RoundScrub.jsx, and the memory
 * fabric-scrollto-flickers), and this strip repositions itself on every
 * tap. So it is RoundScrub's own list pan turned on its side: one shared
 * value `tx` is the only horizontal position, a horizontal pan drags it
 * with a rubber band past either end and flings it with a decay, and a
 * pick moves it with a timed ease. Everything the UI thread needs — the
 * travel limit, the centring offset — lives in shared values it reads. */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import Animated, {
  Easing, cancelAnimation, useAnimatedStyle, useSharedValue, withDecay, withTiming,
} from 'react-native-reanimated'
import { C, S } from './theme'
import { leading } from './fontScale.js'
import { textWidth } from './measure'
import { pickLevel } from './stripLayout'

// The scrub's axis lock, mirrored: a sideways drag of 8pt is ours, a
// vertical one of 12pt is the page's.
const AXIS_ACTIVE_X = 8
const AXIS_FAIL_Y = 12
const RUBBER = 0.6
const RUBBER_FACTOR = 0.6
const MOVE = { duration: 240, easing: Easing.bezier(0.22, 0.61, 0.36, 1) }
const FACE = 'Archivo_500Medium', SIZE = 13         // a chip
const FACE_ON = 'Archivo_700Bold', SIZE_ON = 15     // the chosen one, a size up

/* `right` — a node pinned at the far right of the bar, outside the sliding
   row: the schedule puts the chosen day's date there. The chips slide
   beneath it, and the centring below treats the slot as outside the
   viewport, so a centred chip is centred in the space that is actually
   visible. With no days at all the bar is just this slot. */
export function DayStrip({ days, active, onPick, right }) {
  const tx = useSharedValue(0)          // how far the row has slid left
  const start = useSharedValue(0)
  const dragging = useSharedValue(false)
  const lim = useSharedValue(0)         // the furthest it can slide
  const lead = useSharedValue(0)        // centring air when it all fits
  const [barW, setBarW] = useState(0)
  const [rightW, setRightW] = useState(0)
  const vw = Math.max(0, barW - rightW)   // what the chips can be seen in
  const [cw, setCw] = useState(0)
  /* WHERE EACH CHIP IS, from its own onLayout — relative to the row, which
     is what tx slides. The counter is bumped when one reports so the
     centring below runs again: the chosen chip is a size up, and its new
     width moves everything after it. */
  const chips = useRef(new Map())
  const [measured, setMeasured] = useState(0)
  /* HOW TIGHT. The type never shrinks; the air between and inside the chips
     does, level by level, until every day fits the room — and only when the
     tightest level still does not fit does the strip scroll (owner,
     2026-09-17). Chosen from font metrics before layout, so there is no
     trial pass on screen: `stripLayout.js`, on its own suite. */
  const activeIndex = days.findIndex(d => d.date === active)
  const widths = useMemo(
    () => days.map((d, i) => textWidth(d.label, i === activeIndex ? FACE_ON : FACE, i === activeIndex ? SIZE_ON : SIZE)),
    [days, activeIndex],
  )
  const { level } = useMemo(() => pickLevel(widths, activeIndex, vw - 2 * S.md), [widths, activeIndex, vw])

  useEffect(() => {
    lim.value = Math.max(0, cw - vw)
    lead.value = Math.max(0, (vw - cw) / 2)
  }, [cw, vw, lim, lead])

  /* CENTRE THE PICK — as near as the ends allow: the first days sit against
     the left edge and the last against the right, as a scroll view's would.
     The first placement is instant (the strip has nothing to move from);
     every later one eases. */
  const placed = useRef(false)
  useEffect(() => {
    const c = chips.current.get(active)
    if (!c || vw <= 0) return
    const L = Math.max(0, cw - vw)
    const target = Math.min(L, Math.max(0, c.x + c.w / 2 - vw / 2))
    cancelAnimation(tx)
    if (!placed.current) { tx.value = target; placed.current = true }
    else tx.value = withTiming(target, MOVE)
  }, [active, vw, cw, measured, tx])

  const pan = useMemo(() => Gesture.Pan()
    .activeOffsetX([-AXIS_ACTIVE_X, AXIS_ACTIVE_X])
    .failOffsetY([-AXIS_FAIL_Y, AXIS_FAIL_Y])
    .onTouchesDown(() => {
      'worklet'
      cancelAnimation(tx)   // a touch stops a fling, as it would a scroll view's
    })
    .onStart(() => {
      'worklet'
      cancelAnimation(tx)
      start.value = tx.value
      dragging.value = true
    })
    .onUpdate((ev) => {
      'worklet'
      if (!dragging.value) return
      let x = start.value - ev.translationX
      const L = lim.value
      if (x < 0) x *= RUBBER
      else if (x > L) x = L + (x - L) * RUBBER
      tx.value = x
    })
    .onEnd((ev) => {
      'worklet'
      if (!dragging.value) return
      dragging.value = false
      tx.value = withDecay({
        velocity: -ev.velocityX, clamp: [0, lim.value], rubberBandEffect: true, rubberBandFactor: RUBBER_FACTOR,
      })
    })
    .onFinalize(() => {
      'worklet'
      if (!dragging.value) return
      dragging.value = false
      tx.value = withDecay({ velocity: 0, clamp: [0, lim.value], rubberBandEffect: true, rubberBandFactor: RUBBER_FACTOR })
    }), [tx, start, dragging, lim])

  const slide = useAnimatedStyle(() => ({ transform: [{ translateX: lead.value - tx.value }] }))

  return (
    <GestureDetector gesture={pan} touchAction="pan-y">
      {/* No ref on the detector's child (React 19 logs element.ref). */}
      <View style={s.bar} onLayout={e => setBarW(e.nativeEvent.layout.width)}>
        <Animated.View
          style={[s.row, { gap: level.gap }, slide]}
          onLayout={e => setCw(e.nativeEvent.layout.width)}
        >
          {days.map(({ date, label }) => {
            const on = date === active
            return (
              <Pressable
                key={date}
                onPress={() => onPick(date)}
                onLayout={e => {
                  const { x, width } = e.nativeEvent.layout
                  chips.current.set(date, { x, w: width })
                  setMeasured(n => n + 1)
                }}
                hitSlop={{ top: 8, bottom: 8, left: 0, right: 0 }}
                style={({ pressed }) => [
                  s.chip, { paddingHorizontal: level.pad, minWidth: level.min },
                  on && s.chipOn, on && { paddingHorizontal: level.padOn, minWidth: level.minOn },
                  pressed && !on && s.chipPressed,
                ]}
                accessibilityRole="button"
                accessibilityState={{ selected: on }}
                accessibilityLabel={`${label.startsWith('Q') ? `Qualifying day ${label.slice(1)}` : `Day ${label}`}, ${date}`}
              >
                <Text style={[s.text, on && s.textOn]}>{label}</Text>
              </Pressable>
            )
          })}
        </Animated.View>
        {right != null && (
          <View style={s.right} onLayout={e => setRightW(e.nativeEvent.layout.width)}>
            {right}
          </View>
        )}
      </View>
    </GestureDetector>
  )
}

const s = StyleSheet.create({
  /* The draw page's round bar, edge to edge: the screen pads its body S.lg
     a side, and a ruled bar that stopped short of the edges read as a box.
     overflow hidden — the row slides under the glass at both ends. */
  bar: {
    marginHorizontal: -S.lg,
    backgroundColor: '#12262a',
    borderTopWidth: 1, borderBottomWidth: 1, borderColor: C.borderLit,
    paddingVertical: 3,
    minHeight: leading(27) + 6,   // the chosen chip plus the padding: 33pt, 13% under the 38 it was
    overflow: 'hidden',
  },
  /* flex-start, so the row is as wide as its chips and no wider — that
     width, against the bar's, is the travel. Centring when it all fits is
     `lead` in the transform, not alignment, so one measurement serves. */
  row: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: S.md, alignSelf: 'flex-start' },   // gap: from the level
  /* A fixed-height box with the glyph centred in it; no lineHeight on the
     text, which sinks caps on iOS (memory ios-lineheight-sinks-caps). */
  chip: {   // width and padding: from the level
    height: leading(23), borderRadius: 6,
    borderWidth: 1, borderColor: 'transparent',
    alignItems: 'center', justifyContent: 'center',
  },
  /* The slot the chips slide under: the bar's own fill so they vanish at
     its edge, a hairline to mark the edge, the bar's full height so it
     centres whatever it holds. */
  right: {
    position: 'absolute', top: 0, bottom: 0, right: 0,
    justifyContent: 'center', alignItems: 'flex-end',
    paddingLeft: S.md, paddingRight: S.lg,
    backgroundColor: '#12262a', borderLeftWidth: 1, borderLeftColor: C.borderLit,
  },
  chipPressed: { backgroundColor: C.greenDeep, borderColor: C.borderLit },
  /* THE PICK: lit — the only filled chip on the bar — and a size up in
     every dimension, so it reads from across the room. Dark ink on the
     bright fill: C.bg on C.greenLit is 7:1. */
  chipOn: {
    height: leading(27), borderRadius: 7,
    backgroundColor: C.greenLit, borderColor: C.greenBright,
  },
  text: { fontFamily: FACE, fontSize: SIZE, color: C.muted },
  textOn: { fontFamily: FACE_ON, fontSize: SIZE_ON, color: C.bg },
})
