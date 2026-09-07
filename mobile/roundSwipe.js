/*
 * Scrub between rounds with a finger, anywhere on the draw screen.
 *
 * A TRUE SCRUB, not a page-flip. Keep dragging and you keep moving: one round
 * every 48px, so a single swipe crosses a slam's seven rounds. RoundScrub's
 * pull gesture committed at most ONE round however far you dragged, which is
 * right for a page-flip and wrong for what this is.
 *
 * DRAG LEFT FOR THE NEXT ROUND. The rounds travel under the finger like a
 * strip of film — the same direction RoundScrub has always used, and the
 * opposite of moving a cursor along the strip. One convention, whichever part
 * of the screen the finger is on.
 *
 * Capture, so a horizontal drag is ours before the list's ScrollView can take
 * it. Vertical falls straight through, untouched: that is the list's.
 */
import { useMemo, useRef } from 'react'
import { PanResponder } from 'react-native'

// RoundScrub's axis rules, unchanged: decide early, and only on a drag that is
// clearly sideways rather than a scroll that wandered.
const AXIS_LOCK_PX = 8
const H_RATIO = 1.5
/* One round per 48px. Six steps — R128 to F — is 288px, inside a comfortable
   thumb sweep on a 393pt screen, which is the point of a scrub. */
const STEP_PX = 48

export function useRoundSwipe({ rounds, active, onPick }) {
  /* EVERY VALUE A HANDLER READS GOES THROUGH THIS REF. PanResponder.create
     runs once, so handlers closing over `rounds`, `active` or `onPick` would
     read the first render's values on every later drag. */
  const live = useRef({ rounds, active, onPick })
  live.current = { rounds, active, onPick }

  /* The index the drag STARTED at. Steps count from here, never from the live
     selection: committing a step moves the selection, and counting from a
     moving origin makes the draw outrun the hand. */
  const from = useRef(0)
  const indexOf = (rs, a) => Math.max(0, rs.findIndex(([n]) => n === a))

  const pan = useMemo(() => PanResponder.create({
    onMoveShouldSetPanResponderCapture: (_e, g) => {
      const ax = Math.abs(g.dx), ay = Math.abs(g.dy)
      if (Math.max(ax, ay) < AXIS_LOCK_PX) return false
      return ax > ay * H_RATIO
    },
    onPanResponderGrant: () => {
      const { rounds: rs, active: a } = live.current
      from.current = indexOf(rs, a)
    },
    onPanResponderMove: (_e, g) => {
      const { rounds: rs, active: a, onPick: pick } = live.current
      if (!rs.length) return
      const want = Math.max(0, Math.min(
        rs.length - 1, from.current + Math.round(-g.dx / STEP_PX)))
      if (want !== indexOf(rs, a)) pick(rs[want][0])
    },
    // Keep the touch once scrubbing: a scroll view asking for it mid-drag is
    // what makes a gesture feel like it slipped.
    onPanResponderTerminationRequest: () => false,
  }), [])

  return pan.panHandlers
}
