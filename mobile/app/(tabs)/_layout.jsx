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
import { C, T } from '../../theme'

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
        options={{ title: 'Today', headerShown: false, tabBarIcon: icon('home') }}
      />
      <Tabs.Screen
        name="schedule"
        options={{ title: 'Schedule', tabBarIcon: icon('calendar') }}
      />
      <Tabs.Screen
        name="leagues"
        options={{ title: 'Leagues', tabBarIcon: icon('trophy') }}
      />
      <Tabs.Screen
        name="status"
        options={{ title: 'Status', tabBarIcon: icon('pulse') }}
      />
    </Tabs>
  )
}
