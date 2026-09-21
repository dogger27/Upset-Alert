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

import { router, Tabs, useGlobalSearchParams, usePathname } from 'expo-router'
import { useState } from 'react'
import { Pressable, Text, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { Ionicons } from '@expo/vector-icons'
import { BracketIcon } from '../../BracketIcon'
import { TourBadge } from '../../cards'
import { Sheet } from '../../sheet'
import { BrandMark, Eyebrow } from '../../ui'
import { useAuth } from '../../auth'
import { hasDrawData, useChoosableTournaments } from '../../choosableTournaments'
import { setCurrentDraw, useCurrentDraw } from '../../currentDraw'
import { GROUP_TONE, groupDrawsByStatus, showGroupHeadings } from '../../drawGroups'
import { useLastLeague } from '../../lastLeague'
import { pruneScheduleTournaments, setScheduleTournaments, useScheduleTournaments } from '../../scheduleFilter'
import { holdSelection } from '../../scheduleRows'
import { C, S, T } from '../../theme'

/* THE TAB BAR'S OWN HEIGHT ARITHMETIC, because it has to be reproduced to be
   trimmed. getTabBarHeight() returns TABBAR_HEIGHT_UIKIT + insets.bottom and
   only a NUMERIC height in tabBarStyle overrides it — which is why setting
   paddingBottom alone changed nothing visible: the padding shrank inside a bar
   that stayed exactly as tall.

   49 was that constant, module-private in @react-navigation/bottom-tabs 7.18
   and copied here rather than imported. It is the icon-and-label box.

   58 NOW, UP FROM 49 (owner, 2026-09-16: a taller bottom bar). This is the
   lever rather than TAB_BOTTOM_MAX below, and the difference matters: the
   inset's whole job is to keep labels off the home indicator, so raising it
   would add dead space under the bar without giving the icons or the labels a
   single point. The content box is where height becomes air — React
   Navigation centres the icon-and-label group inside it, so the extra 9pt
   lands as ~4.5 above and below, around a 22pt icon and an 11pt label that
   together were sitting in 12pt of padding.

   GROWING THIS IS THE SAFE DIRECTION, which is why the old note said not to
   touch it: 49 was the floor at which nothing clipped at the phone's largest
   text sizes. More room can only help that. */
const TAB_CONTENT_H = 58
/* Enough to clear the indicator (~8pt up, ~5pt tall) and no more. A notched
   phone hands us 34, which is generous for a gap whose whole job is to keep
   labels off a 5pt line. */
const TAB_BOTTOM_MAX = 12

/* THE BAR'S TOP EDGE, in green. It was a hairline in C.border — a grey barely
   separable from the page it sits on — so on a dark screen the navigation had
   no top at all (owner, 2026-09-12). greenLit rather than greenBright:
   brightest green is reserved for something that has to read FIRST, and this
   is structure, not text.

   ADDED TO THE HEIGHT, not taken out of it. Yoga counts the border inside an
   explicit height, so thickening the edge would otherwise have shaved a point
   off the 49pt icon-and-label box that is deliberately left alone — the one
   thing in this file's arithmetic that must not shrink, or a label clips at
   the phone's larger text sizes. */
const TAB_BORDER_H = 2

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
  /* WHICH TOURNAMENTS THE SCHEDULE SHOWS. A day's sheet can carry four of them
     and a hundred rows, so the tab asks before it opens — one or many, never
     none (scheduleFilter). Held here as a draft and published on close, so a
     half-made selection never filters the screen behind the sheet. */
  const [filtering, setFiltering] = useState(false)
  const chosen = useScheduleTournaments()
  const [draft, setDraft] = useState(null)
  const showing = useCurrentDraw()
  const lastLeague = useLastLeague()
  const pathname = usePathname()
  /* Gated on a real session, exactly as the dashboard gates it: the tabs can
     render for a beat while signed out, and an unauthenticated call here
     would 401 — which this app treats as "sign out". */
  const { phase } = useAuth()
  const ready = phase === 'ready'
  /* The one derivation, shared with the Schedule page's own checkboxes so the
     two controls can never offer different tournaments. */
  const { all, live, choosable, sectionOf } = useChoosableTournaments(ready)
  /* The chooser's rows, in their two groups. Not memoised: it is a filter over
     the handful of draws being played, and `live` is a fresh array on every
     render anyway, so a memo here would buy a comparison and no work. */
  const drawGroups = groupDrawsByStatus(live, sectionOf)
  const groupHeadings = showGroupHeadings(drawGroups)
  /* The tab's destination falls back past `live` to any released draw, so the
     bar keeps four tabs through an off-season week with nothing being played.
     The chooser still lists only what is live and says so when that is
     nothing — a tab that vanishes teaches people it might not be there. */
  const drawId = showing ?? live[0]?.id ?? all.find(hasDrawData)?.id ?? null
  /* Is the Schedule the page we are ON? That is what separates "take me
     there" from "let me change what I see there", and it is the whole of the
     rule below. */
  const onSchedule = pathname === '/schedule' || pathname.startsWith('/schedule/')
  /* THE SCHEDULE, PINNED TO ONE EVENT. Order of Play on a card whose
     tournament is neither open nor being played sends the reader to a page
     showing that event alone, with no chooser — there is nothing in the
     chooser's list to choose. A second press of this tab would otherwise open
     the sheet anyway: a control over nothing, since the pin outranks whatever
     it sets. The press releases the pin instead, which is the one thing a
     reader in that state could want from it. */
  const routeParams = useGlobalSearchParams()
  const scheduleParam = onSchedule && routeParams?.tournament != null
    ? Number(routeParams.tournament) : null
  const onDraw = pathname.startsWith('/draw/')
  /* The EVENT behind the bracket last opened — the US Open, not the US Open
     WTA, because the chooser and the filter both work in events. Null when
     that draw is no longer among the live ones, which is the off-season and
     the week-old draw alike; the schedule then shows everything, as before. */
  const readingDrawId = showing ?? null
  const readingTournamentId = readingDrawId != null
    ? all.find(t => t.id === readingDrawId)?.tournament_id ?? null
    : null
  const readingEventId = choosable.some(t => t.id === readingTournamentId)
    ? readingTournamentId
    : null
  /* Pinned once the DRAW LIST has arrived — not once `choosable` is non-empty,
     which is a different question wearing the same shape: an empty choosable
     set is the CORRECT answer in the off-season, so waiting for it to fill
     would mean never agreeing with the page. schedule.jsx keeps the same test,
     and had exactly this bug. */
  const schedulePinned = scheduleParam != null && all.length > 0
    && !choosable.some(t => t.id === scheduleParam)

  /* WHICH BRACKET THE DRAW TAB OPENS WITHOUT ASKING, or null to ask.

     One live draw is the easy half: a chooser holding one row is a gate in
     front of an open door, the same thing the Schedule tab stopped doing.

     The other half is the reader's own context. Filtering the Schedule to one
     tournament is a statement about what they are following, so the Draw tab
     honours it rather than re-asking (owner, 2026-09-14). A combined event
     still has two brackets under that one name — the bracket already being
     read wins, and failing that the men's, which is the order the header's
     tour switch uses, so the tab never picks a different half on different
     days. Either way the switch in the header is one tap to the other. */
  const soleFollowed = chosen?.size === 1 ? [...chosen][0] : null
  const followedDraws = soleFollowed != null
    ? live.filter(d => d.tournament_id === soleFollowed)
    : []
  const jumpTo = live.length === 1
    ? live[0].id
    : followedDraws.length
      ? (followedDraws.find(d => d.id === showing)
         ?? [...followedDraws].sort((a, b) => (a.gender === 'M' ? 0 : 1) - (b.gender === 'M' ? 0 : 1))[0]).id
      : null

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
          // The darker green: the lit one was a bright line across the whole screen (owner, 2026-09-17).
          borderTopColor: C.green,
          borderTopWidth: TAB_BORDER_H,
          // BOTH, or neither works: height is what the bar measures itself by,
          // paddingBottom is where that height goes. The border is inside that
          // height, so it is added on — see TAB_BORDER_H.
          height: TAB_CONTENT_H + tabBottom + TAB_BORDER_H,
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
        /* THE SHEET OPENS FROM THE SCHEDULE, NOT ON THE WAY TO IT.

           Arriving from a bracket, the question "which tournaments?" already
           has an answer — the one being read — so asking it is a gate in front
           of a door that was open. The press filters to that tournament and
           goes. A SECOND press, now that the tab is the page you are on, is
           the one that means "show me the others" and opens the chooser
           (owner, 2026-09-14).

           Still nothing to ask when there is nothing to choose between: one
           live event, or none, and the press goes straight through either way. */
        listeners={{
          tabPress: e => {
            if (schedulePinned) {
              e.preventDefault()
              // replace, not push: the pinned page is where we already are,
              // and a back button onto it would put the reader straight back.
              router.replace('/schedule')
              return
            }
            if (choosable.length < 2) return
            if (!onSchedule) {
              // Stale ids name nothing a week later; start from what is live.
              pruneScheduleTournaments(choosable.map(t => t.id))
              if (readingEventId != null) setScheduleTournaments(new Set([readingEventId]))
              return
            }
            e.preventDefault()
            setDraft(new Set(chosen ?? choosable.map(t => t.id)))
            setFiltering(true)
          },
        }}
        options={{ title: 'Schedule', headerShown: false, tabBarIcon: icon('calendar') }}
      />
      {/* The bracket, between the day's play and the people you play it with. */}
      <Tabs.Screen
        name="draw/[id]"
        /* ASK WHICH ONE — but only when there is genuinely a question. There
           is usually no single "the draw", two at every slam, so the default
           is a chooser rather than a guess; `jumpTo` above is the short list
           of cases where the answer is already known. The href still points
           somewhere real: it is what keeps the tab on the bar and gives the
           press a destination if this listener ever misses. */
        listeners={{
          tabPress: e => {
            e.preventDefault()
            /* A SECOND PRESS IS THE WAY TO ANOTHER BRACKET, the same rule the
               Schedule tab follows. Without this the chooser would be
               unreachable whenever `jumpTo` answers — and unlike the schedule,
               the draw header's tour switch only reaches the OTHER HALF of
               this event, never another tournament. */
            if (jumpTo != null && !(onDraw && live.length > 1)) {
              setCurrentDraw(jumpTo)
              router.push(`/draw/${jumpTo}`)
              return
            }
            setPicking(true)
          },
        }}
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
      {/* THE PUSHED SCREENS, inside the navigator so the bar survives them —
          the league, standings, Hall of Fame, rules, draw history, about.
          href:null keeps the group off the bar; it has its own stack, and its
          own headers and Back buttons, in (more)/_layout. */}
      <Tabs.Screen name="(more)" options={{ href: null, headerShown: false }} />
    </Tabs>

    {/* GROUPED BY STATUS (owner, 2026-09-19). The list answers two questions
        at once — which draws still take picks, and which are being played —
        and flat, four rows read as one undifferentiated list with the only
        deadline in it invisible. The two headings are the DASHBOARD's own
        words and colours, in its order, so this teaches no second vocabulary
        for the same fact. One group draws no heading at all: see
        drawGroups.showGroupHeadings. */}
    <Sheet visible={picking} onClose={() => setPicking(false)} title="Draws">
      {live.length ? drawGroups.map(g => (
        <View key={g.key}>
          {groupHeadings ? (
            <View style={s.groupHead}>
              <Eyebrow color={C[GROUP_TONE[g.key]] || C.muted}>{g.title}</Eyebrow>
              <View style={s.groupRule} />
            </View>
          ) : null}
          {g.draws.map((t, i) => (
            <DrawRow key={t.id} t={t} showing={showing}
                     /* The heading brought its own rule, so the first row
                        under one must not draw a second immediately below it. */
                     underHeading={groupHeadings && i === 0}
                     onPress={() => { setPicking(false); router.push(`/draw/${t.id}`) }} />
          ))}
        </View>
      )) : (
        <Text style={s.none}>No draws are being played right now.</Text>
      )}
    </Sheet>

    {/* WHICH TOURNAMENTS. One row per EVENT — the US Open is one entry with
        both badges, not two rows — because the ATP/WTA split is a control the
        screen already has and does not need repeating here (owner,
        2026-09-13). Closing applies the draft and goes to the schedule —
        Close is Done here, and tapping the scrim means the same thing rather
        than throwing the choice away.

        NEVER NONE, ENFORCED WHERE IT APPLIES rather than under the reader's
        finger. The rule is about what the SCHEDULE shows: a screen filtered
        to nothing is indistinguishable from a broken one. It used to be kept
        by refusing to untick the last row, which made Clear impossible and
        made one arbitrary row behave unlike its neighbours. An empty
        selection is simply the store's own word for "every tournament"
        (scheduleFilter turns an empty set into null), so the draft may now go
        empty and closing on it shows everything — the guarantee intact, and
        every row behaving the same way (owner, 2026-09-14). */}
    <Sheet visible={filtering} title="Select Tournament(s)"
           titleRight={
             <View style={s.titleActions}>
               <Pressable hitSlop={8} accessibilityRole="button"
                          disabled={!!draft && draft.size === choosable.length}
                          onPress={() => setDraft(new Set(choosable.map(t => t.id)))}>
                 <Text style={[s.action, draft && draft.size === choosable.length && s.actionOff]}>
                   Select all
                 </Text>
               </Pressable>
               <Pressable hitSlop={8} accessibilityRole="button"
                          disabled={!draft || draft.size === 0}
                          onPress={() => setDraft(new Set())}>
                 <Text style={[s.action, (!draft || draft.size === 0) && s.actionOff]}>Clear</Text>
               </Pressable>
             </View>
           }
           onClose={() => {
             setScheduleTournaments(draft && draft.size === choosable.length ? null : draft)
             setFiltering(false)
             // Only when the sheet was a detour. It now opens FROM the
             // schedule, where pushing it again just stacks a second copy of
             // the page the reader is already looking at.
             if (!onSchedule) router.push('/schedule')
           }}>
      {choosable.map(t => {
        const on = !!draft?.has(t.id)
        return (
          /* TAP TICKS, HOLD ISOLATES, HOLD THE LONE ONE FOR ALL (owner,
             2026-09-21) — the same gesture the Schedule's pills have, and the
             same rule (scheduleRows.holdSelection), because this sheet is the
             same list and a gesture that works on one and not the other is a
             gesture nobody trusts. The all case TICKS EVERY ROW rather than
             handing the store its null: this sheet shows its answer as
             checkboxes, and clearing them all to mean "everything" is the one
             thing its own Clear button already warns is confusing. */
          <Pressable key={t.id} style={s.row} accessibilityRole="button"
                     accessibilityState={{ selected: on }}
                     accessibilityHint={on && draft?.size === 1
                       ? 'Hold to choose every tournament'
                       : 'Hold to choose only this tournament'}
                     onLongPress={() => setDraft(holdSelection(draft, t.id)
                       ?? new Set(choosable.map(x => x.id)))}
                     delayLongPress={320}
                     onPress={() => setDraft(prev => {
                       const next = new Set(prev ?? [])
                       if (next.has(t.id)) next.delete(t.id)
                       else next.add(t.id)
                       return next
                     })}>
            <Text style={[s.name, s.nameGrow, !on && { color: C.faint }]} numberOfLines={1}>
              {t.name}
            </Text>
            {/* A BOX, NOT A BARE TICK. Beside the name a tick only ever
                appeared — there was nothing on an unselected row to say it
                COULD be selected, so the rows that were off read as inert
                text. An empty grey box is the affordance; the tick fills it.
                Parked on the right beside the badges, where the eye can run
                one column of states instead of hunting each one at the end of
                a name of a different length (owner, 2026-09-14). */}
            <View style={[s.check, on && s.checkOn]}>
              {on ? <Ionicons name="checkmark" size={14} color={C.bg} /> : null}
            </View>
            {/* Both halves of a combined event, men first. */}
            <View style={s.badges}>
              {t.genders.map(g => <TourBadge key={g} gender={g} />)}
            </View>
          </Pressable>
        )
      })}
    </Sheet>
    </>
  )
}

/* ONE DRAW IN THE CHOOSER. Its own component now that the list is grouped: the
   rows are drawn from inside a second map, and the alternative was this body
   nested two levels deep in the sheet. */
function DrawRow({ t, showing, underHeading, onPress }) {
  return (
    <Pressable style={[s.row, underHeading && s.rowUnderHeading]} accessibilityRole="button"
               /* The mark says "this one" to anyone who can see it; this
                  says it to anyone who cannot. Neither the tick before it
                  nor the logo now carries a label of its own — a mark that
                  means "current" is the ROW's state, not a thing in it. */
               accessibilityState={{ selected: t.id === showing }}
               onPress={onPress}>
      {/* The tour's colour is how the two halves of a combined event tell
          themselves apart everywhere else in the app; a list of draws is
          exactly where that matters most. */}
      <View style={[s.tint, { backgroundColor: t.gender === 'F' ? C.wta : C.atp }]} />
      {/* THE MARK BELONGS TO THE NAME, not to the row. Pushed out to the
          far edge it read as a column of its own, a long way from the
          thing it marks; beside the name it says "this one" (owner,
          2026-09-12). The group takes the slack so the badge still sits
          right, and the name shrinks before the mark does.

          THE BRAND DOT RATHER THAN A TICK (owner, 2026-09-16). A green
          checkmark is the app's "done/correct" mark — it grades a pick in
          the bracket, and it confirms a choice in four other sheets — so
          on this row it was answering a question nobody asked. The logo
          answers the right one: this is the draw you are in. It is also
          the one mark in the app that cannot mean anything else. */}
      <View style={s.nameWrap}>
        <Text style={s.name} numberOfLines={1}>{t.name}</Text>
        {t.id === showing ? <BrandMark size={16} /> : null}
      </View>
      {/* The app's own badge, not a second one: same pill, same two
          colours as every draw card and bracket header. */}
      <TourBadge gender={t.gender} />
    </Pressable>
  )
}


const s = {
  row: {
    flexDirection: 'row', alignItems: 'center', gap: 10,
    paddingVertical: 12, borderTopWidth: 1, borderTopColor: C.border,
  },
  rowUnderHeading: { borderTopWidth: 0 },
  /* The heading and the rule that runs off it — the dashboard's Section head,
     the same three numbers. */
  groupHead: { flexDirection: 'row', alignItems: 'center', gap: S.sm, paddingTop: S.sm },
  groupRule: { flex: 1, height: 1, backgroundColor: C.border },
  tint: { width: 3, height: 20, borderRadius: 2 },
  /* The heading's own controls. Small and quiet — they act on the list below
     rather than being the choice itself, so they read as tools beside the
     title, not as two more options in it. */
  titleActions: { flexDirection: 'row', alignItems: 'center', gap: 14 },
  action: { ...T.smallMed, color: C.clay },
  // Nothing left to do: dimmed rather than hidden, so the pair never reflows.
  actionOff: { color: C.faint },
  /* The DRAW chooser's name-and-tick group: flex so it takes the row's slack,
     shrink on the TEXT so a long tournament name gives way before the tick
     does. The tournament chooser below uses a checkbox in its own column
     instead, and needs only `nameGrow`. */
  nameWrap: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 6 },
  name: { ...T.bodyMed, color: C.ink, flexShrink: 1 },
  // The name takes the row's slack, so the box and the badges hold their
  // column whatever the tournament is called.
  nameGrow: { flex: 1 },
  /* The checkbox. Square, and sized in points rather than from the type
     scale: it is a control, not text, and a row of them has to line up. */
  check: {
    width: 20, height: 20, borderRadius: 4, borderWidth: 1.5,
    borderColor: C.border, alignItems: 'center', justifyContent: 'center',
  },
  // Filled when on, with the tick knocked out in the page's own dark — the
  // strongest reading of "yes" available without inventing a colour.
  checkOn: { backgroundColor: C.greenBright, borderColor: C.greenBright },
  // A combined event carries both badges, so they need a row of their own.
  badges: { flexDirection: 'row', gap: 4 },
  none: { ...T.smallMed, color: C.muted, textAlign: 'center', paddingVertical: 12 },
}
