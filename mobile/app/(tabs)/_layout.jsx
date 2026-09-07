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

import { router, Tabs } from 'expo-router'
import { useState } from 'react'
import { Pressable, Text, View } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { BracketIcon } from '../../BracketIcon'
import { Sheet } from '../../sheet'
import { listTournaments } from '../../api'
import { useAuth } from '../../auth'
import { useApi } from '../../useApi'
import { computeCohortInfo, getHomeSection } from '../../drawStatus'
import { useCurrentDraw } from '../../currentDraw'
import { C, T } from '../../theme'

/* Openable means the draw actually exists to look at — the dashboard's own
   test, so the tab cannot offer a tournament whose bracket is unreleased. */
const hasDrawData = t => t.status === 'completed' || !!t.draw_released_direct_at

/* LIVE ONLY. The chooser was listing every draw that had ever been released,
   so a season of finished tournaments buried the two being played. These are
   the dashboard's own top two sections: picks still open, or play under way.
   getHomeSection also promotes a completed draw back to 'active' while the
   rest of its cohort is still going — a men's final does not retire the
   event while the women's is on court. */
const LIVE_SECTIONS = new Set(['open', 'active'])

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
  const [picking, setPicking] = useState(false)
  const showing = useCurrentDraw()
  /* Gated on a real session, exactly as the dashboard gates it: the tabs can
     render for a beat while signed out, and an unauthenticated call here
     would 401 — which this app treats as "sign out". */
  const { phase } = useAuth()
  const ready = phase === 'ready'
  const tours = useApi(ready ? 'tournaments' : null, listTournaments, { enabled: ready })
  /* computeCohortInfo needs EVERY draw: clustering a filtered list moves the
     boundaries it works out, which is how "Last Week" starts stealing from
     "Active". Filter AFTER, never before. */
  const all = tours.data || []
  const cohort = computeCohortInfo(all)
  const openable = all.filter(hasDrawData)
  // What the CHOOSER lists. The href below is a separate question.
  const live = openable.filter(t => LIVE_SECTIONS.has(getHomeSection(t, cohort)))
  /* The tab's destination falls back past `live` to any released draw, so the
     bar keeps four tabs through an off-season week with nothing being played.
     The chooser still lists only what is live and says so when that is
     nothing — a tab that vanishes teaches people it might not be there. */
  const drawId = showing ?? live[0]?.id ?? openable[0]?.id ?? null

  return (
    <>
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
        /* ASK WHICH ONE. There is never a single "the draw" — two at every
           slam — so the tab opens a chooser instead of guessing. The href
           still points somewhere real: it is what keeps the tab on the bar
           and gives the press a destination if this listener ever misses. */
        listeners={{ tabPress: e => { e.preventDefault(); setPicking(true) } }}
        options={{
          /* The LABEL is always "Draw". The screen used to set `title`, which
             drives the tab label as well as the header, so the bar read
             "ATX Open" — the name of a tournament where the name of a
             destination belongs. The screen sets headerTitle now. */
          title: 'Draw',
          tabBarIcon: ({ color, size }) => <BracketIcon size={size ?? 22} color={color} />,
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

    <Sheet visible={picking} onClose={() => setPicking(false)} title="Draws">
      {live.length ? live.map(t => (
        <Pressable key={t.id} style={s.row}
                   onPress={() => { setPicking(false); router.push(`/draw/${t.id}`) }}>
          {/* The tour's colour is how the two halves of a combined event tell
              themselves apart everywhere else in the app; a list of draws is
              exactly where that matters most. */}
          <View style={[s.tint, { backgroundColor: t.gender === 'F' ? C.wta : C.atp }]} />
          <Text style={s.name} numberOfLines={1}>{t.name}</Text>
          <Text style={s.tour}>{t.gender === 'F' ? 'WTA' : 'ATP'}</Text>
          {t.id === showing ? <Ionicons name="checkmark" size={16} color={C.greenBright} /> : null}
        </Pressable>
      )) : (
        <Text style={s.none}>No draws are being played right now.</Text>
      )}
    </Sheet>
    </>
  )
}

const s = {
  row: {
    flexDirection: 'row', alignItems: 'center', gap: 10,
    paddingVertical: 12, borderTopWidth: 1, borderTopColor: C.border,
  },
  tint: { width: 3, height: 20, borderRadius: 2 },
  name: { ...T.bodyMed, color: C.ink, flex: 1 },
  tour: { ...T.tiny, color: C.muted },
  none: { ...T.smallMed, color: C.muted, textAlign: 'center', paddingVertical: 12 },
}
