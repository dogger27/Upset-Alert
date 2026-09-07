/*
 * Swipe between rounds anywhere on the draw screen.
 *
 * ONE SWIPE MOVES ONE ROUND. Distance decides only WHETHER the swipe counts,
 * never how far it goes: a flick and a slow drag across the whole screen both
 * move exactly one round. Counting rounds per pixel instead let a single long
 * drag cross six of them, which is a scrub-bar's behaviour and not this.
 *
 * Committed on RELEASE, not during the drag. That is what makes "one swipe"
 * a thing the gesture can count — while the finger is down there is no
 * decision to take back, and no way for a wandering drag to rack up rounds.
 *
 * DRAG LEFT FOR THE NEXT ROUND: the rounds travel under the finger like a
 * strip of film, the direction RoundScrub has always used.
 *
 * Capture, so a horizontal drag is ours before the list's ScrollView takes
 * it. Vertical falls straight through, untouched: that is the list's.
 */
import { useMemo, useRef } from 'react'
import { PanResponder } from 'react-native'

// RoundScrub's axis rules: decide early, and only on a drag that is clearly
// sideways rather than a scroll that wandered.
const AXIS_LOCK_PX = 8
const H_RATIO = 1.5
/* Far enough that a stray sideways nudge during a scroll does not change
   round, short enough that a small flick does. */
const COMMIT_PX = 40
// A fast flick counts even when it is short.
const COMMIT_VELOCITY = 0.3

export function useRoundSwipe({ rounds, active, onPick }) {
  /* EVERY VALUE A HANDLER READS GOES THROUGH THIS REF. PanResponder.create
     runs once, so handlers closing over `rounds`, `active` or `onPick` would
     read the first render's values on every later swipe. */
  const live = useRef({ rounds, active, onPick })
  live.current = { rounds, active, onPick }

  const pan = useMemo(() => PanResponder.create({
    onMoveShouldSetPanResponderCapture: (_e, g) => {
      const ax = Math.abs(g.dx), ay = Math.abs(g.dy)
      if (Math.max(ax, ay) < AXIS_LOCK_PX) return false
      return ax > ay * H_RATIO
    },
    onPanResponderMove: () => {},
    onPanResponderRelease: (_e, g) => {
      const { rounds: rs, active: a, onPick: pick } = live.current
      if (!rs.length) return
      if (Math.abs(g.dx) < COMMIT_PX && Math.abs(g.vx) < COMMIT_VELOCITY) return
      // ONE step, in the direction of travel. `dx` sets only the sign here —
      // its magnitude has already done its only job above.
      const step = g.dx < 0 ? 1 : -1
      const now = Math.max(0, rs.findIndex(([n]) => n === a))
      const want = Math.max(0, Math.min(rs.length - 1, now + step))
      if (want !== now) pick(rs[want][0])
    },
    // Keep the touch once swiping: a scroll view asking for it mid-drag is
    // what makes a gesture feel like it slipped.
    onPanResponderTerminationRequest: () => false,
  }), [])

  return pan.panHandlers
}
