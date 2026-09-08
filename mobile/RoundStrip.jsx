/*
 * The draw's round bar: every round on one line, ruled above and below.
 *
 * Tap a round to go to it. SCRUBBING lives in roundSwipe.js and covers the
 * whole screen, this bar included — a gesture that worked only while the
 * finger was on these few glyphs was the complaint that produced it.
 *
 * A ROW OF VIEWS, not one Text with pressable spans, because the selected
 * round is a bordered pill and a nested Text cannot carry a border on iOS.
 * The dots on either side of the pill are dropped — its edge is already
 * the separator — so "R32 • [R16] • QF" reads as "R32 [R16] QF".
 */
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { shortRound } from './rounds'
import { C, S, T } from './theme'

export function RoundStrip({ rounds, active, onPick }) {
  const activeIdx = rounds.findIndex(([n]) => n === active)
  return (
    <View style={s.bar}>
      <View style={s.row}>
        {rounds.flatMap(([num, matches], i) => {
          const on = num === active
          const label = (
            <Pressable key={num} onPress={() => onPick(num)} hitSlop={6}
                       accessibilityRole="button" accessibilityState={{ selected: on }}
                       style={[s.round, on && s.roundOn]}>
              <Text style={[s.roundText, on && s.roundTextOn]} numberOfLines={1}
                    adjustsFontSizeToFit minimumFontScale={0.6}>
                {shortRound(matches[0]?.round_name, num)}
              </Text>
            </Pressable>
          )
          if (i === 0) return [label]
          // No dot beside the selected round, on either side.
          const touchesActive = i === activeIdx || i - 1 === activeIdx
          return touchesActive
            ? [label]
            : [<Text key={`dot${num}`} style={s.dot}>•</Text>, label]
        })}
      </View>
    </View>
  )
}

const s = StyleSheet.create({
  /* Its own field, ruled top and bottom, so the bar reads as a control
     strip rather than a line of text floating between the banner and the
     draw. The fill is this bar's alone — nothing else on the screen is
     this teal-black — so it is found at a glance. marginTop matches the
     banner's own air. */
  bar: {
    marginTop: S.xs,
    backgroundColor: '#12262a',
    borderTopWidth: 1, borderBottomWidth: 1, borderColor: C.borderLit,
    paddingVertical: 3,
  },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6 },
  round: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 999, borderWidth: 1, borderColor: 'transparent' },
  // The round you are on: a filled, edged pill, the only bright thing here.
  roundOn: { backgroundColor: C.greenDeep, borderColor: C.greenLit },
  // Dimmed but still READ — these are the control, not decoration.
  roundText: { ...T.smallMed, color: C.muted },
  roundTextOn: { color: C.greenBright, fontFamily: 'Archivo_700Bold' },
  // Punctuation, so it sits below the labels it separates without vanishing.
  dot: { ...T.smallMed, color: C.borderLit },
})
