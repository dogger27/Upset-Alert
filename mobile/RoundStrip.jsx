/*
 * The draw's round strip: every round on one line, and a finger-scrub across
 * it to move between them.
 *
 * TWO GESTURES REACH THE SAME STATE, deliberately. RoundScrub is the fine
 * control — drag over the DRAW and the next round is pulled in under your
 * finger, one round per 150px, with the row you were pointing at anchored.
 * This is the coarse one: drag along the STRIP and the selection follows,
 * a round every 46px, so R128 to F is one short swipe rather than seven.
 *
 * A tap on a label still selects it directly. The PanResponder only claims
 * the touch once it is clearly horizontal, so a tap never becomes a scrub and
 * a vertical drag still scrolls the page.
 */
import { useRef } from 'react'
import { PanResponder, Text, View } from 'react-native'
import { shortRound } from './rounds'
import { C, S, T } from './theme'

/* RoundScrub's axis rules, so the two gestures agree on what "horizontal"
   means and one cannot start while the other is running. */
const H_RATIO = 1.5
const AXIS_LOCK_PX = 8
/* One round per 46px. Shorter than RoundScrub's 150 because this control is
   the whole draw at a glance: the strip is ~300px wide, so a swipe across it
   covers every round of a slam. */
const STEP_PX = 46

export function RoundStrip({ rounds, active, onPick }) {
  const idx = Math.max(0, rounds.findIndex(([n]) => n === active))

  /* EVERYTHING THE RESPONDER READS GOES THROUGH A REF. PanResponder.create
     runs once, so a handler closing over `rounds`, `onPick` or the live index
     would still be reading this first render's values on every later drag —
     the classic stale-closure trap. */
  const live = useRef({ rounds, onPick, idx })
  live.current = { rounds, onPick, idx }
  // Where the drag began. Steps count from THIS, not from the selection as it
  // changes: committing a step would otherwise move the origin under the
  // finger and the strip would run away faster than the hand.
  const from = useRef(0)

  const pan = useRef(
    PanResponder.create({
      onMoveShouldSetPanResponder: (_e, g) =>
        Math.abs(g.dx) > AXIS_LOCK_PX && Math.abs(g.dx) > Math.abs(g.dy) * H_RATIO,
      // Once scrubbing, keep the touch — a parent scroll view asking for it
      // mid-drag is what makes a gesture feel like it slipped.
      onPanResponderTerminationRequest: () => false,
      onPanResponderGrant: () => { from.current = live.current.idx },
      onPanResponderMove: (_e, g) => {
        const { rounds: rs, onPick: pick, idx: now } = live.current
        const want = Math.max(0, Math.min(
          rs.length - 1, from.current + Math.round(g.dx / STEP_PX)))
        if (want !== now) pick(rs[want][0])
      },
    }),
  ).current

  return (
    <View {...pan.panHandlers}>
      {/* ONE Text with pressable children, not a row of Pressables: a single
          Text shrinks the whole strip as a unit to fit the width. As separate
          views each cell would shrink on its own and "R128" would end up
          smaller than "F". */}
      <Text style={s.strip} numberOfLines={1}
            adjustsFontSizeToFit minimumFontScale={0.6}>
        {rounds.flatMap(([num, matches], i) => {
          const on = num === active
          const label = (
            <Text key={num} onPress={() => onPick(num)} suppressHighlighting
                  accessibilityRole="button"
                  accessibilityState={{ selected: on }}
                  style={on ? s.roundOn : s.roundOff}>
              {shortRound(matches[0]?.round_name, num)}
            </Text>
          )
          return i === 0
            ? [label]
            : [<Text key={`dot${num}`} style={s.roundDot}>  •  </Text>, label]
        })}
      </Text>
    </View>
  )
}

const s = {
  strip: { ...T.smallMed, marginTop: S.sm, paddingVertical: S.xs, textAlign: 'center' },
  // The round you are on, and the only bright thing in the strip.
  roundOn: { color: C.greenBright, fontFamily: 'Archivo_700Bold' },
  // Dimmed but still READ — these are the control, not decoration, so they
  // stay well clear of the faint end of the ramp.
  roundOff: { color: C.muted },
  // Punctuation, so it sits below the labels it separates without vanishing.
  roundDot: { color: C.borderLit },
}
