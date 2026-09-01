/*
 * The root layout: fonts, providers, then the stack.
 *
 * Auth lives above the navigator so a 401 anywhere can move the whole app to
 * the sign-in screen without a screen having to know how it got there.
 */

import { useEffect, useState } from 'react'
import { Stack } from 'expo-router'
import { StatusBar } from 'expo-status-bar'
import { useFonts } from 'expo-font'
import { ActivityIndicator, View } from 'react-native'
import { SafeAreaProvider } from 'react-native-safe-area-context'
import { AuthProvider } from '../auth'
import { FONTS } from '../fonts'
import { C, T } from '../theme'

export default function RootLayout() {
  const [ready, fontError] = useFonts(FONTS)

  /* A DEADLINE ON THE FONTS, because the alternative is an app that never
     starts. Holding the first paint is right — text laid out in system San
     Francisco and then reflowed into a CONDENSED face moves every line on the
     screen, and these are local files, so the wait is a beat.
     But "wait for fonts" with no escape means anything that stops useFonts
     resolving stops the app dead at a spinner, with nothing on screen to say
     why. Seen for real: the web build sat on this spinner indefinitely.
     After the deadline we render in the fallback stack. A reflow is a bad
     second; a blank launch is no app at all. */
  const [waited, setWaited] = useState(false)
  useEffect(() => {
    const t = setTimeout(() => setWaited(true), 2500)
    return () => clearTimeout(t)
  }, [])

  if (!ready && !fontError && !waited) {
    return (
      <View style={{ flex: 1, backgroundColor: C.bg, alignItems: 'center', justifyContent: 'center' }}>
        <StatusBar style="light" />
        <ActivityIndicator color={C.clay} />
      </View>
    )
  }

  return (
    <SafeAreaProvider>
      <AuthProvider>
        <StatusBar style="light" />
        <Stack
          screenOptions={{
            headerStyle: { backgroundColor: C.bg },
            headerTintColor: C.ink,
            headerTitleStyle: { ...T.h2, color: C.ink },
            headerShadowVisible: false,
            headerBackTitle: 'Back',
            contentStyle: { backgroundColor: C.bg },
          }}
        >
          {/* The tab bar owns the four main destinations; everything else is
              PUSHED over it, which is what keeps a draw feeling like somewhere
              you went rather than somewhere you switched to. */}
          <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
          <Stack.Screen name="sign-in" options={{ headerShown: false }} />
          <Stack.Screen name="draw/[id]" options={{ title: 'Draw' }} />
        </Stack>
      </AuthProvider>
    </SafeAreaProvider>
  )
}
