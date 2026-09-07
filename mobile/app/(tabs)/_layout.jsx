/*
 * The tab bar.
 *
 * Four destinations, because the app has four things a person opens it for and
 * they were previously reachable only through text links at the bottom of the
 * dashboard — which is a website's navigation, not an app's.
 *
 * Icon AND label on every tab. An icon alone saves a few points of height and
 * costs anyone who does not already know what the glyph means; on a tab bar
 * used a few times a day that trade is not worth making.
 */

import { Tabs } from 'expo-router'
import { Ionicons } from '@expo/vector-icons'
import { listTournaments } from '../../api'
import { useAuth } from '../../auth'
import { useApi } from '../../useApi'
import { useCurrentDraw } from '../../currentDraw'
import { C, T } from '../../theme'

/* Openable means the draw actually exists to look at — the dashboard's own
   test, so the tab cannot offer a tournament whose bracket is unreleased. */
const hasDrawData = t => t.status === 'completed' || !!t.draw_released_direct_at

function icon(name) {
  // The filled/outline pair is what makes the selected tab obvious without
  // relying on colour alone.
  const TabIcon = ({ color, focused, size }) => (
    <Ionicons name={focused ? name : `${name}-outline`} size={size ?? 22} color={color} />
  )
  TabIcon.displayName = `TabIcon(${name})`
  return TabIcon
}

export default function TabLayout() {
  /* WHICH DRAW THE TAB OPENS. The one on screen if you are reading one, so
     tapping Draw never swaps the women's bracket for the men's. Otherwise the
     first worth opening — shared cache key with the dashboard, so this costs
     no extra request. With none at all the tab is hidden rather than dead. */
  const showing = useCurrentDraw()
  /* Gated on a real session, exactly as the dashboard gates it: the tabs can
     render for a beat while signed out, and an unauthenticated call here
     would 401 — which this app treats as "sign out". */
  const { phase } = useAuth()
  const ready = phase === 'ready'
  const tours = useApi(ready ? 'tournaments' : null, listTournaments, { enabled: ready })
  const fallback = (tours.data || []).find(hasDrawData)?.id ?? null
  const drawId = showing ?? fallback

  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: C.bg },
        headerTintColor: C.ink,
        headerTitleStyle: { ...T.h2, color: C.ink },
        headerShadowVisible: false,
        sceneStyle: { backgroundColor: C.bg },
        tabBarActiveTintColor: C.clay,
        tabBarInactiveTintColor: C.faint,
        tabBarStyle: {
          backgroundColor: C.card,
          borderTopColor: C.border,
          borderTopWidth: 1,
        },
        // Archivo rather than the system face, so the bar belongs to the app.
        tabBarLabelStyle: { ...T.tiny, marginTop: 1 },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{ title: 'Home', headerShown: false, tabBarIcon: icon('home') }}
      />
      {/* No header, like Today: the lit tab already names the page, and the
          screen's own date bar is the thing worth the top of the phone.
          `title` stays — it is the TAB's label, not the header's. */}
      <Tabs.Screen
        name="schedule"
        options={{ title: 'Schedule', headerShown: false, tabBarIcon: icon('calendar') }}
      />
      {/* The bracket, between the day's play and the people you play it with. */}
      <Tabs.Screen
        name="draw/[id]"
        options={{
          title: 'Draw',
          tabBarIcon: icon('git-network'),
          href: drawId != null ? `/draw/${drawId}` : null,
        }}
      />
      <Tabs.Screen
        name="leagues"
        options={{ title: 'Leagues', tabBarIcon: icon('trophy') }}
      />
      {/* OFF THE BAR, NOT GONE. Status is the account screen — preferences,
          password, sign out — reached from the dashboard's avatar. Four
          destinations is the brief, and a diagnostics screen is not one of
          the four things this app is opened for. */}
      <Tabs.Screen name="status" options={{ title: 'Status', href: null }} />
    </Tabs>
  )
}
