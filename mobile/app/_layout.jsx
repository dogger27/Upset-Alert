/*
 * The root layout: providers, then the stack.
 *
 * Auth lives above the navigator so a 401 anywhere can move the whole app to
 * the sign-in screen without a screen having to know how it got there.
 */

import { Stack } from 'expo-router'
import { StatusBar } from 'expo-status-bar'
import { SafeAreaProvider } from 'react-native-safe-area-context'
import { AuthProvider } from '../auth'
import { C } from '../theme'

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <AuthProvider>
        <StatusBar style="light" />
        <Stack
          screenOptions={{
            headerStyle: { backgroundColor: C.bg },
            headerTintColor: C.ink,
            headerTitleStyle: { fontWeight: '800' },
            headerShadowVisible: false,
            contentStyle: { backgroundColor: C.bg },
          }}
        >
          <Stack.Screen name="index" options={{ title: 'Upset Alert' }} />
          <Stack.Screen name="sign-in" options={{ title: 'Sign in', headerShown: false }} />
          <Stack.Screen name="status" options={{ title: 'Status' }} />
        </Stack>
      </AuthProvider>
    </SafeAreaProvider>
  )
}
