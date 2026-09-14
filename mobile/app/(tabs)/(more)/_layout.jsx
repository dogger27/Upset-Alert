/*
 * The pushed screens — INSIDE the tab navigator, so the bar stays.
 *
 * These all used to sit on the root stack, which draws OVER the tabs: opening
 * a league, the Hall of Fame, the rules or the draw history took the
 * navigation away, and the way back to any other destination was the header's
 * Back button (owner, 2026-09-14). A tab bar that disappears on half the app's
 * screens is not a tab bar.
 *
 * A group rather than a directory — `(more)` is in parentheses — so every path
 * is exactly what it was: /hall-of-fame, /league/3, /standings/77. Nothing
 * that links here had to change.
 *
 * A STACK, not more tabs. These are places you go INTO and come back from, so
 * they keep their headers and their Back button; only the bar underneath is
 * new. `(tabs)/_layout` registers this group with href:null, which keeps it
 * out of the bar while leaving it inside the navigator that draws one.
 *
 * The auth screens stay on the ROOT stack deliberately. Sign-in, register and
 * forgot-password are what the app shows when there is no session, and a tab
 * bar there would offer four destinations that all bounce back to sign-in.
 */
import { Stack } from 'expo-router'
import { C, T } from '../../../theme'

export default function MoreLayout() {
  return (
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
      <Stack.Screen name="history" options={{ title: 'Draw history' }} />
      <Stack.Screen name="standings/[id]" options={{ title: 'Standings' }} />
      <Stack.Screen name="hall-of-fame" options={{ title: 'Hall of Fame' }} />
      <Stack.Screen name="rules" options={{ title: 'Rules' }} />
      <Stack.Screen name="about" options={{ title: 'About' }} />
    </Stack>
  )
}
