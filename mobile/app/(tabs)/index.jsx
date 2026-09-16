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
import { getEntryStatus, listTournaments } from '../../api'
import { useApi } from '../../useApi'
import { computeCohortInfo, getHomeSection } from '../../drawStatus'
import { drawsByTournament } from '../../scheduleRows'
import { lockLabel } from '../../lock'
import { C, R, S, T } from '../../theme'
import { CardNav, FitText, StatusChip, SurfaceText, TourCard, useCardSkin } from '../../cards'
import { dateRange } from '../../dates'
import { Button, Card, CardLink, ErrorNote, Eyebrow, Loading, Muted, Screen, Title } from '../../ui'
import { MenuSheet } from '../../menu'
import { showToast } from '../../toast'
import { leading } from '../../fontScale'

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

/* The order of play, as the running card's one action.
 *
 * It used to sit on a third row beside a "Closed" chip and the Competing star.
 * Both of those went: "Closed" restated the ACTIVE header two lines above it
 * and the pick state the standing already implies, and the star moved to the
 * card's corner — which left this alone on a row of its own, so it moved up
 * beside the standing. The Active card now has the Open card's shape: meta,
 * then one footer row with the number on the left and the action on the right.
 *
 * Rendered greyed rather than dropped when a tournament has published no sheet
 * yet: the row keeps its shape, and the reader learns that there is nothing to
 * open rather than wondering where the link went. */
/* THE PILLS ARE GONE, all of them (owner, 2026-09-16). CardPill and its two
   callers — OrderOfPlay and DrawPill — were about 120 lines and four crossed
   decisions: available or not, loud section or quiet, the tour's ink family,
   and three alpha weights. Every one of those existed because a free-floating
   lozenge has to manufacture its own edges out of colour. CardNav's plates sit
   in a band that supplies the edges, so none of it was needed any more; the
   last call site was Next week's lone Schedule pill, and with that off the row
   the whole system is unreferenced. Kept: oopHref and oopDraw, which navItems
   uses to point the Schedule plate at a sheet. */

/* QUALIFYING IS UNDERWAY — and it is the EVENT's, not a draw's.
 *
 * qualifying_started_at comes off the tournaments list, computed server-side
 * from schedule_entries (stage='qualifying'), because qualifying is not in
 * `matches` at all: a 128 draw stores rounds 1-7, and a player who fails to
 * qualify never reaches draw_entries. The schedule row is the only record it
 * has. Both halves of a combined event report the same answer, so `some` and
 * `find` agree here.
 */
const qualifying = draws => draws.find(d => d.qualifying_started_at) || null

/* Straight to the schedule, filtered to this event. NO DATE PARAM on purpose:
   the schedule's own landing rule puts you on today, and if qualifying has
   started then today is a qualifying day. Keyed on tournament_id because that
   is what the schedule filters by — qualifying rows carry no draw_id, which is
   the whole reason the filter is on the event (see scheduleRows.js). */
const qualHref = t => (t?.tournament_id
  ? { pathname: '/schedule', params: { tournament: t.tournament_id } }
  : null)

/* THE LEAGUE FOR THIS EVENT. A standing is per DRAW, so a combined tournament
   has two of them and one bar — the same shape cardHref settled for the
   bracket, and settled the same way: the first draw with data, with the
   standings screen's own tour switch one tap from the other half. */
const leagueHref = draws => {
  const d = draws.find(hasDrawData) || draws[0]
  return d ? `/standings/${d.id}` : null
}

/* THE THREE DESTINATIONS, IN ONE PLACE, so Open, Active and Last week cannot
   drift apart in what they offer or in what order.

   ALL THREE APPEAR WHEREVER THE BAND DOES, including the ones with nothing
   behind them — an Open draw has no order of play published for days, and its
   Schedule plate sits translucent rather than absent. A plate that is not
   there changes the band's shape from card to card, which is the one thing a
   nav must not do. */
const navItems = draws => [
  { label: 'League', href: leagueHref(draws), a11y: 'League standings' },
  { label: 'Draw', href: cardHref(draws), a11y: 'Tournament draw' },
  /* "Sched", NOT "Schedule" (owner, 2026-09-16). The three plates now share a
     row with the city, and the full word costs 18pt of plate that the city
     needs: measured, the three come to 214pt with it and 196 without, which is
     the difference between the city having 101pt and 119. It is the one label
     here with an abbreviation everyone already reads. */
  { label: 'Sched', href: oopHref(oopDraw(draws)), a11y: 'Schedule and order of play' },
]

/* COMPETING, in the corner. On the footer row it was a bare star between two
   controls, reading as a third one; on the corner it is a stamp on the card,
   which is what it is — a fact about the whole draw, not an action in a row.
   Pressing it says so in words: a green star is a symbol nobody was taught,
   and the card it sits on opens the draw, so the star needs an answer of its
   own rather than borrowing the card's. hitSlop because the disc is 22pt and
   Apple's minimum is 44 — the ring is what you see, not what you have to hit. */
function CompetingStar() {
  /* THE DISC IS THE CARD'S OWN COLOUR. It sits half off the corner and has to
     close the border it crosses (see u.corner in cards.jsx), so a fixed
     C.card was a near-black blob pinned to a pink card — and the C.green ring
     around it measured 1.33:1 on that card: coloured enough to argue with the
     tint, too faint to read as a shape at all. Card colour, card ink, same
     rule as the button beside it. */
  const skin = useCardSkin()
  return (
    <Pressable onPress={() => showToast('You are competing!')} hitSlop={11}
               accessibilityRole="button" accessibilityLabel="Competing in this draw"
               style={({ pressed }) => [s.star,
                                        { backgroundColor: skin.card,
                                          borderColor: skin.ink + '80' },
                                        pressed && { opacity: 0.6 }]}>
      <Ionicons name="star" size={12} color={skin.ink} />
    </Pressable>
  )
}

export default function Dashboard() {
  const { phase, retry, error: authError } = useAuth()
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
    /* GROUPED BY EVENT, so a combined tournament is one card and not two
       identical ones (owner, 2026-09-15). Grouped AFTER the section split,
       because the two draws of an event can sit in different sections — a
       men's final does not retire the event while the women's is still on
       court, which is exactly what getHomeSection is careful about. An event
       playing in one tour and finished in the other therefore still shows a
       card in each section, each carrying the draws that belong there. */
    const of = k => drawsByTournament(all.filter(t => getHomeSection(t, cohort) === k))
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

      <Section title="Open" tone={C.clay}>
        {buckets.open.map(g => (
          <OpenCard key={g[0].id} draws={g} status={entry.data} now={now} />
        ))}
        {!buckets.open.length && !loading && (
          <Muted>No draws are open at this time.</Muted>
        )}
      </Section>

      {buckets.active.length > 0 && (
        <Section title="Active" tone={C.greenLit}>
          {buckets.active.map(g => (
            <ActiveCard key={g[0].id} draws={g} status={entry.data} />
          ))}
        </Section>
      )}

      {buckets.upcoming.length > 0 && (
        <Section title="Next week" tone={C.muted}>
          {buckets.upcoming.map(g => <CompactRow key={g[0].id} draws={g} />)}
        </Section>
      )}

      {buckets.lastweek.length > 0 && (
        <Section title="Last week" tone={C.muted}>
          {buckets.lastweek.map(g => <CompactRow key={g[0].id} draws={g} done />)}
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
        {/* ABSOLUTE, SO THE BUTTONS LINE UP WITH THE MARK (owner, 2026-09-16).
            An absolutely-positioned child adds nothing to its parent's height,
            so brandBlock now measures exactly the wordmark — and the row's
            alignItems:'center' therefore centres the two buttons on the
            WORDMARK rather than on a block that was also carrying this line.
            That is what put them about half a slogan too low.

            A STRUCTURE RATHER THAN AN OFFSET, deliberately: the alternative
            was a negative margin derived from the wordmark's line box and the
            button's fixed 36pt, and those two do not scale together — it would
            have been right at one text size and wrong at every other. This way
            the tuned -leading(12) below keeps meaning exactly what it meant,
            because it is still measured from the wordmark's own bottom. */}
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

/* THE SURFACE SITS ON THE ROW'S CENTRE LINE, not after the city.
 *
 * It used to follow the city directly, so it landed wherever that name
 * happened to end — Seoul put it near the left, Singapore most of the way
 * across — and a column of cards had the same pill in four places (owner,
 * 2026-09-15). A reader scanning for the surface was re-finding the control on
 * every row.
 *
 * Two FLEXIBLE side slots do it, rather than absolute positioning: they split
 * whatever the pill leaves equally, which puts the pill's centre on the row's
 * centre whatever the pill and the gaps measure. The city is left-aligned in
 * its slot and the dates right-aligned in theirs, so both keep the edges they
 * had — and each may use half the free width before it has to shrink, which
 * is more than either needs ("New York City" is the longest and it fits).
 */
function Meta({ t, showSurface = true }) {
  const inks = useCardSkin()
  return (
    <View style={s.meta}>
      <View style={s.metaSide}>
        {t.city ? (
          <Text style={[T.smallMed, { color: inks.inkBody }]} numberOfLines={1}>
            {t.city}
          </Text>
        ) : null}
      </View>
      {showSurface ? <SurfaceText surface={t.surface} /> : null}
      <View style={[s.metaSide, { alignItems: 'flex-end' }]}>
        {dateRange(t) ? (
          <Text style={[T.tiny, { color: inks.muted }]} numberOfLines={1}>{dateRange(t)}</Text>
        ) : null}
      </View>
    </View>
  )
}

/* THE DEADLINE AND THE PICK STATE, PER DRAW. Both belong to the draw and not
   to the event: the two halves of a combined tournament can close at different
   times (the men's first match can be a day before the women's, which is the
   whole reason closing_time is per draw), and picks can be in for one and not
   the other. So a combined card shows this row twice, each labelled with its
   tour, rather than picking one draw's answer to stand for both. */
const pickChip = status => (status === 'complete' ? ['good', 'Picks in']
  : status === 'partial' ? ['warn', 'Picks incomplete']
  : ['bad', 'Not entered'])

function OpenRow({ draws, status, now, label }) {
  const lock = lockLabel(draws[0], now)
  const chip = pickChip(status?.[draws[0].id])
  const inks = useCardSkin()
  return (
    <View style={s.footRow}>
      <View style={s.lockLine}>
        {label ? <Text style={[s.footTour, { color: inks.faint }]}>{label}</Text> : null}
        {lock ? (
          <>
            {/* URGENT STAYS CLAY. It is the brand's one warm note and it reads
                on either card; the ramp is for the ink that is merely quiet. */}
            <Text style={[T.score, { color: lock.urgent ? C.clay : inks.ink }]}>{lock.value}</Text>
            <Text style={[T.tiny, { color: inks.faint }]}>{lock.suffix}</Text>
          </>
        ) : null}
      </View>
      <StatusChip tone={chip[0]}>{chip[1]}</StatusChip>
    </View>
  )
}

/* ONE LINE PER DISTINCT ANSWER.
 *
 * The two halves of an event usually agree — both finished, both opening on
 * the same day — and a row repeated word for word with a tour pill in front of
 * it is two rows saying one thing (owner, 2026-09-15). So the facts are
 * grouped by what they SAY: one line when they agree, one line each when they
 * do not, and a tour label only on the second kind, where it is the only thing
 * telling them apart.
 */
function distinctBy(draws, say) {
  const out = []
  for (const d of draws) {
    const text = say(d)
    const seen = out.find(r => r.text === text)
    if (seen) seen.draws.push(d)
    else out.push({ text, draws: [d] })
  }
  return out
}

/* "ATP", "WTA", or both — the tours a row covers. Plain text, not the pill:
   the pill is a badge for a heading and this is a label on a line of small
   type, where a filled box outweighs the fact it is labelling. */
const tourWord = draws => draws.map(d => (d.gender === 'F' ? 'WTA' : 'ATP')).join(' · ')

/* THE ORDER OF PLAY IS THE EVENT'S, not the draw's. oopHref keys the link on
   tournament_id, so both halves of a combined event linked to the same page:
   two buttons, same destination, one above the other. The first half with a
   sheet supplies it, and if none has one the greyed label still appears, which
   is how a reader learns there is nothing to open yet. */
const oopDraw = draws => draws.find(d => oopHref(d)) || draws[0]

/* WHICH DRAW A CARD OPENS. One draw: its own bracket, as ever. A combined
   event: the men's, arbitrarily but predictably — drawsByTournament puts it
   first, and the draw screen's own ATP/WTA switch is one tap from the other
   half. The alternative, a card that is not a link at all, would take the
   bracket two taps away from every Slam. */
const cardHref = draws => {
  const open = draws.find(hasDrawData)
  return open ? `/draw/${open.id}` : null
}

/* The only card with something to DO, so the countdown is the loudest thing
   on it — that is the part you can miss. */
function OpenCard({ draws, status, now }) {
  /* The deadline AND the pick state together: two halves that lock at the same
     minute can still differ in whether your picks are in, and either one
     differing is a reason to show both lines. */
  const rows = distinctBy(draws, d => {
    const lock = lockLabel(d, now)
    return `${lock ? `${lock.value} ${lock.suffix}` : ''}|${pickChip(status?.[d.id])[1]}`
  })
  return (
        <TourCard
          draws={draws} name={draws[0].name} href={cardHref(draws)}
          footer={
            /* THE CONTROLS SIT OUTSIDE THE STACK because they belong to the
               EVENT and the rows belong to the draws: a combined tournament
               whose halves lock at different times has two rows and still one
               draw to open. No Schedule pill here — an Open draw is days from
               its first match and the tour has published no sheet, so the
               card would carry a control that is never anything but empty. */
            <View style={s.footStack}>
              {rows.map(r => (
                <OpenRow key={r.draws[0].id} draws={r.draws} status={status} now={now}
                         label={rows.length > 1 ? tourWord(r.draws) : null} />
              ))}
            </View>
          }
        >
          <Meta t={draws[0]} />
        </TourCard>
  )
}

/* NO STANDING ON THE CARD ANY MORE (owner, 2026-09-16, "remove the 4th of 8
   completely"). ActiveRow went with it, and with ActiveRow went a
   getDrawStandings call PER DRAW — one or two network requests per Active card
   on every dashboard load, for one ordinal. The League band is where a
   standing is read now, and it costs nothing until it is pressed. */

/* Active: nothing to do and nothing to say, so the card is its name, its
   place and its band. */
function ActiveCard({ draws, status }) {
  /* COMPETING IN THE EVENT, which is what the corner stamp claims: picks in
     for either half of a combined tournament means you are in it. Which half
     is in the rows below, where a standing says it better than a star. */
  const competing = draws.some(d => status?.[d.id] === 'complete')
  return (
        <TourCard
          draws={draws} name={draws[0].name} href={cardHref(draws)}
          corner={competing ? <CompetingStar /> : null}
        >
          {/* The surface sits beside the city, exactly as it does on an Open
              card — one line up from the footer it used to share with the
              standing (owner, 2026-09-15). The two cards differ now only in
              what their footer says, which is the point: a draw you are
              playing and a draw you are watching should not look like two
              different kinds of thing. */}
          <Meta t={draws[0]} />
        </TourCard>
  )
}

/* TEMPORARY, AND MEANT TO BE (owner, 2026-09-15, "for testing purposes"):
   Next week and Last week render as full cards, the same size and shape as an
   Active one, instead of the single line they are worth. Flip this back to
   false — the compact row below is untouched and takes over again — or revert
   the commit that added it. Worth keeping around while it is on: these two
   buckets are where the ATP cards and the slam crests live, so they are the
   only place on this screen the blue tint and an untinted crest can be seen
   at all. */
const WEEK_ROWS_AS_CARDS = true

/* Next/last week: one line, because that is what they are worth. The tour dot
   carries the only thing that distinguishes them at a glance. */
function CompactRow({ draws, done }) {
  const t = draws[0]
  if (WEEK_ROWS_AS_CARDS) return <WeekCard draws={draws} done={done} />
  /* Upcoming: the site shows WHEN THE DRAW COMES OUT, which is the only thing
     a reader can act on before it does — the date range says nothing they
     need yet. Last week: the order of play still matters (results), so it
     keeps its link; the row itself opens the draw. */
  /* One date, in the reader's terms: when picks OPEN, which is the main
     draw's release. The qualifying draw's date stands in only when the main
     draw has none yet. "Draw · Qual" was two facts where one is wanted. */
  const opens = !done ? (t.draw_release_direct || t.draw_release_qualifiers) : null
  const rel = opens ? `Opens ${fmtShort(opens)}` : ''
  const oop = done ? oopHref(t) : null
  const body = (
    <>
      {/* A DOT PER TOUR, because the row is the EVENT: a combined tournament
          is one line here too, and the dots are the only thing on it that
          could say both halves are there. */}
      {draws.map(d => (
        <View key={d.id} style={[s.compactDot,
                                 { backgroundColor: d.gender !== 'F' ? C.atp : C.wta }]} />
      ))}
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

/* The week rows as full cards — see WEEK_ROWS_AS_CARDS. Meta and the footer
   row are the Active card's, not copies of them, so "the same formatting" is
   true by construction rather than by my matching two sets of styles. The
   footer's left slot carries the one fact each bucket has: when picks open for
   next week's draw, and the dates for last week's. */
function WeekCard({ draws, done }) {
  /* THE EARLIEST RELEASE, for the event. The two halves of a combined
     tournament can open a day apart and this card no longer has a row each to
     say so: it is a one-line summary now, and the first date is the one that
     changes what a reader does today. The draw page has the rest. */
  /* QUALIFYING TAKES OVER THE WHOLE CARD (owner, 2026-09-16). A next-week
     event whose qualifying has begun is the one case where this card has
     somewhere worth going: its draw is not out, so cardHref is null and the
     card was not a link at all. Now the whole card opens the qualifying
     schedule. */
  const qual = done ? null : qualifying(draws)
  return (
    <TourCard draws={draws} name={draws[0].name} compact
      href={qual ? qualHref(qual) : cardHref(draws)}
      /* LAST WEEK GETS THE BAR, NEXT WEEK DOES NOT (owner, 2026-09-16). Next
         week has nothing behind any of the three: no bracket, no standings
         without one, and no sheet — a bar of three dimmed segments is a
         control that only reports its own uselessness. Its single Schedule
         pill stays in the row instead. */

      /* AS THE FOOTER, not as the body's children — and the difference is not
         cosmetic. `href` makes the body a link, so a row placed inside it puts
         Order of Play's own link INSIDE that one: invalid HTML on the web
         build (the harness printed "<a> cannot contain a nested <a>") and a
         tap-ownership fight on native, where pressing the button could open
         the draw instead. The footer is a sibling inside the same frame, which
         is what it exists for. `compact` drops its rule and its padding, so it
         still reads as one card rather than two rows. */
      footer={
      <>
      {/* ONE ROW, NO RULE — the whole card is the name, its tier and this.
          The date range, the surface and "Finished" came off at the owner's
          ask (2026-09-15), and taking them off alone would have saved about
          four points: the city still held the meta row and the button still
          held the footer. Merging what is left is what actually makes these
          cards smaller than the ones above them, which is the difference the
          sections are for — a draw you can still pick is worth more room than
          one that opens next Saturday. */}
      <WeekRow draws={draws} qual={qual} done={done} />
      </>
      }
    />
  )
}

/* The week card's one row — ITS OWN COMPONENT, and not for tidiness.
 *
 * The card's ink comes from a context TourCard provides (see cards.jsx), and a
 * context is read by the component that ASKS for it, at its own place in the
 * tree. WeekCard sits ABOVE the provider — it is what renders the card — so
 * asking there would have handed it the neutral ramp on a pink card, which is
 * precisely the bug being fixed, reintroduced one level up. Bare <Text> in
 * WeekCard's JSX cannot ask at all. A component can, because it renders as a
 * child of the card it was passed to. OpenRow was already this shape for the
 * same structural reason; this one matches it.
 */
function WeekRow({ draws, qual, done }) {
  const inks = useCardSkin()
  return (
    <View style={s.weekRow}>
      {/* THE RELEASE DATE ON THE ROW'S CENTRE LINE, by the same two-flexible-
          slots arithmetic the surface pill uses on the cards above: the sides
          split what the middle leaves, so the middle's centre is the row's
          centre. It trailed the city before, which put it in four places
          down a column of four cards (owner, 2026-09-15). */}
      {/* THE CITY SHRINKS, THE PLATES DO NOT (owner, 2026-09-16: the city
          "always fits in its allotted space, on one line"). FitText measures
          the room it was given and scales the type by exactly the ratio
          needed — so "New York City" sits at its full 13pt with 119pt to play
          with, and a long one gives way rather than wrapping or being cut.
          The plates are flexShrink 0 for the same reason: a control that
          shrinks is a control nobody can hit.
          At 13pt the measured cities all fit (New York City 83pt, Rio de
          Janeiro 85, 's-Hertogenbosch 104), so the shrink is the safety net
          for Dynamic Type and for whatever the tour adds next, not a thing
          the reader normally sees working. */}
      <FitText style={[T.smallMed, { color: inks.inkBody }]}>
        {draws[0].city || ''}
      </FitText>
      {/* LAST WEEK GETS THE PLATES. Next week gets its dates, and — once
          qualifying is under way — a word for it, centred between the two.

          THE FULL RANGE, NOT "OPENS SEP 19" (owner, 2026-09-16). The release
          date answered "when can I pick", which is the right question for a
          card you cannot act on yet; the dates answer "when is this", which is
          what a week of context is for. dateRange is the same helper the Open
          and Active cards' meta row uses, so the two read alike. */}
      {done ? <CardNav items={navItems(draws)} /> : (
        <>
          {/* THE MIDDLE SLOT: the surface, or "Qualifying" while it is on.
              Centred by the two flexible sides — the city's slot and the
              dates' — which split whatever this leaves, so it lands at the
              same x as the surface on an Open or Active card (owner,
              2026-09-16). That is the point of putting it here: the three
              sections' cards then read down one column.

              QUALIFYING TAKES THE SLOT WHEN IT IS ON, rather than sitting
              beside the surface. Both were asked for centred and only one can
              be; a hard court is true all fortnight and qualifying is true for
              two days, so the news wins while it is news. It takes the loud
              step of the card's own ink ramp rather than a fixed accent — a
              colour chosen against one tint fights the other, which the
              Schedule button spent an afternoon proving. */}
          {qual
            ? <Text style={[T.tiny, { color: inks.ink }]} numberOfLines={1}>Qualifying</Text>
            : <SurfaceText surface={draws[0].surface} />}
          <View style={[s.weekSide, { alignItems: 'flex-end' }]}>
            {dateRange(draws[0]) ? (
              <Text style={[T.tiny, { color: inks.faint }]} numberOfLines={1}>
                {dateRange(draws[0])}
              </Text>
            ) : null}
          </View>
        </>
      )}
    </View>
  )
}

// "Sep 5" — the release-date form the site's upcoming cards use.
const fmtShort = iso => {
  const d = new Date(`${iso}T12:00:00`)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

const s = StyleSheet.create({
  head: {
    // Centred, not baseline: the row opens with a 36px circle, and a
    // baseline row hung the wordmark off the circle's bottom edge.
    // WHAT IT CENTRES ON is the wordmark, because the slogan is absolute and
    // leaves brandBlock measuring the mark alone — see the note at the slogan.
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    gap: S.sm, paddingTop: S.sm, paddingBottom: S.xs,
  },
  brandBlock: { flex: 1, alignItems: 'center', minWidth: 0 },
  brandTop: { flexDirection: 'row', alignItems: 'center', gap: 9 },
  // Tight leading on the wordmark: the display face's default line box left
  // a gap under the caps that pushed the slogan away from it.
  // The site's wordmark face: Saira Condensed BLACK (Navbar.css sets 900),
  // not the 700 the rest of the app's display text uses.
  brand: { ...T.display, fontFamily: 'SairaCondensed_900Black', lineHeight: leading(27), letterSpacing: 0.9, color: C.ink },
  // Navbar.css .navbar-brand-slogan, a size down and tucked right under the
  // wordmark (user, 2026-09-04). fontStyle as well as the italic face: if the
  // face is ever not loaded, the system fallback still slants.
  slogan: {
    fontFamily: 'Archivo_400Regular_Italic', fontStyle: 'italic', fontSize: 11, lineHeight: leading(13),
    // TUNED ON THE PHONE, NOT THE WEB HARNESS. react-native-web lays the
    // display face out in a different box from iOS: values that looked right
    // in tools/visual-diff.mjs left a ~20pt gap on the device (2026-09-04).
    // The room this closes is the wordmark's descender space, which scales
    // with the reader's text size, hence leading().
    letterSpacing: 0.9, color: C.muted, textAlign: 'center',
    /* OUT OF THE FLOW: top 100% is brandBlock's full height, which IS the
       wordmark's line box now that this line no longer adds to it, so the
       tuned margin is still measured from the mark's own bottom. left/right 0
       gives it the block's width to centre in.
       It ends about a point below the mark — the room it closes is the
       wordmark's descender space — so it needs no reservation in the header's
       padding, and the 36pt buttons still set the row's height. */
    position: 'absolute', top: '100%', left: 0, right: 0, marginTop: -leading(12),
  },
  // A size up from the site's 12px, and lifted: the row centres the dot on
  // the wordmark's line box, whose centre sits below the caps' centre (the
  // box keeps room for descenders the caps never use).
  dotWrap: { width: 30, height: 30, alignItems: 'center', justifyContent: 'center', marginTop: -leading(12) },
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
  // Equal shares of what the pill leaves — see the note at Meta. minWidth 0 so
  // a long city name shrinks inside its slot instead of widening it.
  metaSide: { flex: 1, minWidth: 0 },
  footRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: S.sm },
  /* One row per draw on a combined card, and exactly one row otherwise — so
     the single-draw card's footer is unchanged by the gap. It is the whole
     footer again now that the controls have moved into the bar below it, and
     minWidth 0 is what lets a long row shrink inside it rather than widen it. */
  footStack: { gap: S.sm, minWidth: 0 },
  /* A week card's whole body: city, release, order of play. CENTRED rather
     than baseline-aligned now — the order of play is a pill when a sheet
     exists and bare type when it does not, and a baseline puts a pill's text
     on the line at the cost of hanging its box below everything else. */
  weekRow: { flexDirection: 'row', alignItems: 'center', gap: S.sm },
  // Equal shares of what the release date leaves — see the note at WeekCard.
  weekSide: { flex: 1, minWidth: 0 },
  /* The tour on a footer row, as TYPE rather than a pill. A filled badge is
     for a heading; on a line of 11pt type it outweighed the fact it was
     labelling, and it was on every row of a combined card including the ones
     that said the same thing twice (owner, 2026-09-15). Fixed width so the
     facts beside it start at one x whichever tour it names. */
  footTour: { ...T.tiny, color: C.faint, letterSpacing: 0.5, width: leading(30) },
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
  /* THE CORNER STAMP. A filled disc in the card's own colour with a green
     ring: sitting half off the card, it has to close the border it crosses,
     and a transparent badge would have shown the card's edge running straight
     through the star. */
  star: {
    width: 22, height: 22, borderRadius: 11,
    alignItems: 'center', justifyContent: 'center',
    backgroundColor: C.card, borderWidth: 1, borderColor: C.green,
  },
  oopMini: { paddingHorizontal: S.md, alignSelf: 'stretch', justifyContent: 'center' },

  footer: {
    flexDirection: 'row', gap: S.lg, justifyContent: 'center', flexWrap: 'wrap',
    marginTop: S.xl, paddingTop: S.lg, borderTopWidth: 1, borderTopColor: C.border,
  },
  footerLink: { ...T.smallMed, color: C.muted },
})
