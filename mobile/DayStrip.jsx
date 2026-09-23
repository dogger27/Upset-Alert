/* DayStrip — the schedule's day selector: one chip per day that has a sheet,
 * the chosen day lit and a size up, the strip sliding sideways when the days
 * outnumber the width and keeping the chosen chip as near the centre as the
 * ends allow.
 *
 * DOTS, NOT NUMBERS (owner, 2026-09-21: "Instead of this Q1, Q2, 1,2,3, etc,
 * we are going to use the regular circle dots the we scrub between. Except
 * 'today' will be a 'T'"). The same 6pt circle the standings' snapshot rail
 * scrubs between, so the two scrubbers are one idiom. A day strip of Q1 Q2 1 2
 * 3 … made the reader parse ten labels to find a position; a rail of dots is
 * read at a glance, and the one thing a reader needs in words — WHICH day is
 * chosen — the bar already spells out in its right-hand slot.
 *
 * TODAY IS A "T", because it is the one day that means something before you
 * have chosen it. It takes the label's own ink, so it lights and darkens with
 * every other chip rather than needing rules of its own.
 *
 * The numbers are not lost, only unprinted: each chip's accessibility label
 * still says "Qualifying day 1" or "Day 3" with its date.
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
const DOT = 6                                       // the standings rail's circle
const FACE_ON = 'Archivo_700Bold', SIZE_ON = 15     // the chosen one, a size up

/* `right` — a node pinned at the far right of the bar, outside the sliding
   row: the schedule puts the chosen day's date there. The chips slide
   beneath it, and the centring below treats the slot as outside the
   viewport, so a centred chip is centred in the space that is actually
   visible. With no days at all the bar is just this slot. */
export function DayStrip({ days, active, onPick, right, rightWidth }) {
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
  /* WHAT EACH CHIP HAS TO HOLD, for the tightening below: a dot is DOT wide
     whatever the day is, and today's "T" is measured like any other glyph. The
     widths are all far under the loosest level's minimum, so the strip settles
     on the roomiest spacing and never needs to scroll — which is the point of
     dots, and is left to fall out of the existing machinery rather than being
     special-cased here. */
  const widths = useMemo(
    () => days.map((d, i) => (d.isToday
      ? textWidth('T', i === activeIndex ? FACE_ON : FACE, i === activeIndex ? SIZE_ON : SIZE)
      : DOT)),
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
      <View>
      <View style={s.bar} onLayout={e => setBarW(e.nativeEvent.layout.width)}>
        <Animated.View
          style={[s.row, { gap: level.gap }, slide]}
          onLayout={e => setCw(e.nativeEvent.layout.width)}
        >
          {days.map(({ date, label, isToday }) => {
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
                {/* The dot takes the ink the label would have: C.muted on the
                    bar, C.bg on the chosen chip's bright fill — so one rule
                    covers both, and a green dot can never land on green. */}
                {isToday
                  ? <Text style={[s.text, on && s.textOn]}>T</Text>
                  : <View style={[s.dot, on && s.dotOn]} />}
              </Pressable>
            )
          })}
        </Animated.View>
        {/* FIXED WHERE THE CALLER SAYS, so the rule down its left edge does not
            move as the word inside it changes (owner, 2026-09-22). Still
            measured: the chips centre themselves in what is left, and one
            onLayout serves whether the width was given or grown. */}
        {right != null && (
          <View style={[s.right, rightWidth ? { width: rightWidth } : null]}
                onLayout={e => setRightW(e.nativeEvent.layout.width)}>
            {right}
          </View>
        )}
      </View>
        {/* "SWIPE TO CYCLE DATE" SITS ON THE TOP RULE (owner, 2026-09-23), a
            caption cut into the line: the swipe is the stepper since the
            arrows went, and nothing said so. Outside the bar, whose
            overflow:hidden would clip half of it; not pressable, so a swipe
            that starts on it is still the strip's. */}
        <View style={s.legendRow} pointerEvents="none">
          {/* ON THE RULE, WITH THE RULE BROKEN FOR IT (owner, 2026-09-23):
              no backing behind the words; the strip's top line is drawn here
              as two lengths either side of them instead of as the bar's
              border, so the text sits in a gap in the middle of the line. */}
          <View style={s.legendLine} />
          <Text style={s.legend} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.6}>Swipe to cycle date</Text>
          <View style={s.legendLine} />
        </View>
      </View>
    </GestureDetector>
  )
}

const STRIP_BG = '#12262a'

const s = StyleSheet.create({
  /* The draw page's round bar, edge to edge: the screen pads its body S.lg
     a side, and a ruled bar that stopped short of the edges read as a box.
     overflow hidden — the row slides under the glass at both ends. */
  /* Centred on the bar's top edge: half the caption's line box above it. */
  legendRow: {
    position: 'absolute', left: -S.lg, right: -S.lg, top: -leading(15) / 2,
    height: leading(15), flexDirection: 'row', alignItems: 'center',
  },
  legendLine: { flex: 1, height: 1, backgroundColor: C.borderLit },
  legend: { fontFamily: 'Archivo_500Medium', fontSize: 11, lineHeight: leading(15), color: C.muted, paddingHorizontal: 6 },
  bar: {
    marginHorizontal: -S.lg,
    backgroundColor: STRIP_BG,
    // The TOP rule is drawn by the caption row (legendRow), broken for its words.
    borderBottomWidth: 1, borderColor: C.borderLit, paddingTop: 4,  // 3 + the 1pt the top border took
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
    // Centred, not right-justified: the slot is as wide as the widest word
    // the range can show, so the word it holds today sits in the middle of
    // that space rather than hugging the screen's edge (owner, 2026-09-22).
    justifyContent: 'center', alignItems: 'center',
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
  /* The standings rail's circle, to the point (standingsTools.jsx): 6pt, and
     the day's own ink rather than a colour of its own. */
  dot: { width: DOT, height: DOT, borderRadius: DOT / 2, backgroundColor: C.muted },
  dotOn: { backgroundColor: C.bg },
  text: { fontFamily: FACE, fontSize: SIZE, color: C.muted },
  textOn: { fontFamily: FACE_ON, fontSize: SIZE_ON, color: C.bg },
})
