/*
 * Swipe between rounds the way the site does: a PULL, not a page-flip.
 *
 * Ported from TournamentDraw.jsx (the gesture) and CombinedView.jsx (the
 * geometry), constants and all. A horizontal drag pulls the next round in by
 * the fraction of one round the finger has travelled, and THE ROW UNDER THE
 * FINGER STAYS UNDER THE FINGER: the match you were pointing at is the match
 * you are still pointing at when its successor arrives. Release snaps to
 * whichever end is nearer and only then commits the round change.
 *
 * THE ANCHOR IS THE WHOLE POINT. The finger's position becomes a fractional
 * index into the current round's row centres — say 3.4 rows down. Its
 * counterpart in the incoming round is that index mapped through the bracket
 * (two feeders per successor), and every frame the scroll is rewritten so the
 * interpolation between the two sits exactly where the finger is.
 *
 * Built-ins only — PanResponder, Animated, ScrollView.scrollTo — so it ships
 * over Metro to the existing development build without a native rebuild.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Animated, PanResponder, ScrollView, StyleSheet, View } from 'react-native'

// The site's numbers. See the comments on each in TournamentDraw.jsx.
const SWIPE_H_RATIO = 1.5     // clearly horizontal, or it is a scroll
const SWIPE_AXIS_LOCK_PX = 8  // decide the axis this early, before native panning wins
const SWIPE_TRAVEL_PX = 150   // one whole round; release rounds to the nearest
const SETTLE_MS = 220

/* Fractional position of y among a column's row centres. */
function fracIndex(centres, y) {
  const n = centres.length
  if (!n) return 0
  if (y <= centres[0]) return 0
  if (y >= centres[n - 1]) return n - 1
  let i = 0
  while (i < n - 1 && centres[i + 1] < y) i++
  const a = centres[i], b = centres[i + 1]
  return i + (b > a ? (y - a) / (b - a) : 0)
}

function atIndex(centres, idx) {
  const n = centres.length
  if (!n) return 0
  const i = Math.max(0, Math.min(n - 1, Math.floor(idx)))
  const j = Math.min(n - 1, i + 1)
  return centres[i] + (centres[j] - centres[i]) * (idx - i)
}

/* Where a row index lands in the neighbouring round. Two feeders share one
   successor; their MIDPOINT (2k + 0.5) maps exactly onto it, and each feeder
   lands a quarter-row either side. Going back is the inverse. */
const forwardIdx = idx => (idx - 0.5) / 2
const backwardIdx = idx => idx * 2 + 0.5

export function RoundScrub({ rounds, active, onCommit, renderRow, columnStyle }) {
  const cur = Math.max(0, rounds.findIndex(([n]) => n === active))
  const [dir, setDir] = useState(0)          // +1 pulling a later round in, -1 earlier, 0 idle
  const [width, setWidth] = useState(0)
  const t = useRef(new Animated.Value(0)).current
  const tNow = useRef(0)                     // last value written to t — no private __getValue
  const scrollRef = useRef(null)
  const scrollY = useRef(0)
  const viewportTop = useRef(0)
  // roundNumber -> Map(matchId -> centreY), measured as rows lay out.
  const centresRef = useRef(new Map())
  const g = useRef(null)                     // the in-flight gesture
  const claim = useRef({ dir: 1 })             // set at capture, read at grant
  const dirRef = useRef(0)
  useEffect(() => { dirRef.current = dir }, [dir])

  const canPage = useCallback(
    d => (d > 0 ? cur + 1 < rounds.length : cur > 0),
    [cur, rounds.length],
  )

  const centresOf = useCallback(roundIdx => {
    const r = rounds[roundIdx]
    if (!r) return []
    const map = centresRef.current.get(r[0])
    if (!map) return []
    const out = []
    for (const m of r[1]) {
      const c = map.get(m.id)
      if (c == null) return []                 // not all laid out yet: no anchor this frame
      out.push(c)
    }
    return out
  }, [rounds])

  /* One scroll write per value of t: the interpolated anchor, minus where the
     finger is in the viewport. Missing measurements simply skip the frame. */
  const holdAnchor = useCallback(v => {
    const s = g.current
    if (!s || !scrollRef.current) return
    const cA = centresOf(cur), cB = centresOf(cur + s.dir)
    if (!cA.length || !cB.length) return
    if (s.idx == null) s.idx = fracIndex(cA, s.contentY)
    const ya = atIndex(cA, s.idx)
    const yb = atIndex(cB, s.dir > 0 ? forwardIdx(s.idx) : backwardIdx(s.idx))
    const y = Math.max(0, ya + (yb - ya) * v - s.localY)
    scrollRef.current.scrollTo({ y, animated: false })
  }, [centresOf, cur])

  useEffect(() => {
    const id = t.addListener(({ value }) => holdAnchor(value))
    return () => t.removeListener(id)
  }, [t, holdAnchor])

  const wrapRef = useRef(null)
  const pan = useMemo(() => PanResponder.create({
    // Capture — so a horizontal drag is ours before the ScrollView can take
    // it. Vertical falls through untouched: that is the ScrollView's.
    onMoveShouldSetPanResponderCapture: (_e, gs) => {
      if (dirRef.current !== 0) return false
      const ax = Math.abs(gs.dx), ay = Math.abs(gs.dy)
      if (Math.max(ax, ay) < SWIPE_AXIS_LOCK_PX) return false
      if (!(ax > ay * SWIPE_H_RATIO)) return false
      // Nothing that way? Leave the gesture alone rather than rubber-banding.
      const d = gs.dx < 0 ? 1 : -1
      if (!canPage(d)) return false
      /* DIRECTION AND ORIGIN ARE DECIDED HERE, not in grant. By the time the
         grant callback runs, RN has reset gestureState.dx to 0 — it counts
         from the moment we became responder — so a direction read there was
         always "backward" and every pull clamped to nothing. This is the
         only callback that sees the travel that earned the gesture. */
      claim.current = { dir: d }
      return true
    },
    onPanResponderGrant: (e) => {
      const { dir: d } = claim.current
      /* THE ORIGIN IS 0 HERE, NOT THE CAPTURE-TIME dx. RN restarts
         gestureState.dx from zero the moment we become responder, so the
         moves that follow are already measured from recognition — which is
         the site's "zero the origin at the instant of recognition", for free.
         Subtracting the capture dx (−16) on top of that drove every t negative
         and the pull clamped to nothing. The anchor still comes from where the
         finger STARTED, via pageY. */
      const localY = e.nativeEvent.pageY - viewportTop.current
      g.current = { dir: d, originDx: 0, localY, contentY: scrollY.current + localY, idx: null }
      setDir(d)
      tNow.current = 0
      t.setValue(0)
    },
    onPanResponderMove: (_e, gs) => {
      const s = g.current
      if (!s) return
      const v = Math.max(0, Math.min(1, (s.dir * -(gs.dx - s.originDx)) / SWIPE_TRAVEL_PX))
      tNow.current = v
      t.setValue(v)
    },
    onPanResponderRelease: () => finish(),
    onPanResponderTerminate: () => finish(),
    onPanResponderTerminationRequest: () => false,
  }), [canPage, t]) // eslint-disable-line react-hooks/exhaustive-deps

  function finish() {
    const s = g.current
    if (!s) return
    const target = tNow.current >= 0.5 ? 1 : 0
    Animated.timing(t, { toValue: target, duration: SETTLE_MS, useNativeDriver: false })
      .start(({ finished }) => {
        if (!finished) return
        holdAnchor(target)
        const d = s.dir
        g.current = null
        // Commit and reset together: the committed round draws its rows at
        // exactly the values t=1 was showing, so the frame is identical.
        if (target === 1) onCommit(rounds[cur + d][0])
        setDir(0)
        tNow.current = 0
        t.setValue(0)
      })
  }

  const measure = useCallback((roundNum, matchId) => e => {
    const { y, height } = e.nativeEvent.layout
    let map = centresRef.current.get(roundNum)
    if (!map) { map = new Map(); centresRef.current.set(roundNum, map) }
    map.set(matchId, y + height / 2)
  }, [])

  const column = roundIdx => {
    const r = rounds[roundIdx]
    if (!r) return <View style={{ width }} />
    const [num, matches] = r
    return (
      <View key={num} style={[{ width }, columnStyle]}>
        {matches.map(m => (
          <View key={m.id} onLayout={measure(num, m.id)} collapsable={false}>
            {renderRow(m)}
          </View>
        ))}
      </View>
    )
  }

  // Current column at x=0. The incoming one sits to the right for a pull
  // forward and to the left for a pull back; the whole strip translates.
  const cols = dir > 0 ? [column(cur), column(cur + 1)]
             : dir < 0 ? [column(cur - 1), column(cur)]
             : [column(cur)]
  const base = dir < 0 ? -width : 0
  const translateX = Animated.add(base, Animated.multiply(t, -dir * width))

  return (
    <View
      ref={wrapRef}
      style={s.wrap}
      onLayout={e => {
        setWidth(e.nativeEvent.layout.width)
        wrapRef.current?.measureInWindow?.((_x, y) => { viewportTop.current = y })
      }}
      {...pan.panHandlers}
    >
      <ScrollView
        ref={scrollRef}
        showsVerticalScrollIndicator={false}
        scrollEventThrottle={16}
        onScroll={e => { scrollY.current = e.nativeEvent.contentOffset.y }}
      >
        <Animated.View style={[s.strip, { width: width * cols.length, transform: [{ translateX }] }]}>
          {cols}
        </Animated.View>
      </ScrollView>
    </View>
  )
}

const s = StyleSheet.create({
  wrap: { flex: 1, overflow: 'hidden', touchAction: 'pan-y' },
  strip: { flexDirection: 'row', alignItems: 'flex-start' },
})
