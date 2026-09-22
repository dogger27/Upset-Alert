/* A SCROLLING PANE THAT ADMITS IT SCROLLS (owner, 2026-09-22).
 *
 * "Ensure the side scroll bar is always visible. It's not clear how to go to
 * the next page or that more data is below." The native indicator cannot do
 * this: on iOS it flashes on touch and fades, and `persistentScrollbar` is
 * Android's alone. So the pane draws its own — a track that is there before
 * the reader touches anything, with a thumb whose height is the share of the
 * page on screen, which is the part that says HOW MUCH more there is.
 *
 * The thumb is moved by the native driver off a plain transform, so it keeps
 * up with a flick without a round trip to JS on every frame. The geometry is
 * in scrollBar.js, where it can be proved without a phone.
 */
import { useRef, useState } from 'react'
import { Animated, StyleSheet, View } from 'react-native'
import { barRange, thumbSize } from './scrollBar.js'
import { C, R } from './theme'

const BAR_W = 3
/* The bar sits outside the text rather than over it: a thumb crossing the end
   of a line is the kind of thing that reads as a rendering fault. */
const BAR_GAP = BAR_W + 5

export function ScrollPane({ style, contentContainerStyle, children, ...rest }) {
  const [viewH, setViewH] = useState(0)
  const [contentH, setContentH] = useState(0)
  const y = useRef(new Animated.Value(0)).current

  const thumb = thumbSize({ viewH, contentH })
  const { max, travel } = barRange({ viewH, contentH, thumb })

  return (
    <View style={[s.pane, style]} onLayout={e => setViewH(e.nativeEvent.layout.height)}>
      <Animated.ScrollView
        showsVerticalScrollIndicator={false}
        scrollEventThrottle={16}
        onScroll={Animated.event([{ nativeEvent: { contentOffset: { y } } }], { useNativeDriver: true })}
        onContentSizeChange={(_w, h) => setContentH(h)}
        contentContainerStyle={[contentContainerStyle, thumb ? { paddingRight: BAR_GAP } : null]}
        {...rest}>
        {children}
      </Animated.ScrollView>
      {thumb ? (
        <View style={s.track} pointerEvents="none">
          <Animated.View style={[s.thumb, {
            height: thumb,
            transform: [{
              translateY: y.interpolate({
                inputRange: [0, max], outputRange: [0, travel], extrapolate: 'clamp',
              }),
            }],
          }]} />
        </View>
      ) : null}
    </View>
  )
}

const s = StyleSheet.create({
  pane: { flexShrink: 1 },
  /* The track spans the pane, so its own length is the page and the thumb's
     place in it is where the reader is. */
  track: {
    position: 'absolute', top: 0, bottom: 0, right: 0, width: BAR_W,
    borderRadius: R.xs, backgroundColor: C.border,
  },
  thumb: { width: BAR_W, borderRadius: R.xs, backgroundColor: C.borderLit },
})
