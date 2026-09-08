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
    // Black above and below, so the bar is a band between the banner and
    // the draw rather than glued to either.
    marginTop: S.md, marginBottom: S.xs,
    /* EDGE TO EDGE: the screen pads its body S.lg a side, and a ruled bar
       that stopped short of the edges read as a box, not a bar. The row
       inside keeps that padding so the labels do not touch the glass. */
    marginHorizontal: -S.lg,
    backgroundColor: '#12262a',
    borderTopWidth: 1, borderBottomWidth: 1, borderColor: C.borderLit,
    paddingVertical: 3,
  },
  /* THIN: no padding of its own; the line box is the type's own height
     and the pill adds a point each side, so the bar is about 20pt. The
     labels may shrink together (flexShrink on each, the type shrinking to
     fit inside) so seven rounds always fit the width, at any text size. */
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 4, paddingHorizontal: S.lg },
  round: {
    paddingHorizontal: 5, paddingVertical: 1, borderRadius: 5, borderWidth: 1, borderColor: 'transparent',
    flexShrink: 1, minWidth: 0,
  },
  // The round you are on: a filled, edged pill, the only bright thing here.
  roundOn: { backgroundColor: C.greenDeep, borderColor: C.greenLit },
  // Dimmed but still READ — these are the control, not decoration.
  roundText: { ...T.smallMed, lineHeight: undefined, color: C.muted },
  roundTextOn: { color: C.greenBright, fontFamily: 'Archivo_700Bold' },
  // Punctuation, so it sits below the labels it separates without vanishing.
  dot: { ...T.smallMed, lineHeight: undefined, color: C.borderLit },
})
