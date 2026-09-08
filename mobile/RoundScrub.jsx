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
 * position `pos`, the anchored scrollTo, one transform per row, one per
 * column), and React renders exactly twice per gesture: once if the incoming
 * round's column is not mounted yet, once to commit the landing.
 *
 * ONE NUMBER DRIVES EVERYTHING: `pos`, the round index as a real. A column
 * derives its whole state from pos - its own index, and a commit changes none
 * of those inputs — which is what makes the landed frame and the committed
 * frame the same pixels. The site's history has three commits of "the frame
 * that flashes on release"; none of them can recur when there is nothing to
 * reset. Direction is not decided up front either: a finger that wanders back
 * through where it started just carries pos past the integer and the other
 * neighbour's formulas take over.
 *
 * MEMORY. What is mounted is the round on screen and its two neighbours, the
 * neighbours a beat after first paint (or at once when a gesture needs them),
 * and the far side unmounts as the window moves. No texture is pinned for the
 * strip — the site's "will-change" on the whole bracket is what killed a phone
 * renderer — and nothing rasterises off-screen; the transforms composite. No
 * per-frame allocation on either thread: the worklets read shared values and
 * return numbers.
 *
 * Two pieces: useRoundScrub() owns the gesture and the shared values; the
 * screen attaches its `pan` to the whole sheet (a scrub you have to find is
 * one nobody uses) and hands `scrub` to RoundScrubView, which renders the
 * columns, and to RoundStrip, which glides its pill along with pos.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { StyleSheet, View } from 'react-native'
import { Gesture } from 'react-native-gesture-handler'
import Animated, {
  Easing, cancelAnimation, measure, scrollTo, useAnimatedReaction, useAnimatedRef,
  useAnimatedScrollHandler, useAnimatedStyle, useSharedValue, withTiming,
} from 'react-native-reanimated'
import { scheduleOnRN, scheduleOnUI } from 'react-native-worklets'
import { ScrubContext } from './scrubContext'
import {
  anchorY, boxOffset, contentHeightAt, rowIndexAt, rowInWindow, rowShift, scrollLimitAt, settleTarget,
} from './scrubGeometry'

/* Rows this far outside the viewport, in groups, are still driven: room for
   a frame of scroll and a row arriving at speed before it is seen. */
const CULL_MARGIN = 2

/* The finger's travel for one whole round, as a share of the screen: the
   bracket moves 1.35 times as far as the finger, which is the site's own
   ratio (150px of travel to a 202px column step). Release rounds to the
   nearest, or lands on a flick or a slow drag past 40px — scrubGeometry. */
const TRAVEL_RATIO = 1.35
/* The axis lock: ours once the finger has gone 12pt sideways without 8pt
   of drift — the site's 1.5:1 cone at its 8px lock — and the list's the
   moment it goes 8pt up or down first. Gesture Handler decides this
   natively, so neither the scrub nor the scroll ever starts by mistake and
   snaps back, which is what every PanResponder version did on the web. */
const AXIS_ACTIVE_X = 12
const AXIS_FAIL_Y = 8
/* Past the first or last round the pull gives a little and stops: the
   column slides and shrinks a touch, enough to say "nothing there". */
const OVERPULL = 0.2
const OVERPULL_MAX = 0.3
// The site's landing: long enough to read as deceleration, short enough that
// a decisive flick still feels immediate. Same curve.
export const SETTLE_MS = 220
const SETTLE = { duration: SETTLE_MS, easing: Easing.bezier(0.22, 0.61, 0.36, 1) }
// Mount the neighbouring rounds this long after the round on screen has
// painted, so opening a draw never waits on three columns.
const WARM_MS = 250

/* ONLY THE ROWS NEAR THE VIEWPORT ARE MOUNTED; the rest of a column is
   placeholders of the group's height, so the column keeps its size and the
   scroll its range. A draw's early rounds are a hundred groups across three
   columns, a few thousand native views, and every one of them was in the
   scroll view's tree whether it could be seen or not: scrolling R128 lagged
   and a pull there shook (owner, 2026-09-08). Mounted now: the rows in view
   plus REST_MARGIN either side; in the neighbouring rounds, the rows those
   feed or are fed by, since a pull shows exactly those; and once a pull has
   begun, PULL_MARGIN rows either side of the finger's row and their
   counterparts — enough for the whole pull, decided once at its start. The
   window follows the scroll from a throttled report; a row it has not
   reached yet is a blank of the right size for a beat, never a wrong one. */
const REST_MARGIN = 6
const PULL_MARGIN = 16
// The window follows the scroll once it has moved this many rows since the
// last report — by distance, not by counting events, so a single programmatic
// jump or a short flick moves it too.
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
  const scrollRef = useAnimatedRef()
  /* The scroll offset, taken straight off the scroll events on the UI thread.
     (useScrollOffset binds to the ref, and this ref attaches after the first
     render; a hook that missed it would read 0 for ever — and an anchor that
     reads 0 puts the finger's row wherever the top of the list is.) */
  const scrollY = useSharedValue(0)
  const reportedY = useSharedValue(0)

  const pos = useSharedValue(activeIdx)
  // The round the current gesture (or glide) left from: the one that fades.
  const r0 = useSharedValue(activeIdx)
  // True from the first frame of a pull until it has landed: the anchor owns
  // the scroll for exactly that long.
  const scrubbing = useSharedValue(false)
  const dragging = useSharedValue(false)
  const originX = useSharedValue(0)
  const dragPx = useSharedValue(0)
  const anchor = useSharedValue({ idx: 0, localY: 0, r0: activeIdx })
  // The draw's shape: how many rounds, how many groups in each.
  const meta = useSharedValue({ count: rounds.length, rows: rounds.map(([, ms]) => ms.length) })
  // Measured as the columns lay out; the constants stand in until then.
  const geo = useSharedValue({ P: padTop, H: rowHeight, G: rowHeight + rowGap })
  const heights = useSharedValue([])
  const widthSV = useSharedValue(0)
  const viewportH = useSharedValue(0)
  const [width, setWidth] = useState(0)
  const [vh, setVh] = useState(0)
  const [warm, setWarm] = useState(false)
  // What the row windows are computed from on the JS side: the last reported
  // scroll offset, and the finger's row while a pull is in flight.
  const [view, setView] = useState({ y: 0, anchor: null })
  const geoRef = useRef({ P: padTop, H: rowHeight, G: rowHeight + rowGap })

  /* EVERY ROW'S SHIFT AND STRETCH ARE WRITTEN BY ONE WORKLET A FRAME, not read
     by a hundred. The first version gave each row a worklet reading pos, and
     each group four more: a hundred and twelve groups on the way to R128 was
     five hundred worklets evaluated every frame of a pull, which shook, and
     gating them on the scroll offset made a plain scroll evaluate all five
     hundred too. Now a row registers two shared values — its translateY and
     its stretch — and a single reaction on pos walks the registry, writes the
     rows inside the viewport (plus a margin) their true values and every
     other row its settled ones. A row's own style reads only its own value,
     so a row nothing was written to costs nothing, scrolling touches nothing,
     and the dozen groups on screen are the whole per-frame bill. */
  const rowsRef = useRef(new Map())
  const [rowsVersion, setRowsVersion] = useState(0)
  const registerRow = useCallback((key, entry) => {
    rowsRef.current.set(key, entry)
    setRowsVersion(v => v + 1)
  }, [])
  const unregisterRow = useCallback((key) => {
    rowsRef.current.delete(key)
    setRowsVersion(v => v + 1)
  }, [])
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const rowList = useMemo(() => [...rowsRef.current.values()], [rowsVersion])

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

  /* Plain JS, reached from the UI thread by scheduleOnRN. Stable, and reads
     the live props through refs: the gesture is created once. */
  const commit = useCallback((idx, y) => {
    setWarm(true)
    setView({ y, anchor: null })
    const r = roundsRef.current[idx]
    if (r) onCommitRef.current?.(r[0])
  }, [])
  const beginPull = useCallback((ri, idx) => {
    setWarm(true)
    setView(v => ({ ...v, anchor: { ri, idx } }))
  }, [])
  const reportScroll = useCallback((y) => {
    setView(v => (v.y === y ? v : { ...v, y }))
  }, [])
  const onScroll = useAnimatedScrollHandler({
    onScroll: (ev) => {
      const y = ev.contentOffset.y
      scrollY.value = y
      if (Math.abs(y - reportedY.value) >= SCROLL_REPORT_ROWS * geo.value.G) {
        reportedY.value = y
        scheduleOnRN(reportScroll, y)
      }
    },
    onMomentumEnd: (ev) => { reportedY.value = ev.contentOffset.y; scheduleOnRN(reportScroll, ev.contentOffset.y) },
    onEndDrag: (ev) => { reportedY.value = ev.contentOffset.y; scheduleOnRN(reportScroll, ev.contentOffset.y) },
  }, [reportScroll])

  // A column's estimated height, for the frame before it is measured.
  const estimate = useCallback((n) => {
    'worklet'
    const g = geo.value
    return g.P + Math.max(0, n - 1) * g.G + g.H + padBottom
  }, [geo, padBottom])

  const land = useCallback((target) => {
    'worklet'
    pos.value = withTiming(target, SETTLE, (finished) => {
      if (!finished) return
      scrubbing.value = false
      reportedY.value = scrollY.value
      scheduleOnRN(commit, target, scrollY.value)
    })
  }, [pos, scrubbing, commit, scrollY, reportedY])

  const pan = useMemo(() => Gesture.Pan()
    .activeOffsetX([-AXIS_ACTIVE_X, AXIS_ACTIVE_X])
    .failOffsetY([-AXIS_FAIL_Y, AXIS_FAIL_Y])
    .onStart((e) => {
      'worklet'
      const m = meta.value
      if (m.count < 2 || widthSV.value <= 0) return
      /* A gesture may begin while the last one is still landing. Its landing
         is FLUSHED, not raced: pos goes straight to where it was headed and
         the commit is sent now, because the previous scrub earned its round
         and dropping it loses one — and because everything this gesture does
         is relative to a whole round. (The site's 734dd31.) */
      cancelAnimation(pos)
      const cur = Math.round(pos.value)
      pos.value = cur
      scheduleOnRN(commit, cur, scrollY.value)
      /* THE ANCHOR. The finger's height within the list becomes a fractional
         group index in the round it is on; that index is what is held.
         measure() gives the list's place on screen on the UI thread, so the
         first frame already has it. */
      const vp = measure(scrollRef)
      const localY = vp ? e.absoluteY - vp.pageY : viewportH.value / 2
      const g = geo.value
      anchor.value = {
        idx: rowIndexAt(scrollY.value + localY, g.P, g.H, g.G, m.rows[cur] ?? 0),
        localY, r0: cur,
      }
      r0.value = cur
      /* The origin is where the finger is NOW, at recognition, not where it
         landed: the axis lock spent AXIS_ACTIVE_X of travel deciding, and
         counting that would start the pull with a jump (the site's 0d7ec8d,
         and the app's own PanResponder version had the mirror-image bug). */
      originX.value = e.translationX
      dragPx.value = 0
      scrubbing.value = true
      dragging.value = true
      scheduleOnRN(beginPull, cur, anchor.value.idx)
    })
    .onUpdate((e) => {
      'worklet'
      if (!dragging.value) return
      const a = anchor.value
      const m = meta.value
      const dx = e.translationX - originX.value
      dragPx.value = dx
      // Dragging LEFT pulls later rounds in.
      let p = a.r0 - dx / (widthSV.value / TRAVEL_RATIO)
      // One round per swipe, and the draw's ends give a little, then hold.
      const lo = Math.max(0, a.r0 - 1), hi = Math.min(m.count - 1, a.r0 + 1)
      if (p < lo) p = lo - Math.min(OVERPULL_MAX, (lo - p) * OVERPULL)
      else if (p > hi) p = hi + Math.min(OVERPULL_MAX, (p - hi) * OVERPULL)
      pos.value = p
    })
    .onEnd((e) => {
      'worklet'
      if (!dragging.value) return
      dragging.value = false
      const m = meta.value
      land(settleTarget(pos.value, anchor.value.r0, e.velocityX, dragPx.value, 0, m.count - 1))
    })
    .onFinalize(() => {
      'worklet'
      // Cancelled mid-pull (a system gesture, a call): land as if released still.
      if (!dragging.value) return
      dragging.value = false
      const m = meta.value
      land(settleTarget(pos.value, anchor.value.r0, 0, dragPx.value, 0, m.count - 1))
    }), [meta, widthSV, pos, commit, scrollRef, viewportH, geo, anchor, scrollY, r0, originX, dragPx, scrubbing, dragging, beginPull, land])

  useAnimatedReaction(() => pos.value, (p) => {
    const g = geo.value
    const top = scrollY.value - CULL_MARGIN * g.H
    const bottom = scrollY.value + viewportH.value + CULL_MARGIN * g.H
    for (let k = 0; k < rowList.length; k++) {
      const r = rowList[k]
      const s = p - r.ri
      let sh = 0, st = 0
      // In the window by where the scrub has put it OR where it sits settled:
      // a row frozen settled while really moved off screen would be drawn
      // where it is not.
      if (rowInWindow(r.i, s, g.P, g.H, g.G, e, top, bottom)) {
        sh = rowShift(r.i, s, g.G, e)
        st = boxOffset(s, g.G, e) - e
      }
      if (r.shift.value !== sh) r.shift.value = sh
      if (r.stretch.value !== st) r.stretch.value = st
    }
  }, [rowList, e])

  /* THE SCROLL FOLLOWS pos, on the UI thread, for as long as a pull owns it:
     the anchored index's position at this pos, less where the finger is in
     the viewport. Bounded by a limit that is the landed column's own at
     either integer, so the moment the content height snaps to that column
     the offset is already inside it — no jump on landing, ever. */
  useAnimatedReaction(() => pos.value, (p) => {
    if (!scrubbing.value) return
    const a = anchor.value
    const g = geo.value
    const m = meta.value
    const y = anchorY(a.idx, p - a.r0, g.P, g.H, g.G, e) - a.localY
    const lo = Math.max(0, Math.min(m.count - 1, Math.floor(p)))
    const hi = Math.max(0, Math.min(m.count - 1, Math.ceil(p)))
    const fallback = Math.max(estimate(m.rows[lo] ?? 0), estimate(m.rows[hi] ?? 0))
    const lim = scrollLimitAt(p, heights.value, fallback, viewportH.value)
    scrollTo(scrollRef, 0, y < 0 ? 0 : y > lim ? lim : y, false)
  }, [estimate, e])

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
        scrubbing.value = false
        pos.value = idx
        r0.value = idx
        return
      }
      const g = geo.value
      const localY = viewportH.value / 2
      anchor.value = {
        idx: rowIndexAt(scrollY.value + localY, g.P, g.H, g.G, meta.value.rows[from] ?? 0),
        localY, r0: from,
      }
      r0.value = from
      scrubbing.value = true
      pos.value = withTiming(idx, SETTLE, (finished) => {
        if (finished) scrubbing.value = false
      })
    })
  }, [activeIdx, drawKey, pos, dragging, scrubbing, r0, geo, viewportH, anchor, scrollY, meta])

  const onWrapLayout = useCallback((e) => {
    const { width: w, height: h } = e.nativeEvent.layout
    widthSV.value = w
    viewportH.value = h
    setWidth(w)
    setVh(h)
  }, [widthSV, viewportH])

  /* Any mounted row measures the column: its height is every group's, its
     pitch is that plus the gap, and its top is P + i × pitch. */
  const onRowLayout = useCallback((ri, i, e) => {
    const { y, height } = e.nativeEvent.layout
    const G = height + rowGap
    const P = y - i * G
    const g = geoRef.current
    if (Math.abs(g.P - P) < 0.5 && Math.abs(g.H - height) < 0.5 && Math.abs(g.G - G) < 0.5) return
    geoRef.current = { P, H: height, G }
    scheduleOnUI(() => { 'worklet'; geo.value = { P, H: height, G } })
  }, [geo, rowGap])
  const onColumnLayout = useCallback((ri, e) => {
    const h = e.nativeEvent.layout.height
    scheduleOnUI(() => {
      'worklet'
      const next = heights.value.slice()
      if (Math.abs((next[ri] || 0) - h) < 0.5) return
      next[ri] = h
      heights.value = next
    })
  }, [heights])

  const windows = useMemo(
    () => windowsFor(view, vh, geoRef.current, rounds, activeIdx, warm),
    [view, vh, rounds, activeIdx, warm],
  )

  const scrub = useMemo(() => ({
    pos, r0, scrollRef, geo, heights, widthSV, activeIdx, width, warm, estimate, e,
    windows, rowHeight, onScroll,
    onWrapLayout, onRowLayout, onColumnLayout, registerRow, unregisterRow,
  }), [pos, r0, scrollRef, geo, heights, widthSV, activeIdx, width, warm, estimate, e,
       windows, rowHeight, onScroll,
       onWrapLayout, onRowLayout, onColumnLayout, registerRow, unregisterRow])

  return { pan, scrub }
}

/* One match group's slot. Its whole part in the scrub is a translateY —
   condensing onto its successor as its column leaves to the left, spreading
   over its feeders as it waits on the right — and a stretch for the group
   inside. Both are shared values WRITTEN by the scrub's one reaction (see
   the registry in useRoundScrub); this reads its own and nothing else, so a
   row the reaction did not touch this frame costs the frame nothing. */
function Row({ ri, i, scrub, children }) {
  const { onRowLayout, registerRow, unregisterRow } = scrub
  const shift = useSharedValue(0)
  const stretch = useSharedValue(0)
  useEffect(() => {
    const key = `${ri}:${i}`
    registerRow(key, { ri, i, shift, stretch })
    return () => unregisterRow(key)
  }, [ri, i, shift, stretch, registerRow, unregisterRow])
  const style = useAnimatedStyle(() => ({ transform: [{ translateY: shift.value }] }))
  // What the group inside reads to stretch or condense itself.
  const ctx = useMemo(() => ({ stretch }), [stretch])
  return (
    <Animated.View style={style} collapsable={false} onLayout={ev => onRowLayout(ri, i, ev)}>
      <ScrubContext.Provider value={ctx}>{children}</ScrubContext.Provider>
    </Animated.View>
  )
}

/* A round's column, at its own place on the strip: index times the width,
   whatever pos is doing — which is why a commit moves nothing. The round a
   pull left from fades on its way out; the one arriving slides in whole. */
function Column({ ri, num, matches, window, scrub, renderRow, columnStyle }) {
  const { pos, r0, width, rowHeight, onColumnLayout } = scrub
  const style = useAnimatedStyle(() => {
    const s = Math.abs(pos.value - ri)
    return { opacity: r0.value === ri && s > 0 ? Math.max(0, 1 - s) : 1 }
  }, [ri])
  const [lo, hi] = window
  return (
    <Animated.View style={[s.column, { left: ri * width, width }, style]}>
      <View style={columnStyle} onLayout={ev => onColumnLayout(ri, ev)}>
        {matches.map((m, i) => {
          /* A slot with no match — an unplayed half of the bracket — has no
             id; the round and position make a key that exists for every row. */
          const key = m.id ?? `slot-${num}-${i}`
          // Outside the window: a blank of the group's height, keeping the
          // column's size and every other row's place.
          if (i < lo || i > hi) return <View key={key} style={{ height: rowHeight }} />
          return (
            <Row key={key} ri={ri} i={i} scrub={scrub}>
              {renderRow(m)}
            </Row>
          )
        })}
      </View>
    </Animated.View>
  )
}

export function RoundScrubView({ scrub, rounds, renderRow, columnStyle, style = null }) {
  const { pos, scrollRef, heights, widthSV, activeIdx, width, warm, estimate, windows, onScroll, onWrapLayout } = scrub
  /* The strip's height is the content height: the round on screen's column
     at rest, the taller of the two while a pull is between rounds — every
     column is absolutely placed, so nothing else would give it one. A layout
     prop, but one that changes twice per gesture, not per frame. */
  const stripStyle = useAnimatedStyle(() => {
    const p = pos.value
    const n = rounds.length
    const lo = Math.max(0, Math.min(n - 1, Math.floor(p)))
    const hi = Math.max(0, Math.min(n - 1, Math.ceil(p)))
    const fallback = Math.max(estimate(rounds[lo]?.[1].length ?? 0), estimate(rounds[hi]?.[1].length ?? 0))
    return {
      height: contentHeightAt(p, heights.value, fallback),
      transform: [{ translateX: -p * widthSV.value }],
    }
  }, [rounds, estimate])

  // The round on screen and, once warm, its neighbours.
  const mounted = []
  for (let ri = warm ? activeIdx - 1 : activeIdx; ri <= (warm ? activeIdx + 1 : activeIdx); ri++) {
    if (rounds[ri]) mounted.push(ri)
  }

  return (
    <View style={[s.wrap, style]} onLayout={onWrapLayout}>
      {width > 0 && (
        <Animated.ScrollView
          ref={scrollRef}
          style={s.scroller}
          showsVerticalScrollIndicator={false}
          scrollEventThrottle={16}
          onScroll={onScroll}
        >
          <Animated.View style={[s.strip, stripStyle]}>
            {mounted.map(ri => (
              <Column key={rounds[ri][0]} ri={ri} num={rounds[ri][0]} matches={rounds[ri][1]}
                      window={windows[ri] ?? [0, -1]}
                      scrub={scrub} renderRow={renderRow} columnStyle={columnStyle} />
            ))}
          </Animated.View>
        </Animated.ScrollView>
      )}
    </View>
  )
}

const s = StyleSheet.create({
  /* minHeight 0 is the web's: a flex item there will not shrink below its
     content unless told, and this one's content is the whole column — the
     wrapper grew to it, reported that as the viewport, and the anchor's
     scroll limit clamped every pull to the top. Yoga never does this. */
  wrap: { flex: 1, minHeight: 0, overflow: 'hidden' },
  /* touchAction is the web's, and it has to be ON THE SCROLLER: a browser
     resolves a touch's touch-action from the element touched up to the
     nearest scroll container, so a value set above the ScrollView never
     reaches a touch inside it. Left at `auto` there, Chromium reserves every
     drag for scrolling and fires pointercancel on the first sideways move —
     the pan activated, got two empty updates and was cancelled. pan-y keeps
     vertical drags the browser's and hands sideways ones to the gesture.
     iOS ignores the style. */
  scroller: { minHeight: 0, touchAction: 'pan-y' },
  strip: { width: '100%' },
  column: { position: 'absolute', top: 0 },
})
