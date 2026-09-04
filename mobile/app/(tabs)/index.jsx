/*
 * The dashboard — what needs your attention, in that order.
 *
 * Not a directory. The website's home page can afford four equal sections side
 * by side; a phone cannot, so this ranks by what it costs you to miss:
 *
 *   1. Draws open for picks   — a deadline you can actually miss
 *   2. Draws playing          — nothing to do, but you want to know where you are
 *   3. Next week / last week  — context, one line each
 *
 * TWO DEPARTURES FROM THE WEBSITE, both because a phone is not a desktop:
 *
 * - ATP and WTA are ONE list, tinted, not two columns. Splitting by tour halves
 *   the width and buys nothing when there is only one column to begin with.
 * - Your standing is on this screen. The web home page never shows it, and it
 *   is the thing most worth knowing without opening anything.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { Redirect } from 'expo-router'
import { Ionicons } from '@expo/vector-icons'
import { Animated, Easing, Pressable, StyleSheet, Text, View } from 'react-native'
import { useAuth } from '../../auth'
import { getDrawStandings, getEntryStatus, listTournaments } from '../../api'
import { useApi } from '../../useApi'
import { computeCohortInfo, getHomeSection } from '../../drawStatus'
import { lockLabel } from '../../lock'
import { C, R, S, T } from '../../theme'
import { StatusChip, SurfacePill, TourCard } from '../../cards'
import { dateRange } from '../../dates'
import { Button, Card, CardLink, ErrorNote, Eyebrow, Loading, Muted, Screen, Title } from '../../ui'
import { MenuSheet } from '../../menu'
import { FONT_SCALE, leading } from '../../fontScale'

/* The site's rule for whether a card is a link at all: a draw that is neither
   completed nor released has nothing to show, and a live link to an empty draw
   reads as a broken page. */
const hasDrawData = t => t.status === 'completed' || !!t.draw_released_direct_at

/* "Order of Play" from a card, keyed on oop_first_seen_at rather than oop_url:
   the URL holds only today's file and goes null overnight and between rounds,
   so a link keyed on it would blink in and out. Once a tournament has published
   an order of play, it has one. No date in the link, deliberately — the
   schedule lands on the right day itself. */
const oopHref = t => (t.oop_first_seen_at && t.tournament_id
  ? { pathname: '/schedule', params: { tournament: t.tournament_id, draw: t.id } }
  : null)

/* The site's footer tracks for a running or finished draw: a state pill, a
   star when this reader is competing, and the order of play. */
function ActionRow({ t, state, pickState, starLabel }) {
  const oop = oopHref(t)
  return (
    <View style={s.actions}>
      <StatusChip tone="muted">{state}</StatusChip>
      {pickState === 'complete' ? (
        <View style={s.star} accessibilityLabel={starLabel}>
          <Ionicons name="star" size={13} color={C.greenLit} />
        </View>
      ) : <View />}
      {oop ? (
        // CardLink, not <Link asChild><Pressable style>: that form drops the
        // style — the pill rendered as bare text — and it is the trap CardLink
        // exists to close. Third time it has been re-typed; last time.
        <CardLink href={oop} style={s.oop} pressedOpacity={0.7}>
          <Text style={s.oopText}>Order of Play</Text>
        </CardLink>
      ) : (
        <Text style={[s.oopText, { color: C.faint, opacity: 0.6 }]}>Order of Play</Text>
      )}
    </View>
  )
}

export default function Dashboard() {
  const { phase, me, retry, error: authError } = useAuth()
  const ready = phase === 'ready'

  const tours = useApi(ready ? 'tournaments' : null, listTournaments, { enabled: ready })
  const entry = useApi(ready ? 'entry-status' : null, getEntryStatus, { enabled: ready })

  // A clock so countdowns tick without refetching anything. Thirty seconds is
  // plenty for a label whose smallest unit is a minute.
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30000)
    return () => clearInterval(id)
  }, [])

  const all = useMemo(() => tours.data || [], [tours.data])
  const buckets = useMemo(() => {
    // computeCohortInfo needs EVERY draw — clustering a filtered list moves the
    // "Last Week" boundary.
    const cohort = computeCohortInfo(all)
    const of = k => all.filter(t => getHomeSection(t, cohort) === k)
    return { open: of('open'), active: of('active'), upcoming: of('upcoming'), lastweek: of('lastweek') }
  }, [all])

  const refetch = () => { tours.refetch(); entry.refetch() }

  if (phase === 'boot') return <Loading />
  if (phase === 'signedout') return <Redirect href="/sign-in" />

  if (phase === 'unreachable') {
    return (
      <Screen>
        <Head />
        <Card>
          <Title>Can’t reach Upset Alert</Title>
          <Muted>
            You’re still signed in — this is a connection problem, not a
            sign-out. Your session is untouched.
          </Muted>
          {!!authError && <Muted>{authError}</Muted>}
          <Button label="Retry" onPress={retry} />
        </Card>
      </Screen>
    )
  }

  const loading = tours.loading && !tours.data
  const empty = !loading && !buckets.open.length && !buckets.active.length
    && !buckets.upcoming.length && !buckets.lastweek.length

  return (
    <Screen onRefresh={refetch}>
      <Head />

      <ErrorNote error={tours.error} onRetry={refetch} />
      {loading ? <Loading /> : null}

      <Section title="Pick now" tone={C.clay}>
        {buckets.open.map(t => (
          <OpenCard key={t.id} t={t} status={entry.data?.[t.id]} now={now} />
        ))}
        {!buckets.open.length && !loading && (
          <Muted>Nothing open. A draw appears here the moment it’s released.</Muted>
        )}
      </Section>

      {buckets.active.length > 0 && (
        <Section title="Playing" tone={C.greenLit}>
          {buckets.active.map(t => <ActiveCard key={t.id} t={t} userId={me?.id} pickState={entry.data?.[t.id]} />)}
        </Section>
      )}

      {buckets.upcoming.length > 0 && (
        <Section title="Next week" tone={C.muted}>
          {buckets.upcoming.map(t => <CompactRow key={t.id} t={t} />)}
        </Section>
      )}

      {buckets.lastweek.length > 0 && (
        <Section title="Last week" tone={C.muted}>
          {buckets.lastweek.map(t => <CompactRow key={t.id} t={t} done />)}
        </Section>
      )}

      {empty && (
        <Card>
          <Title>Nothing on right now</Title>
          <Muted>The tour is between events. Draws appear here as they’re released.</Muted>
        </Card>
      )}

    </Screen>
  )
}

/* A profile button, as on the site, rather than the username spelled out.
   The name told the reader something they already knew — whose phone this is —
   and it was the widest thing on the row after the wordmark. The circle goes
   somewhere; the text went nowhere. */
/* The site's brand dot: a 12px clay circle whose ring breathes from 3px to
   6px every 2.8 s (Navbar.css, logo-ring-pulse). There are no box-shadow
   rings in React Native, so the ring is a second circle behind the dot,
   scaled and faded on the native driver — nothing re-renders per frame. */
function BrandDot() {
  const ring = useRef(new Animated.Value(0)).current
  useEffect(() => {
    const loop = Animated.loop(Animated.sequence([
      Animated.timing(ring, { toValue: 1, duration: 1400, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
      Animated.timing(ring, { toValue: 0, duration: 1400, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
    ]))
    loop.start()
    return () => loop.stop()
  }, [ring])
  return (
    <View style={s.dotWrap}>
      <Animated.View style={[s.dotRing, {
        opacity: ring.interpolate({ inputRange: [0, 1], outputRange: [0.15, 0.42] }),
        transform: [{ scale: ring.interpolate({ inputRange: [0, 1], outputRange: [0.75, 1] }) }],
      }]} />
      <View style={s.dot} />
    </View>
  )
}

function Head() {
  const [menu, setMenu] = useState(false)
  return (
    <View style={s.head}>
      {/* The hamburger, top-LEFT (moved 2026-09-04 at the user's request):
          Draw History, Hall of Fame, Rules, About. */}
      <Pressable onPress={() => setMenu(true)} style={({ pressed }) => [s.avatar, pressed && { opacity: 0.7 }]}
                 accessibilityRole="button" accessibilityLabel="Menu">
        <Ionicons name="menu" size={20} color={C.inkBody} />
      </Pressable>
      {/* The site's wordmark, exactly: pulsing dot, UPSET ALERT! with only
          ALERT in clay (the "!" is white), and the slogan centred beneath.
          Centred between the two buttons, as the navbar centres it. */}
      <View style={s.brandBlock}>
        <View style={s.brandTop}>
          <BrandDot />
          <Text style={s.brand} numberOfLines={1}>
            UPSET <Text style={{ color: C.clay }}>ALERT</Text>!
          </Text>
        </View>
        <Text style={s.slogan} numberOfLines={1}>Your Wildest Fantasy Tennis</Text>
      </View>
      {/* CardLink, not <Link asChild><Pressable style=...>. That second form
          drops the style — it is the same trap CardLink exists to close, and I
          walked straight back into it: the ring simply did not draw and the
          icon floated in the header. */}
      <CardLink href="/status" style={s.avatar} pressedOpacity={0.7}>
        <Ionicons name="person-outline" size={18} color={C.inkBody} />
      </CardLink>
      <MenuSheet visible={menu} onClose={() => setMenu(false)} />
    </View>
  )
}

/* No count. A number floating at the end of the rule said only how many cards
   were already visible directly beneath it — the reader can see that, and it
   read as a badge that meant something. */
function Section({ title, tone, children }) {
  return (
    <View style={s.section}>
      <View style={s.sectionHead}>
        <Eyebrow color={tone}>{title}</Eyebrow>
        <View style={s.rule} />
      </View>
      {children}
    </View>
  )
}

/* "Sep 21 – 27", the site's date range in its mono face, right-aligned in the
   meta row so it reads as the third item in a summary rather than a heading. */

function Meta({ t, showSurface = true }) {
  return (
    <View style={s.meta}>
      {t.city ? (
        <Text style={[T.smallMed, { color: C.inkBody, flexShrink: 1 }]} numberOfLines={1}>
          {t.city}
        </Text>
      ) : null}
      {showSurface ? <SurfacePill surface={t.surface} /> : null}
      {dateRange(t) ? (
        <Text style={[T.tiny, { color: C.muted, marginLeft: 'auto' }]}>{dateRange(t)}</Text>
      ) : null}
    </View>
  )
}

/* The only card with something to DO, so the countdown is the loudest thing
   on it — that is the part you can miss. */
function OpenCard({ t, status, now }) {
  const lock = lockLabel(t, now)
  const chip = status === 'complete' ? ['good', 'Picks in']
    : status === 'partial' ? ['warn', 'Picks incomplete']
    : ['bad', 'Not entered']

  return (
        <TourCard
          tour={t.gender === 'F' ? 'WTA' : 'ATP'} tier={t.category} name={t.name}
          href={hasDrawData(t) ? `/draw/${t.id}` : null}
          footer={
            <View style={s.footRow}>
              {lock ? (
                <View style={s.lockLine}>
                  <Text style={[T.score, { color: lock.urgent ? C.clay : C.ink }]}>{lock.value}</Text>
                  <Text style={[T.tiny, { color: C.faint }]}>{lock.suffix}</Text>
                </View>
              ) : <View />}
              <StatusChip tone={chip[0]}>{chip[1]}</StatusChip>
            </View>
          }
        >
          <Meta t={t} />
        </TourCard>
  )
}

/* Playing: nothing to do, so the only question is where you stand. */
function ActiveCard({ t, userId, pickState }) {
  const standings = useApi(`standings:${t.id}`, () => getDrawStandings(t.id))
  const rows = standings.data || []
  const mine = rows.find(r => r.user?.id === userId)

  return (
        <TourCard
          tour={t.gender === 'F' ? 'WTA' : 'ATP'} tier={t.category} name={t.name}
          href={hasDrawData(t) ? `/draw/${t.id}` : null}
          footer={
            <View style={{ gap: 8 }}>
            <View style={s.footRow}>
              {mine ? (
                <CardLink href={`/standings/${t.id}`} style={s.lockLine} pressedOpacity={0.6}>
                  <Text style={[T.score, { color: C.ink }]}>{ordinal(mine.rank)}</Text>
                  <Text style={[T.tiny, { color: C.faint }]}>of {rows.length}</Text>
                  <Ionicons name="chevron-forward" size={13} color={C.faint} />
                </CardLink>
              ) : (
                <Text style={[T.tiny, { color: C.faint }]}>
                  {standings.loading ? '' : 'Not entered'}
                </Text>
              )}
              {/* The SURFACE here, not "29 right · 29 pts". Those two numbers
                  restate the standing immediately to their left — "29th of 29"
                  already says how it is going — while the surface is the one
                  thing about the event this card was not showing anywhere. */}
              <SurfacePill surface={t.surface} />
            </View>
            {/* The site's row: Closed, the Competing star, Order of Play. */}
            <ActionRow t={t} state="Closed" pickState={pickState} starLabel="Competing" />
            </View>
          }
        >
          <Meta t={t} showSurface={false} />
        </TourCard>
  )
}

/* Next/last week: one line, because that is what they are worth. The tour dot
   carries the only thing that distinguishes them at a glance. */
function CompactRow({ t, done }) {
  const isATP = t.gender !== 'F'
  /* Upcoming: the site shows WHEN THE DRAW COMES OUT, which is the only thing
     a reader can act on before it does — the date range says nothing they
     need yet. Last week: the order of play still matters (results), so it
     keeps its link; the row itself opens the draw. */
  const rel = !done ? [
    t.draw_release_direct && `Draw ${fmtShort(t.draw_release_direct)}`,
    t.draw_release_qualifiers && `Qual ${fmtShort(t.draw_release_qualifiers)}`,
  ].filter(Boolean).join(' · ') : ''
  const oop = done ? oopHref(t) : null
  const body = (
    <>
      <View style={[s.compactDot, { backgroundColor: isATP ? C.atp : C.wta }]} />
      <Text style={[T.small, { color: done ? C.muted : C.inkBody, flex: 1 }]} numberOfLines={1}>
        {t.name}
      </Text>
      <Text style={[T.tiny, { color: C.faint }]} numberOfLines={1}>{rel || dateRange(t)}</Text>
    </>
  )
  // A row that has no draw yet is not a link — the site's rule. The order-of
  // play icon is a SIBLING of the row link, never inside it.
  const inner = hasDrawData(t)
    ? <CardLink href={`/draw/${t.id}`} style={s.compactBody} pressedOpacity={0.7} grow>{body}</CardLink>
    : <View style={[s.compactBody, { flex: 1 }]}>{body}</View>
  return (
    <View style={s.compact}>
      {inner}
      {oop ? (
        <CardLink href={oop} style={s.oopMini} pressedOpacity={0.6}>
          <Ionicons name="calendar-outline" size={14} color={C.greenLit} />
        </CardLink>
      ) : null}
    </View>
  )
}

// "Sep 5" — the release-date form the site's upcoming cards use.
const fmtShort = iso => {
  const d = new Date(`${iso}T12:00:00`)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

/* 1st, 2nd, 3rd, 4th… The server sends `rank` already computed across the whole
   board — competition ranking, ties sharing a place — so this only formats it.
   Recomputing here would be a second opinion on the same question. */
function ordinal(n) {
  if (n == null) return '—'
  const suf = ['th', 'st', 'nd', 'rd']
  const v = n % 100
  return n + (suf[(v - 20) % 10] || suf[v] || suf[0])
}


const s = StyleSheet.create({
  head: {
    // Centred, not baseline: the row opens with a 36px circle, and a
    // baseline row hung the wordmark off the circle's bottom edge.
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    gap: S.sm, paddingTop: S.sm, paddingBottom: S.xs,
  },
  brandBlock: { flex: 1, alignItems: 'center', minWidth: 0 },
  brandTop: { flexDirection: 'row', alignItems: 'center', gap: 9 },
  // Tight leading on the wordmark: the display face's default line box left
  // a gap under the caps that pushed the slogan away from it.
  brand: { ...T.display, lineHeight: leading(27), color: C.ink },
  // Navbar.css .navbar-brand-slogan, a size down and tucked right under the
  // wordmark (user, 2026-09-04). fontStyle as well as the italic face: if the
  // face is ever not loaded, the system fallback still slants.
  slogan: {
    fontFamily: 'Archivo_400Regular_Italic', fontStyle: 'italic', fontSize: 11, lineHeight: leading(13),
    // The lift is a line, not a ratio: measured at text scale 1.0 (+2, any
    // higher and the slogan climbs into the letters) and at the phone's 1.7
    // (-10, any lower and a gap opens), and interpolated between. The room it
    // closes is the wordmark's descender space, which grows faster than the
    // slogan does, so a plain scaled offset fit one size and not the other.
    letterSpacing: 0.9, color: C.muted, textAlign: 'center', marginTop: Math.round(19 - 17 * FONT_SCALE),
  },
  // A size up from the site's 12px, and lifted: the row centres the dot on
  // the wordmark's line box, whose centre sits below the caps' centre (the
  // box keeps room for descenders the caps never use).
  dotWrap: { width: 30, height: 30, alignItems: 'center', justifyContent: 'center', marginTop: -leading(3) },
  dotRing: { position: 'absolute', width: 30, height: 30, borderRadius: 15, backgroundColor: C.clayLight },
  dot: { width: 15, height: 15, borderRadius: 7.5, backgroundColor: C.clayLight },
  avatar: {
    width: 36, height: 36, borderRadius: 18,
    // borderOn, not border: C.border on C.card is a 1.1:1 edge and the circle
    // simply was not there — the icon looked like it was floating in the
    // header. The site draws a visible ring around its profile button.
    borderWidth: 1, borderColor: C.borderOn, backgroundColor: C.card,
    alignItems: 'center', justifyContent: 'center',
  },

  section: { gap: S.sm, marginTop: S.md },
  sectionHead: { flexDirection: 'row', alignItems: 'center', gap: S.sm },
  rule: { flex: 1, height: 1, backgroundColor: C.border },

  meta: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  footRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: S.sm },
  lockLine: { flexDirection: 'row', alignItems: 'baseline', gap: 5 },

  compact: {
    flexDirection: 'row', alignItems: 'center',
    backgroundColor: C.card, borderRadius: R.md, borderWidth: 1, borderColor: C.border,
    overflow: 'hidden',
  },
  compactBody: {
    flex: 1, flexDirection: 'row', alignItems: 'center', gap: S.sm,
    paddingVertical: S.sm, paddingHorizontal: S.md,
  },
  compactDot: { width: 6, height: 6, borderRadius: 3 },
  actions: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: S.sm },
  star: { paddingHorizontal: 4 },
  oop: {
    borderRadius: R.pill, borderWidth: 1, borderColor: C.borderOn, backgroundColor: C.raised,
    paddingHorizontal: 10, paddingVertical: 4,
  },
  oopText: { ...T.tiny, color: C.greenLit, letterSpacing: 0.3 },
  oopMini: { paddingHorizontal: S.md, alignSelf: 'stretch', justifyContent: 'center' },

  footer: {
    flexDirection: 'row', gap: S.lg, justifyContent: 'center', flexWrap: 'wrap',
    marginTop: S.xl, paddingTop: S.lg, borderTopWidth: 1, borderTopColor: C.border,
  },
  footerLink: { ...T.smallMed, color: C.muted },
})
