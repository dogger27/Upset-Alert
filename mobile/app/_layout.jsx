/*
 * The root layout: fonts, providers, then the stack.
 *
 * Auth lives above the navigator so a 401 anywhere can move the whole app to
 * the sign-in screen without a screen having to know how it got there.
 */

import { Stack } from 'expo-router'
import { StatusBar } from 'expo-status-bar'
import { useFonts } from 'expo-font'
import { ActivityIndicator, View } from 'react-native'
import { SafeAreaProvider } from 'react-native-safe-area-context'
import { AuthProvider } from '../auth'
import { FONTS } from '../fonts'
import { C, T } from '../theme'

export default function RootLayout() {
  const [ready] = useFonts(FONTS)

  // Held rather than rendered-then-swapped. Text laid out in system San
  // Francisco and then reflowed into a CONDENSED face moves every line on the
  // screen, which is worse than a beat of nothing — and the beat is short,
  // because these are local files, not a network fetch.
  if (!ready) {
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
          <Stack.Screen name="index" options={{ headerShown: false }} />
          <Stack.Screen name="sign-in" options={{ headerShown: false }} />
          <Stack.Screen name="status" options={{ title: 'Status' }} />
          <Stack.Screen name="leagues" options={{ title: 'Leagues' }} />
          <Stack.Screen name="draw/[id]" options={{ title: 'Draw' }} />
        </Stack>
      </AuthProvider>
    </SafeAreaProvider>
  )
}
