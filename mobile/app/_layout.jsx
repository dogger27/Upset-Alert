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
import { AuthProvider, useAuth } from '../auth'
import { FONTS } from '../fonts'
import { C, T } from '../theme'


/* WHY THE NAVIGATOR WAITS FOR AUTH BOOT.
 *
 * expo-router mounts the target screen immediately, so a COLD LAUNCH STRAIGHT
 * INTO A ROUTE — a deep link, a notification tap, and above all a Live Activity
 * tap into a match — begins fetching before auth.boot() has read the Keychain
 * and called setToken(). Those requests go out bare and come back 401.
 *
 * That is worse than a slow screen: useApi CACHES the rejection, and nothing
 * re-runs it when the token later arrives, so the screen stays wrong until
 * something forces a refetch. Observed on /draw/77, where every pick silently
 * disappeared — the bracket rendered perfectly and simply showed no picks,
 * which is the kind of wrong that reads as a design decision.
 *
 * Only 'boot' waits. 'signedout' and 'unreachable' must render, or the sign-in
 * screen and the offline notice would have nowhere to appear.
 */
function Gate({ children }) {
  const { phase } = useAuth()
  if (phase === 'boot') {
    return (
      <View style={{ flex: 1, backgroundColor: C.bg, alignItems: 'center', justifyContent: 'center' }}>
        <ActivityIndicator color={C.clay} />
      </View>
    )
  }
  return children
}

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
        <Gate>
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
          <Stack.Screen name="history" options={{ title: 'Draw history' }} />
          <Stack.Screen name="hall-of-fame" options={{ title: 'Hall of Fame' }} />
          <Stack.Screen name="rules" options={{ title: 'Rules' }} />
          <Stack.Screen name="forgot-password" options={{ title: 'Forgot password' }} />
          <Stack.Screen name="register" options={{ title: 'Create account' }} />
          <Stack.Screen name="about" options={{ title: 'About' }} />
        </Stack>
        </Gate>
      </AuthProvider>
    </SafeAreaProvider>
  )
}
