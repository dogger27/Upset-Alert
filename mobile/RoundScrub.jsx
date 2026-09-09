/*
 * Scrub between rounds: a PULL that telescopes the bracket around the finger.
 *
 * The site's fluid round scrub (TournamentDraw.jsx supplies the gesture,
 * CombinedView.jsx the geometry), rebuilt for one round per screen and moved
 * off the JavaScript thread entirely. A sideways drag pulls the next round in
 * by the fraction of one round the finger has travelled; the outgoing round's
 * match groups CONDENSE, each pair closing onto the group they feed, while the
 * incoming round's groups arrive spread over the pairs that feed them and
 * CONTRACT into place — so the bracket appears to fold up around the finger
 * going forward and unfold going back — and THE ROW UNDER THE FINGER STAYS
 * UNDER THE FINGER. Release lands on a round and only then does React hear of
 * it. The arithmetic is in scrubGeometry.js, with its tests.
 *
 * WHY REANIMATED AND GESTURE HANDLER. The first version of this (PanResponder,
 * Animated, ScrollView.scrollTo) crossed the bridge twice on every frame: a JS
 * move handler wrote an Animated.Value, a listener turned it into a scrollTo,
 * and any JS work — a live-score refetch re-rendering sixty match groups —
 * showed up as the bracket stalling under a moving finger. Here the pan is
 * recognised natively, every frame is a worklet on the UI thread (the
 * position `pos`, the anchored offset `viewY`, one transform per row, one
 * for the strip), and React renders exactly twice per gesture: once if the
 * incoming round's column is not mounted yet, once to commit the landing.
 *
 * THERE IS NO SCROLL VIEW. Vertical position is `viewY`, a shared value: a
 * vertical pan drags it, a decay flings it, a pull sets it to hold the
 * anchor, and the strip is translated by minus it. One mechanism, so a
 * landing has nothing to hand over. The first build put the columns in a
 * ScrollView and scrolled it once, on landing, to where the pull's
 * translation had the content — the same pixels, by every number the UI
 * thread could log — and the screen still flashed to the top of the round
 * for a frame on every release in the early rounds (owner, 2026-09-09).
 * Nine reorderings of the scroll, the translate and the commit later, a
 * landing with the scrollTo simply left out did not flash: React Native's
 * scroll view draws a stale frame on a programmatic jump under the new
 * architecture, and nothing on this side of it can reach that frame. So the
 * scroll view went. What it gave up: the system scroll indicator and the
 * exact feel of UIScrollView's deceleration; Reanimated's decay with a
 * rubber band stands in for the latter.
 *
 * ONE NUMBER DRIVES EVERYTHING SIDEWAYS: `pos`, the round index as a real. A
 * column derives its whole state from pos - its own index, and a commit
 * changes none of those inputs — which is what makes the landed frame and
 * the committed frame the same pixels. Direction is not decided up front
 * either: a finger that wanders back through where it started just carries
 * pos past the integer and the other neighbour's formulas take over.
 *
 * NOTHING COMMITS PER FRAME, AND NOTHING RE-RENDERS PER SCROLL. The row
 * window follows viewY from a report sent every SCROLL_REPORT_ROWS of
 * travel, inside RoundScrubView alone, with memoised rows, so a report
 * re-renders nothing that was already there; the row registry the reaction
 * walks is a shared value, never React state. The leaving round does not
 * fade (a fade by the column's own opacity would render it offscreen every
 * frame).
 *
 * MEMORY. What is mounted is the round on screen and its two neighbours, the
 * neighbours a beat after first paint (or at once when a gesture needs them),
 * and within each only the rows near the viewport, the rest two spacers (see
 * windowsFor and Column). No texture is pinned for the strip — the site's
 * "will-change" on the whole bracket is what killed a phone renderer — and
 * nothing rasterises off-screen; the transforms composite.
 *
 * Two pieces: useRoundScrub() owns the gestures and the shared values; the
 * screen attaches its `pan` to the whole sheet (a scrub you have to find is
 * one nobody uses) and hands `scrub` to RoundScrubView, which renders the
 * columns under the vertical pan, and to RoundStrip, which glides its pill
 * along with pos.
 */
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { StyleSheet, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import Animated, {
  Easing, cancelAnimation, measure, useAnimatedReaction, useAnimatedRef,
  useDerivedValue, useSharedValue, withDecay, withTiming,
} from 'react-native-reanimated'
import { scheduleOnRN, scheduleOnUI } from 'react-native-worklets'
import { ScrubContext } from './scrubContext'
import {
  anchorY, boxOffset, rowIndexAt, rowInWindow, rowShift, scrollLimitAt, settleTarget,
} from './scrubGeometry'

/* Rows this far outside the viewport, in groups, are still driven: room for
   a frame of scroll and a row arriving at speed before it is seen. */
const CULL_MARGIN = 2

/* The finger's travel for one whole round, as a share of the screen: the
   bracket moves 1.35 times as far as the finger, which is the site's own
   ratio (150px of travel to a 202px column step). Release rounds to the
   nearest, or lands on a flick or a slow drag past 40px — scrubGeometry. */
const TRAVEL_RATIO = 1.35
/* The axis lock: the scrub's once the finger has gone 12pt sideways without
   8pt of drift — the site's 1.5:1 cone at its 8px lock — and the list's the
   moment it goes 8pt up or down first. Gesture Handler decides this
   natively, so neither the scrub nor the scroll ever starts by mistake and
   snaps back, which is what every PanResponder version did on the web. The
   vertical pan is the mirror image: 8pt of vertical travel claims it, 12pt
   sideways fails it. */
const AXIS_ACTIVE_X = 12
const AXIS_FAIL_Y = 8
/* Past the first or last round the pull gives a little and stops: the
   column slides and shrinks a touch, enough to say "nothing there". */
const OVERPULL = 0.2
const OVERPULL_MAX = 0.3
/* Past the top or bottom of a round the list gives this share of the
   finger's travel, then springs back on release — a scroll view's rubber
   band, by hand. */
const RUBBER = 0.35
const RUBBER_FACTOR = 0.6
// The site's landing: long enough to read as deceleration, short enough that
// a decisive flick still feels immediate. Same curve.
export const SETTLE_MS = 220
const SETTLE = { duration: SETTLE_MS, easing: Easing.bezier(0.22, 0.61, 0.36, 1) }
// Mount the neighbouring rounds this long after the round on screen has
// painted, so opening a draw never waits on three columns.
const WARM_MS = 250

/* ONLY THE ROWS NEAR THE VIEWPORT ARE MOUNTED; the rest of a column is two
   spacers of the right size, so the column keeps its height and every row
   its place. A draw's early rounds are a hundred groups across three
   columns, a few thousand native views, and every one of them was in the
   tree whether it could be seen or not. Mounted now: the rows in view plus
   REST_MARGIN either side; in the neighbouring rounds, the rows those feed
   or are fed by, since a pull shows exactly those; and once a pull has
   begun, PULL_MARGIN rows either side of the finger's row and their
   counterparts — enough for the whole pull, decided once at its start. The
   window follows viewY from a report sent every SCROLL_REPORT_ROWS of
   travel; a row it has not reached yet is blank for a beat, never wrong. */
const REST_MARGIN = 6
const PULL_MARGIN = 16
const SCROLL_REPORT_ROWS = 0.75

function windowsFor({ y, anchor }, vh, geo, rounds, activeIdx, warm) {
  const out = {}
  const add = (ri, lo, hi) => {
    const r = rounds[ri]
    if (!r) return
    const c = [Math.max(0, lo), Math.min(r[1].length - 1, hi)]
    const cur = out[ri]
    out[ri] = cur ? [Math.min(cur[0], c[0]), Math.max(cur[1], c[1])] : c
  }
  const vis0 = Math.floor((y - geo.P) / geo.G)
  const vis1 = Math.ceil((y + vh - geo.P) / geo.G)
  add(activeIdx, vis0 - REST_MARGIN, vis1 + REST_MARGIN)
  if (warm) {
    add(activeIdx + 1, Math.floor(vis0 / 2) - REST_MARGIN, Math.ceil(vis1 / 2) + REST_MARGIN)
    add(activeIdx - 1, 2 * vis0 - REST_MARGIN, 2 * vis1 + 1 + REST_MARGIN)
  }
  if (anchor) {
    const c = Math.round(anchor.idx)
    add(anchor.ri, c - PULL_MARGIN, c + PULL_MARGIN)
    add(anchor.ri + 1, Math.floor(c / 2) - PULL_MARGIN, Math.ceil(c / 2) + PULL_MARGIN)
    add(anchor.ri - 1, 2 * c - PULL_MARGIN, 2 * c + 1 + PULL_MARGIN)
  }
  return out
}

export function useRoundScrub({ rounds, active, onCommit, rowHeight, rowGap, padTop, padBottom, boxPitch = 0 }) {
  // Half the distance between a settled group's two boxes: the offset a
  // condensing row lands at either side of its successor's centre.
  const e = boxPitch / 2
  const activeIdx = Math.max(0, rounds.findIndex(([n]) => n === active))
  // The viewport, for measure(): where a finger is within the list.
  const wrapRef = useAnimatedRef()
  /* THE VERTICAL POSITION: the content offset at the top of the viewport.
     The vertical pan writes it, a fling decays it, a pull sets it each frame
     to hold the anchor, and the strip is translated by minus it. Nothing
     else moves the list up or down. */
  const viewY = useSharedValue(0)
  const reportedY = useSharedValue(0)
  const vStart = useSharedValue(0)
  const vDragging = useSharedValue(false)

  const pos = useSharedValue(activeIdx)
  // The round the current gesture (or glide) left from.
  const r0 = useSharedValue(activeIdx)
  // True from the first frame of a pull until it has landed.
  const scrubbing = useSharedValue(false)
  const dragging = useSharedValue(false)
  const originX = useSharedValue(0)
  const dragPx = useSharedValue(0)
  const anchor = useSharedValue({ idx: 0, localY: 0, r0: activeIdx })
  // The draw's shape: how many rounds, how many groups in each.
  const meta = useSharedValue({ count: rounds.length, rows: rounds.map(([, ms]) => ms.length) })
  // Measured as the columns lay out; the constants stand in until then.
  const geo = useSharedValue({ P: padTop, H: rowHeight, G: rowHeight + rowGap })
  const geoRef = useRef({ P: padTop, H: rowHeight, G: rowHeight + rowGap })
  const heights = useSharedValue([])
  const widthSV = useSharedValue(0)
  const viewportH = useSharedValue(0)
  const [width, setWidth] = useState(0)
  const [warm, setWarm] = useState(false)

  const roundsRef = useRef(rounds)
  const onCommitRef = useRef(onCommit)
  roundsRef.current = rounds
  onCommitRef.current = onCommit
  useEffect(() => {
    meta.value = { count: rounds.length, rows: rounds.map(([, ms]) => ms.length) }
  }, [rounds, meta])
  // A different draw: its columns are not this tall.
  const drawKey = rounds.map(([n]) => n).join(',')
  useEffect(() => { heights.value = [] }, [drawKey, heights])
  useEffect(() => {
    if (warm || rounds.length < 2) return
    const t = setTimeout(() => setWarm(true), WARM_MS)
    return () => clearTimeout(t)
  }, [warm, rounds.length])

  /* EVERY ROW'S SHIFT AND STRETCH ARE WRITTEN BY ONE WORKLET A FRAME, not read
     by a hundred. A row registers two shared values — its translateY and its
     stretch — and a single reaction on pos walks the registry, writes the rows
     inside the viewport (plus a margin) their true values and every other row
     its settled ones. A row's own style reads only its own value, so a row
     nothing was written to costs nothing. THE REGISTRY IS A SHARED VALUE, not
     React state: rows come and go with the window on every scroll, and a
     re-render for each would be the very cost this exists to remove. */
  const rowsRef = useRef(new Map())
  const rowsSV = useSharedValue([])
  const rowsFlush = useRef(0)
  const flushRows = useCallback(() => {
    rowsFlush.current = 0
    const list = [...rowsRef.current.values()]
    scheduleOnUI(() => { 'worklet'; rowsSV.value = list })
  }, [rowsSV])
  const registerRow = useCallback((key, entry) => {
    rowsRef.current.set(key, entry)
    if (!rowsFlush.current) rowsFlush.current = setTimeout(flushRows, 0)
  }, [flushRows])
  const unregisterRow = useCallback((key) => {
    rowsRef.current.delete(key)
    if (!rowsFlush.current) rowsFlush.current = setTimeout(flushRows, 0)
  }, [flushRows])

  /* What RoundScrubView listens to, to move its row window: the scroll, a
     pull beginning (widen around the finger), a pull landing. Plain
     listeners, so nothing here re-renders the screen this hook lives in. */
  const listeners = useRef(new Set())
  const subscribe = useCallback((fn) => {
    listeners.current.add(fn)
    return () => listeners.current.delete(fn)
  }, [])
  const emit = useCallback((ev) => { for (const fn of listeners.current) fn(ev) }, [])

  /* Plain JS, reached from the UI thread by scheduleOnRN. Stable, and reads
     the live props through refs: the gesture is created once. This is the
     React commit — it moves `active` (the round the app is on), the mounted
     row window, and the round bar's bold label. None of it changes a pixel:
     the landed round is a neighbour and already mounted, and pos and viewY
     are where they were. */
  const commit = useCallback((idx, y) => {
    setWarm(true)
    emit({ type: 'land', y })
    const r = roundsRef.current[idx]
    if (r) onCommitRef.current?.(r[0])
  }, [emit])
  const beginPull = useCallback((ri, idx) => {
    setWarm(true)
    emit({ type: 'pull', ri, idx })
  }, [emit])
  const reportScroll = useCallback((y) => { emit({ type: 'scroll', y }) }, [emit])

  // A column's estimated height, for the frame before it is measured.
  const estimate = useCallback((n) => {
    'worklet'
    const g = geo.value
    return g.P + Math.max(0, n - 1) * g.G + g.H + padBottom
  }, [geo, padBottom])

  // How far the list can go at this pos: the landed column's own at either
  // integer, a blend of the two between.
  const limitAt = useCallback((p) => {
    'worklet'
    const m = meta.value
    const lo = Math.max(0, Math.min(m.count - 1, Math.floor(p)))
    const hi = Math.max(0, Math.min(m.count - 1, Math.ceil(p)))
    const fallback = Math.max(estimate(m.rows[lo] ?? 0), estimate(m.rows[hi] ?? 0))
    return scrollLimitAt(p, heights.value, fallback, viewportH.value)
  }, [meta, heights, viewportH, estimate])

  /* Where the list should be for this pos: the anchored row's place, less
     the finger's place in the viewport, inside the limit. */
  const scrollFor = useCallback((p) => {
    'worklet'
    const a = anchor.value
    const g = geo.value
    const y = anchorY(a.idx, p - a.r0, g.P, g.H, g.G, e) - a.localY
    const lim = limitAt(p)
    return y < 0 ? 0 : y > lim ? lim : y
  }, [anchor, geo, limitAt, e])

  /* Landing. viewY is already where the pull left it; it is set once more
     for the integer, whose limit is exact (a frame earlier it was still a
     blend of two columns'), and the pull is over. Nothing scrolls. */
  const settle = useCallback((target) => {
    'worklet'
    viewY.value = scrollFor(target)
    reportedY.value = viewY.value
    scrubbing.value = false
  }, [scrollFor, viewY, reportedY, scrubbing])

  const land = useCallback((target) => {
    'worklet'
    pos.value = withTiming(target, SETTLE, (finished) => {
      if (!finished) return
      settle(target)
      scheduleOnRN(commit, target, viewY.value)
    })
  }, [pos, settle, commit, viewY])

  /* A gesture may begin while the last pull is still landing. Its landing
     is FLUSHED, not raced: pos goes straight to where it was headed, the
     list settles there, and the commit is sent now, because the previous
     scrub earned its round and dropping it loses one. (The site's 734dd31.) */
  const flushLanding = useCallback(() => {
    'worklet'
    cancelAnimation(pos)
    const cur = Math.round(pos.value)
    pos.value = cur
    if (scrubbing.value) {
      settle(cur)
      scheduleOnRN(commit, cur, viewY.value)
    }
    return cur
  }, [pos, scrubbing, settle, commit, viewY])

  const pan = useMemo(() => Gesture.Pan()
    .activeOffsetX([-AXIS_ACTIVE_X, AXIS_ACTIVE_X])
    .failOffsetY([-AXIS_FAIL_Y, AXIS_FAIL_Y])
    .onStart((ev) => {
      'worklet'
      const m = meta.value
      if (m.count < 2 || widthSV.value <= 0) return
      cancelAnimation(viewY)
      const cur = flushLanding()
      /* THE ANCHOR. The finger's height within the list becomes a fractional
         group index in the round it is on; that index is what is held.
         measure() gives the list's place on screen on the UI thread, so the
         first frame already has it. */
      const vp = measure(wrapRef)
      const localY = vp ? ev.absoluteY - vp.pageY : viewportH.value / 2
      const g = geo.value
      anchor.value = {
        idx: rowIndexAt(viewY.value + localY, g.P, g.H, g.G, m.rows[cur] ?? 0),
        localY, r0: cur,
      }
      r0.value = cur
      /* The origin is where the finger is NOW, at recognition, not where it
         landed: the axis lock spent AXIS_ACTIVE_X of travel deciding, and
         counting that would start the pull with a jump (the site's 0d7ec8d,
         and the app's own PanResponder version had the mirror-image bug). */
      originX.value = ev.translationX
      dragPx.value = 0
      scrubbing.value = true
      dragging.value = true
      scheduleOnRN(beginPull, cur, anchor.value.idx)
    })
    .onUpdate((ev) => {
      'worklet'
      if (!dragging.value) return
      const a = anchor.value
      const m = meta.value
      const dx = ev.translationX - originX.value
      dragPx.value = dx
      // Dragging LEFT pulls later rounds in.
      let p = a.r0 - dx / (widthSV.value / TRAVEL_RATIO)
      // One round per swipe, and the draw's ends give a little, then hold.
      const lo = Math.max(0, a.r0 - 1), hi = Math.min(m.count - 1, a.r0 + 1)
      if (p < lo) p = lo - Math.min(OVERPULL_MAX, (lo - p) * OVERPULL)
      else if (p > hi) p = hi + Math.min(OVERPULL_MAX, (p - hi) * OVERPULL)
      pos.value = p
    })
    .onEnd((ev) => {
      'worklet'
      if (!dragging.value) return
      dragging.value = false
      const m = meta.value
      land(settleTarget(pos.value, anchor.value.r0, ev.velocityX, dragPx.value, 0, m.count - 1))
    })
    .onFinalize(() => {
      'worklet'
      // Cancelled mid-pull (a system gesture, a call): land as if released still.
      if (!dragging.value) return
      dragging.value = false
      const m = meta.value
      land(settleTarget(pos.value, anchor.value.r0, 0, dragPx.value, 0, m.count - 1))
    }), [meta, widthSV, pos, viewY, flushLanding, wrapRef, viewportH, geo,
         anchor, r0, originX, dragPx, dragging, scrubbing, beginPull, land])

  /* THE LIST'S OWN SCROLL: a vertical pan on viewY, with a rubber band past
     either end and a decay on release. A touch anywhere stops a fling, as it
     would a scroll view's. Only the round on screen scrolls; a pull that
     has not landed is flushed first, as the scrub does. */
  const vpan = useMemo(() => Gesture.Pan()
    .activeOffsetY([-AXIS_FAIL_Y, AXIS_FAIL_Y])
    .failOffsetX([-AXIS_ACTIVE_X, AXIS_ACTIVE_X])
    .onTouchesDown(() => {
      'worklet'
      cancelAnimation(viewY)
    })
    .onStart(() => {
      'worklet'
      cancelAnimation(viewY)
      flushLanding()
      vStart.value = viewY.value
      vDragging.value = true
    })
    .onUpdate((ev) => {
      'worklet'
      if (!vDragging.value) return
      let y = vStart.value - ev.translationY
      const lim = limitAt(pos.value)
      if (y < 0) y *= RUBBER
      else if (y > lim) y = lim + (y - lim) * RUBBER
      viewY.value = y
    })
    .onEnd((ev) => {
      'worklet'
      if (!vDragging.value) return
      vDragging.value = false
      const lim = limitAt(pos.value)
      viewY.value = withDecay({
        velocity: -ev.velocityY, clamp: [0, lim], rubberBandEffect: true, rubberBandFactor: RUBBER_FACTOR,
      })
    })
    .onFinalize(() => {
      'worklet'
      if (!vDragging.value) return
      vDragging.value = false
      const lim = limitAt(pos.value)
      viewY.value = withDecay({ velocity: 0, clamp: [0, lim], rubberBandEffect: true, rubberBandFactor: RUBBER_FACTOR })
    }), [viewY, vStart, vDragging, flushLanding, limitAt, pos])

  /* viewY moved: tell the view every SCROLL_REPORT_ROWS of travel, so the
     row window follows. Not during a pull — the pull widened the window
     around the finger when it began — and the landing reports itself. */
  useAnimatedReaction(() => viewY.value, (y) => {
    if (scrubbing.value) return
    if (Math.abs(y - reportedY.value) >= SCROLL_REPORT_ROWS * geo.value.G) {
      reportedY.value = y
      scheduleOnRN(reportScroll, y)
    }
  }, [reportScroll])

  /* A column measured shorter than the list has scrolled (a different
     draw's, or the first estimate too tall): back inside the limit, at
     rest only — a pull clamps itself and a drag has its rubber band. */
  useAnimatedReaction(() => [heights.value, viewportH.value], () => {
    if (scrubbing.value || vDragging.value) return
    const lim = limitAt(Math.round(pos.value))
    if (viewY.value > lim) viewY.value = lim
  }, [limitAt])

  /* pos moved: hold the anchor, then drive the rows on screen. One reaction,
     in this order, every frame of a pull. */
  useAnimatedReaction(() => pos.value, (p) => {
    if (scrubbing.value) viewY.value = scrollFor(p)
    const g = geo.value
    const top = viewY.value - CULL_MARGIN * g.H
    const bottom = viewY.value + viewportH.value + CULL_MARGIN * g.H
    const rows = rowsSV.value
    for (let k = 0; k < rows.length; k++) {
      const r = rows[k]
      const s = p - r.ri
      let sh = 0, st = 0
      // In the window by where the pull has put it OR where it sits settled:
      // a row frozen settled while really moved off screen would be drawn
      // where it is not.
      if (rowInWindow(r.i, s, g.P, g.H, g.G, e, top, bottom)) {
        sh = rowShift(r.i, s, g.G, e)
        st = boxOffset(s, g.G, e) - e
      }
      if (r.shift.value !== sh) r.shift.value = sh
      if (r.stretch.value !== st) r.stretch.value = st
    }
  }, [scrollFor, e])

  /* The round the screen asks for, arriving from outside a gesture — a tap
     on the strip, the live round moving on, a different draw. A neighbour
     glides there the way a pull would, anchored on the middle of the
     viewport; anything further, or a draw that just changed, is simply
     shown. A pull's own commit arrives here too and finds nothing to do. */
  const prevKey = useRef(drawKey)
  useEffect(() => {
    const idx = activeIdx
    const changedDraw = prevKey.current !== drawKey
    prevKey.current = drawKey
    scheduleOnUI(() => {
      'worklet'
      const cur = pos.value
      if (cur === idx) return
      if (dragging.value) return
      const from = Math.round(cur)
      if (changedDraw || cur !== from || Math.abs(idx - from) !== 1) {
        cancelAnimation(pos)
        if (scrubbing.value) settle(Math.round(pos.value))
        pos.value = idx
        r0.value = idx
        if (changedDraw) viewY.value = 0
        return
      }
      cancelAnimation(viewY)
      const g = geo.value
      const localY = viewportH.value / 2
      anchor.value = {
        idx: rowIndexAt(viewY.value + localY, g.P, g.H, g.G, meta.value.rows[from] ?? 0),
        localY, r0: from,
      }
      r0.value = from
      scrubbing.value = true
      pos.value = withTiming(idx, SETTLE, (finished) => {
        if (!finished) return
        settle(idx)
        scheduleOnRN(reportScroll, viewY.value)
      })
    })
  }, [activeIdx, drawKey, pos, dragging, scrubbing, settle, r0, geo, viewportH, anchor, viewY, meta, reportScroll])

  const onWrapLayout = useCallback((ev) => {
    const { width: w, height: h } = ev.nativeEvent.layout
    widthSV.value = w
    viewportH.value = h
    setWidth(w)
    emit({ type: 'viewport', vh: h })
  }, [widthSV, viewportH, emit])

  /* Any mounted row measures the column: its height is every group's, its
     pitch is that plus the gap, and its top is P + i × pitch. */
  const onRowLayout = useCallback((ri, i, ev) => {
    const { y, height } = ev.nativeEvent.layout
    const G = height + rowGap
    const P = y - i * G
    const g = geoRef.current
    if (Math.abs(g.P - P) < 0.5 && Math.abs(g.H - height) < 0.5 && Math.abs(g.G - G) < 0.5) return
    geoRef.current = { P, H: height, G }
    scheduleOnUI(() => { 'worklet'; geo.value = { P, H: height, G } })
    emit({ type: 'geo', geo: geoRef.current })
  }, [geo, rowGap, emit])
  const onColumnLayout = useCallback((ri, ev) => {
    const h = ev.nativeEvent.layout.height
    scheduleOnUI(() => {
      'worklet'
      const next = heights.value.slice()
      if (Math.abs((next[ri] || 0) - h) < 0.5) return
      next[ri] = h
      heights.value = next
    })
  }, [heights])

  const scrub = useMemo(() => ({
    pos, r0, viewY, vpan, wrapRef, widthSV, activeIdx, width, warm,
    rowHeight, rowGap, rounds, subscribe, geoRef,
    onWrapLayout, onRowLayout, onColumnLayout, registerRow, unregisterRow,
  }), [pos, r0, viewY, vpan, wrapRef, widthSV, activeIdx, width, warm,
       rowHeight, rowGap, rounds, subscribe,
       onWrapLayout, onRowLayout, onColumnLayout, registerRow, unregisterRow])

  return { pan, scrub }
}

/* One match group's slot. Its whole part in the scrub is a translateY —
   condensing onto its successor as its column leaves to the left, spreading
   over its feeders as it waits on the right — and a stretch for the group
   inside. Both are shared values WRITTEN by the scrub's one reaction; this
   reads its own and nothing else. MEMOISED on the match and the renderer,
   so the window moving on a scroll re-renders only the rows that entered. */
const Row = memo(function Row({ ri, i, m, renderRow, scrub }) {
  const { onRowLayout, registerRow, unregisterRow } = scrub
  const shift = useSharedValue(0)
  const stretch = useSharedValue(0)
  useEffect(() => {
    const key = `${ri}:${i}`
    registerRow(key, { ri, i, shift, stretch })
    return () => unregisterRow(key)
  }, [ri, i, shift, stretch, registerRow, unregisterRow])
  // What the group inside reads to stretch or condense itself.
  const ctx = useMemo(() => ({ stretch }), [stretch])
  return (
    <Animated.View style={{ transform: [{ translateY: shift }] }} collapsable={false}
                   onLayout={ev => onRowLayout(ri, i, ev)}>
      <ScrubContext.Provider value={ctx}>{renderRow(m)}</ScrubContext.Provider>
    </Animated.View>
  )
})

/* A round's column, at its own place on the strip: index times the width,
   whatever pos is doing — which is why a commit moves nothing. NO FADE on
   the way out, either way: a leaving round just goes, and its groups piling
   onto one another as they condense is fine (owner, 2026-09-08).

   Only the rows in the window are mounted; the rest is ONE SPACER above and
   ONE below, not a blank per row, so a column mounts about a dozen views
   whatever the round's size. Each spacer stands in for its run of rows,
   pitch (a group plus the row gap) apiece, less the one gap the flex row
   adds beside it — so onColumnLayout measures the true height and every
   row keeps its place. */
function Column({ ri, num, matches, window, scrub, renderRow, columnStyle }) {
  const { width, rowHeight, rowGap, onColumnLayout } = scrub
  const [lo, hi] = window
  const count = matches.length
  const pitch = rowHeight + rowGap
  const children = []
  if (lo > 0) children.push(<View key="sp-top" style={{ height: lo * pitch - rowGap }} />)
  for (let i = lo; i <= hi && i < count; i++) {
    const m = matches[i]
    /* A slot with no match — an unplayed half of the bracket — has no id;
       the round and position make a key that exists for every row. */
    children.push(<Row key={m.id ?? `slot-${num}-${i}`} ri={ri} i={i} m={m} renderRow={renderRow} scrub={scrub} />)
  }
  if (hi < count - 1) children.push(<View key="sp-bot" style={{ height: (count - 1 - hi) * pitch - rowGap }} />)
  return (
    <View style={[s.column, { left: ri * width, width }]}>
      <View style={columnStyle} onLayout={ev => onColumnLayout(ri, ev)}>{children}</View>
    </View>
  )
}

export function RoundScrubView({ scrub, rounds, renderRow, columnStyle, style = null }) {
  const { pos, viewY, vpan, wrapRef, widthSV, activeIdx, width, warm, subscribe, geoRef, onWrapLayout } = scrub
  /* The strip carries every column, absolutely placed, and is translated:
     sideways by pos, up by viewY. It has no height of its own and needs
     none — nothing scrolls it; the wrapper clips it. */
  const stripX = useDerivedValue(() => -pos.value * widthSV.value)
  const stripY = useDerivedValue(() => -viewY.value)

  /* The row window's inputs live HERE, not in the hook the screen owns: a
     scroll report re-renders this view and its memoised rows, never the
     screen and everything on it. */
  const [view, setView] = useState({ y: 0, vh: 0, anchor: null, geo: geoRef.current })
  useEffect(() => subscribe((ev) => {
    setView(v => {
      switch (ev.type) {
        case 'scroll': return v.y === ev.y ? v : { ...v, y: ev.y }
        case 'pull': return { ...v, anchor: { ri: ev.ri, idx: ev.idx } }
        case 'land': return { ...v, y: ev.y, anchor: null }
        case 'viewport': return v.vh === ev.vh ? v : { ...v, vh: ev.vh }
        case 'geo': return { ...v, geo: ev.geo }
        default: return v
      }
    })
  }), [subscribe])
  const windows = useMemo(
    () => windowsFor(view, view.vh, view.geo, rounds, activeIdx, warm),
    [view, rounds, activeIdx, warm],
  )

  // The round on screen and, once warm, its neighbours.
  const mounted = []
  for (let ri = warm ? activeIdx - 1 : activeIdx; ri <= (warm ? activeIdx + 1 : activeIdx); ri++) {
    if (rounds[ri]) mounted.push(ri)
  }

  /* The detector's own child carries no ref: Gesture Handler reads its
     child's ref, which React 19 logs on every render. The measured viewport
     is the view inside, which fills it. */
  return (
    <GestureDetector gesture={vpan}>
      <View style={[s.wrap, style]}>
        <Animated.View ref={wrapRef} style={s.fill} onLayout={onWrapLayout} collapsable={false}>
          {width > 0 && (
            <Animated.View style={[s.strip, { transform: [{ translateX: stripX }, { translateY: stripY }] }]}>
              {mounted.map(ri => (
                <Column key={rounds[ri][0]} ri={ri} num={rounds[ri][0]} matches={rounds[ri][1]}
                        window={windows[ri] ?? [0, -1]}
                        scrub={scrub} renderRow={renderRow} columnStyle={columnStyle} />
              ))}
            </Animated.View>
          )}
        </Animated.View>
      </View>
    </GestureDetector>
  )
}

const s = StyleSheet.create({
  /* minHeight 0 is the web's: a flex item there will not shrink below its
     content unless told, and this one's content is the whole column — the
     wrapper grew to it, reported that as the viewport, and the anchor's
     limit clamped every pull to the top. Yoga never does this.
     touchAction none is the web's too: both axes are the gestures' now, so
     the browser must reserve neither — left at its default it claims every
     vertical drag for a scroll that no longer exists and cancels the pan on
     the first move. iOS ignores the style. */
  wrap: { flex: 1, minHeight: 0, overflow: 'hidden', touchAction: 'none' },
  fill: { flex: 1, minHeight: 0 },
  strip: { position: 'absolute', top: 0, left: 0, right: 0 },
  column: { position: 'absolute', top: 0 },
})
