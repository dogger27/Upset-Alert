/* A one-line toast, app-wide. `showToast('…')` from anywhere; `<ToastHost />`
   once, at the root, draws it above everything for a couple of seconds.
   Module state rather than context so a helper in a plain .js file (the
   Lock Screen bridge, say) can speak without a React tree in hand. */
import { useEffect, useRef, useState } from 'react'
import { Animated, StyleSheet, Text, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { C, R, S, T } from './theme'

let listener = null
export function showToast(message, ms = 2200) {
  listener?.(String(message), ms)
}

export function ToastHost() {
  const [msg, setMsg] = useState(null)
  const fade = useRef(new Animated.Value(0)).current
  const timer = useRef(null)
  const insets = useSafeAreaInsets()
  useEffect(() => {
    listener = (m, ms) => {
      clearTimeout(timer.current)
      setMsg(m)
      Animated.timing(fade, { toValue: 1, duration: 160, useNativeDriver: true }).start()
      timer.current = setTimeout(() => {
        Animated.timing(fade, { toValue: 0, duration: 220, useNativeDriver: true })
          .start(() => setMsg(null))
      }, ms)
    }
    return () => { listener = null; clearTimeout(timer.current) }
  }, [fade])
  if (!msg) return null
  return (
    <View pointerEvents="none" style={[s.host, { bottom: insets.bottom + 84 }]}>
      <Animated.View style={[s.toast, { opacity: fade }]} accessibilityLiveRegion="polite">
        <Text style={s.text} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.6}>
          {msg}
        </Text>
      </Animated.View>
    </View>
  )
}

const s = StyleSheet.create({
  host: { position: 'absolute', left: 0, right: 0, alignItems: 'center' },
  toast: {
    backgroundColor: C.ink, borderRadius: R.md, paddingHorizontal: S.md, paddingVertical: S.sm,
    maxWidth: '94%', shadowColor: '#000', shadowOpacity: 0.3, shadowRadius: 8, shadowOffset: { width: 0, height: 4 },
  },
  // One line, always: the message is short by contract and a phone at a
  // large Dynamic Type size shrinks it rather than wrapping it.
  text: { ...T.smallMed, color: C.bg, textAlign: 'center' },
})
