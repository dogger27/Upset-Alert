/*
 * The draw's round strip: every round on one line.
 *
 * Tap a round to go to it. SCRUBBING lives in roundSwipe.js and covers the
 * whole screen, this strip included — a gesture that worked only while the
 * finger was on these few glyphs was the complaint that produced it.
 */
import { Text } from 'react-native'
import { shortRound } from './rounds'
import { C, S, T } from './theme'

export function RoundStrip({ rounds, active, onPick }) {
  return (
    /* ONE Text with pressable children, not a row of Pressables: a single
       Text shrinks the whole strip as a unit to fit the width. As separate
       views each cell would shrink on its own and "R128" would end up
       smaller than "F". */
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
  )
}

const s = {
  /* marginTop MATCHES the draw list's paddingTop (app/(tabs)/draw/[id].jsx),
     so the strip sits in equal air above and below. Two files, one number:
     if one moves the other has to. */
  strip: { ...T.smallMed, marginTop: S.xs, paddingVertical: S.xs, textAlign: 'center' },
  // The round you are on, and the only bright thing in the strip.
  roundOn: { color: C.greenBright, fontFamily: 'Archivo_700Bold' },
  // Dimmed but still READ — these are the control, not decoration, so they
  // stay well clear of the faint end of the ramp.
  roundOff: { color: C.muted },
  // Punctuation, so it sits below the labels it separates without vanishing.
  roundDot: { color: C.borderLit },
}
