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

import { router, Tabs, usePathname } from 'expo-router'
import { useState } from 'react'
import { Pressable, Text, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { Ionicons } from '@expo/vector-icons'
import { BracketIcon } from '../../BracketIcon'
import { TourBadge } from '../../cards'
import { Sheet } from '../../sheet'
import { listTournaments } from '../../api'
import { useAuth } from '../../auth'
import { useApi } from '../../useApi'
import { computeCohortInfo, getHomeSection } from '../../drawStatus'
import { useCurrentDraw } from '../../currentDraw'
import { useLastLeague } from '../../lastLeague'
import { C, T } from '../../theme'

/* Openable means the draw actually exists to look at — the dashboard's own
   test, so the tab cannot offer a tournament whose bracket is unreleased. */
const hasDrawData = t => t.status === 'completed' || !!t.draw_released_direct_at

/* THE TAB BAR'S OWN HEIGHT ARITHMETIC, because it has to be reproduced to be
   trimmed. getTabBarHeight() returns TABBAR_HEIGHT_UIKIT + insets.bottom and
   only a NUMERIC height in tabBarStyle overrides it — which is why setting
   paddingBottom alone changed nothing visible: the padding shrank inside a bar
   that stayed exactly as tall.

   49 is that constant, module-private in @react-navigation/bottom-tabs 7.18,
   so it is copied here rather than imported. It is the icon-and-label box; it
   is NOT touched, so nothing clips at any text size — the only thing trimmed
   is the home-indicator inset below it. */
const TAB_CONTENT_H = 49
/* Enough to clear the indicator (~8pt up, ~5pt tall) and no more. A notched
   phone hands us 34, which is generous for a gap whose whole job is to keep
   labels off a 5pt line. */
const TAB_BOTTOM_MAX = 12

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
  /* Read rather than hardcoded: the inset is 34 on a notched phone and 0 on a
     flat one, so a fixed number would either waste the space on one or bury
     the labels on the other. Capped, not subtracted, so the result is the same
     deliberate gap on every device. */
  const insets = useSafeAreaInsets()
  const tabBottom = Math.min(insets.bottom, TAB_BOTTOM_MAX)
  const [picking, setPicking] = useState(false)
  const showing = useCurrentDraw()
  const lastLeague = useLastLeague()
  const pathname = usePathname()
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
          // BOTH, or neither works: height is what the bar measures itself by,
          // paddingBottom is where that height goes.
          height: TAB_CONTENT_H + tabBottom,
          paddingBottom: tabBottom,
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
          /* No navigation header: the screen's own tinted box carries the
             tour and the tournament name, and a bar repeating the name above
             it made the top of the screen two rows saying one thing. */
          headerShown: false,
          tabBarIcon: ({ color, size }) => <BracketIcon size={size ?? 22} color={color} />,
          href: drawId != null ? `/draw/${drawId}` : null,
        }}
      />
      {/* STRAIGHT TO THE LEAGUE LAST READ, not to a list of them. For most
          accounts that list is one or two rows standing in front of the thing
          the tab is for; the league's own name at the top is the way to
          another (leaguePicker). Same shape as the Draw tab above: prevent
          the default, go somewhere real, and keep an href so the tab is still
          a tab.
          Until the keychain answers (`loaded`), and for anyone with no
          remembered league — a new account, a fresh install — the press falls
          through to the list, which is also where creating and joining
          live. */}
      <Tabs.Screen
        name="leagues"
        listeners={{
          tabPress: e => {
            if (lastLeague.loaded && lastLeague.id != null) {
              e.preventDefault()
              // Already reading it: a second press must not stack a second
              // copy of the same screen behind the first.
              if (pathname !== `/league/${lastLeague.id}`) {
                router.push(`/league/${lastLeague.id}`)
              }
            }
          },
        }}
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
          {/* THE TICK BELONGS TO THE NAME, not to the row. Pushed out to the
              far edge it read as a column of its own, a long way from the
              thing it marks; beside the name it says "this one" (owner,
              2026-09-12). The group takes the slack so the badge still sits
              right, and the name shrinks before the tick does. */}
          <View style={s.nameWrap}>
            <Text style={s.name} numberOfLines={1}>{t.name}</Text>
            {t.id === showing
              ? <Ionicons name="checkmark" size={16} color={C.greenBright} />
              : null}
          </View>
          {/* The app's own badge, not a second one: same pill, same two
              colours as every draw card and bracket header. */}
          <TourBadge gender={t.gender} />
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
  /* The name and its tick, as one group: flex so it takes the row's slack,
     shrink on the TEXT so a long tournament name gives way before the tick
     does. */
  nameWrap: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 6 },
  name: { ...T.bodyMed, color: C.ink, flexShrink: 1 },
  none: { ...T.smallMed, color: C.muted, textAlign: 'center', paddingVertical: 12 },
}
