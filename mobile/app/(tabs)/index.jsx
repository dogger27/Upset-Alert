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
import { drawsByTournament } from '../../scheduleRows'
import { lockLabel } from '../../lock'
import { C, R, S, T } from '../../theme'
import { StatusChip, SurfaceText, TourCard, useCardSkin } from '../../cards'
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
function OrderOfPlay({ t }) {
  const oop = oopHref(t)
  const inks = useCardSkin()
  /* NOTHING TO OPEN YET — STILL A PILL, HOLLOWED OUT (owner, 2026-09-16).
   *
   * The disabled state keeps the control's outline and loses its fill: the
   * border says "this is the same button you press on the cards above", the
   * empty middle says "not yet". Bare type said the second thing only, and on
   * a week card it read as a stray label rather than the same affordance
   * greyed.
   *
   * NO `opacity` MULTIPLIER, which is what it used to be: C.faint at 0.6
   * leaves about 3:1 on the near-black card and lands near 1.6 on a tour
   * tint, so the label was legible nowhere a card is coloured — which is most
   * of this screen. A step of the ramp carries the text (see theme.js), and
   * the border is that same ink, at a fraction of it, so the outline sits
   * below the word inside it rather than boxing it in.
   *
   * THE ROW NO LONGER CHANGES HEIGHT with whether a sheet exists: live and
   * dead are now the same 25pt object, where before the dead one was 15pt of
   * type and a week card was shorter on the days nobody had published an
   * order of play.
   *
   * "SCHEDULE", NOT "ORDER OF PLAY" (owner, 2026-09-16). Two reasons, and the
   * first is measured: at the owner's text size the longer phrase wrapped to
   * two lines inside the pill, which doubled the control's height and with it
   * the whole week card's. The second is that it names its destination — the
   * Schedule tab, spelled exactly that way in the tab bar — where "Order of
   * Play" named the sheet the tour publishes. Same word for the same place.
   *
   * numberOfLines={1} REGARDLESS, on both states: a pill this row's height
   * depends on must not be able to wrap, whatever the label becomes next or
   * whatever the reader's type size is. That is the actual fault; the shorter
   * word is what buys the room back.
   *
   * A SECOND AXIS, `skin.quiet`: THE SECTION (owner, 2026-09-16). Everything
   * above is about STATE — a sheet exists or it does not. This is about how
   * much the CARD is worth: Open and Active are this week and push the button
   * up, next and last week are context and push it down. They are independent,
   * so all four combinations occur — Last week's US Open has a sheet on a
   * quiet card, and an Active draw often has none on a loud one.
   *
   * ONE KNOB CARRIES IT: the border's alpha over its own label, 70% on a loud
   * card and 40% on a quiet one. On the chip that is 4.5-8.1:1 off the fill
   * against 2.4-3.4; on the lifted pill 2.7-3.3 against 1.5-1.6.
   */
  const edge = inks.quiet ? '66' : 'b3'
  if (!oop) {
    /* AND HERE THE LABEL STEPS DOWN TOO, which it does not on the chip below.
       On a week card it is `faint` at 3.4-4.3:1 rather than `muted` at
       4.1-5.5 — deliberately under AA, at the owner's ask, and this is the one
       place in the app where that is a fair trade: a label naming something
       that does not exist yet, on the least important card on the screen, with
       everything actionable above it. */
    const lab = inks.quiet ? inks.faint : inks.muted
    return (
      <View style={[s.oop, s.oopDead, { borderColor: lab + edge }]}>
        <Text style={[s.oopText, { color: lab }]} numberOfLines={1}>Schedule</Text>
      </View>
    )
  }
  // CardLink, not <Link asChild><Pressable style>: that form drops the
  // style — the pill rendered as bare text — and it is the trap CardLink
  // exists to close. Third time it has been re-typed; last time.
  /* THE CONTROL IS READ IN THE CARD'S OWN INK, not in the brand's green
     (owner, 2026-09-16, "the green button and icon are not working with the
     pink").
   *
   * C.greenLit sits 164.5 degrees from the WTA card's hue at 3.44:1 — a near
   * complement at low contrast, which is the definition of a vibrating pair —
   * and 2.68:1 against the pill's own fill, under any floor. It was right when
   * it was chosen: on the near-black card it is 12.8 degrees away and 6.40:1,
   * a green control on a green-grey card.
   *
   * NO FIXED ACCENT CAN REPLACE IT, which is what settles the question rather
   * than taste. The two tints are 100 degrees apart, so an accent that is
   * harmonious on one is near-complementary on the other: C.gold is 89 degrees
   * from the pink card and 171 from the blue, C.clayLight 59 and 159. Only a
   * colour derived PER TOUR can be harmonious on both, and the card already
   * has one. C.gold was the close second and was rejected for a second reason
   * as well: in this palette gold means a locked podium place, and a gold
   * button on every card spends that meaning.
   *
   * FILLED VERSUS HOLLOW, because there are two states and they have to be
   * told apart across a column of cards without being read (owner,
   * 2026-09-16). Weight alone was not enough: the first attempt lifted the
   * available pill with white at 10%, which is 1.28:1 against the card, and
   * beside a hollow one it read as the same object twice.
   *
   * THE TWO STATES GO OPPOSITE WAYS OFF THE CARD (owner, 2026-09-16). A sheet
   * that exists is a RECESSED DARK CHIP — the card's own control pair, the
   * dark its tier stamp sits on carrying the tour's light ink, at 9.5:1 on the
   * WTA card, 7.6 on the ATP and 15.7 on the neutral. One that does not exist
   * is barely LIFTED instead: white at 8%, which is 1.22:1, present as a shape
   * and saying nothing.
   *
   * THE CHIP IS DEFINED BY ITS EDGE, not by its fill. The fill is only 1.9:1
   * off a tinted card and 1.17:1 off the neutral one, where there is almost no
   * room left to go darker — so the border is the label, at 70% on a loud card
   * and 40% on a quiet one, standing 4.5-8.1:1 and 2.4-3.4:1 off the fill.
   *
   * ITS LABEL DOES NOT STEP DOWN ON A QUIET CARD, and the arithmetic is why:
   * this is a LIGHT label on a DARK fill, so walking it down the ink ramp does
   * not lower its contrast. `muted` measures 9.34:1 on the WTA chip against
   * `text`'s 9.52, and on the ATP chip it goes UP — 9.53 from 7.63. The only
   * lever that quiets a chip is its border, which is the one that moves.
   *
   * AND THE QUIET STATE MOVED UP A RAMP STEP, which is the part that is not
   * obvious: lifting its fill costs its label contrast, so C.faint fell from
   * 4.20:1 on the bare card to 3.45 on the lifted one. It takes `muted`
   * instead, at 4.05-5.53:1 — still the quieter of the two by a wide margin,
   * since the chip beside it carries 9.5:1. */
  return (
    <CardLink href={oop} pressedOpacity={0.7}
              style={[s.oop, { backgroundColor: inks.control,
                               borderColor: inks.controlInk + edge }]}
              accessibilityLabel="Schedule and order of play">
      <Text style={[s.oopText, { color: inks.controlInk }]} numberOfLines={1}>Schedule</Text>
    </CardLink>
  )
}

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
            <ActiveCard key={g[0].id} draws={g} userId={me?.id} status={entry.data} />
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

/* WHERE YOU STAND IN THIS DRAW, and its order of play. Its own component
   because it FETCHES: a standing is per draw, so a combined card needs two
   requests, and a hook cannot be called in a loop. One component per row, one
   hook each, and the card does not care how many there are. */
function ActiveRow({ t, userId, label }) {
  const standings = useApi(`standings:${t.id}`, () => getDrawStandings(t.id))
  const rows = standings.data || []
  const mine = rows.find(r => r.user?.id === userId)
  const inks = useCardSkin()
  /* THE LABEL STAYS HERE, where the pill came off everywhere else: a standing
     is the one fact on this card that genuinely differs between the two halves
     and cannot be collapsed — 3rd of 8 and 7th of 8 are two different links to
     two different pages, and unlabelled they are a coin toss. It rides inside
     the link, as plain type. */
  return mine ? (
    <CardLink href={`/standings/${t.id}`} style={s.lockLine} pressedOpacity={0.6}>
      {label ? <Text style={[s.footTour, { color: inks.faint }]}>{label}</Text> : null}
      <Text style={[T.score, { color: inks.ink }]}>{ordinal(mine.rank)}</Text>
      <Text style={[T.tiny, { color: inks.faint }]}>of {rows.length}</Text>
      <Ionicons name="chevron-forward" size={13} color={inks.faint} />
    </CardLink>
  ) : (
    <View style={s.lockLine}>
      {label ? <Text style={[s.footTour, { color: inks.faint }]}>{label}</Text> : null}
      <Text style={[T.tiny, { color: inks.faint }]}>
        {standings.loading ? '' : 'Not entered'}
      </Text>
    </View>
  )
}

/* Active: nothing to do, so the only question is where you stand. */
function ActiveCard({ draws, userId, status }) {
  /* COMPETING IN THE EVENT, which is what the corner stamp claims: picks in
     for either half of a combined tournament means you are in it. Which half
     is in the rows below, where a standing says it better than a star. */
  const competing = draws.some(d => status?.[d.id] === 'complete')
  return (
        <TourCard
          draws={draws} name={draws[0].name} href={cardHref(draws)}
          corner={competing ? <CompetingStar /> : null}
          footer={
            <View style={s.footRow}>
              <View style={s.footStack}>
                {draws.map(d => (
                  <ActiveRow key={d.id} t={d} userId={userId}
                             label={draws.length > 1 ? tourWord([d]) : null} />
                ))}
              </View>
              <OrderOfPlay t={oopDraw(draws)} />
            </View>
          }
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
  const opens = done ? null : draws
    .map(d => d.draw_release_direct || d.draw_release_qualifiers)
    .filter(Boolean)
    .sort()[0]
  return (
    <TourCard draws={draws} name={draws[0].name} href={cardHref(draws)} compact
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
      <WeekRow draws={draws} opens={opens} />
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
 * child of the card it was passed to. OpenRow and ActiveRow were already this
 * shape for the same structural reason; this one now matches them.
 */
function WeekRow({ draws, opens }) {
  const inks = useCardSkin()
  return (
    <View style={s.weekRow}>
      {/* THE RELEASE DATE ON THE ROW'S CENTRE LINE, by the same two-flexible-
          slots arithmetic the surface pill uses on the cards above: the sides
          split what the middle leaves, so the middle's centre is the row's
          centre. It trailed the city before, which put it in four places
          down a column of four cards (owner, 2026-09-15). */}
      <View style={s.weekSide}>
        {draws[0].city ? (
          <Text style={[T.smallMed, { color: inks.inkBody }]} numberOfLines={1}>
            {draws[0].city}
          </Text>
        ) : null}
      </View>
      {opens ? (
        <Text style={[T.tiny, { color: inks.faint }]} numberOfLines={1}>
          Opens {fmtShort(opens)}
        </Text>
      ) : null}
      <View style={[s.weekSide, { alignItems: 'flex-end' }]}>
        <OrderOfPlay t={oopDraw(draws)} />
      </View>
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
    letterSpacing: 0.9, color: C.muted, textAlign: 'center', marginTop: -leading(12),
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
  // One row per draw on a combined card, and exactly one row otherwise — so
  // the single-draw card's footer is unchanged by the gap.
  footStack: { gap: S.sm },
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
  oop: {
    borderRadius: R.pill, borderWidth: 1, borderColor: C.borderOn, backgroundColor: C.raised,
    paddingHorizontal: 10, paddingVertical: 4,
  },
  /* Barely lifted off the card rather than cut out of it — see OrderOfPlay.
     White at 8% is 1.22:1, which is a shape you can find without it being a
     shape that asks for anything. It composes ON TOP of `oop`, so the key has
     to be set rather than omitted. */
  oopDead: { backgroundColor: 'rgba(255,255,255,0.08)' },
  /* NO COLOUR HERE. Both states set their own from the card's skin — the
     live pill the ink, the disabled one the faint step — and a default green
     left in the shared style is a default that only looks right on the one
     card it was chosen against. */
  oopText: { ...T.tiny, letterSpacing: 0.3 },
  oopMini: { paddingHorizontal: S.md, alignSelf: 'stretch', justifyContent: 'center' },

  footer: {
    flexDirection: 'row', gap: S.lg, justifyContent: 'center', flexWrap: 'wrap',
    marginTop: S.xl, paddingTop: S.lg, borderTopWidth: 1, borderTopColor: C.border,
  },
  footerLink: { ...T.smallMed, color: C.muted },
})
