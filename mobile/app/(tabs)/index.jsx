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

import { useEffect, useMemo, useState } from 'react'
import { Link, Redirect } from 'expo-router'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { useAuth } from '../../auth'
import { getDrawStandings, getEntryStatus, listTournaments } from '../../api'
import { useApi } from '../../useApi'
import { computeCohortInfo, getHomeSection } from '../../drawStatus'
import { lockLabel } from '../../lock'
import { C, R, S, T } from '../../theme'
import { StatusChip, SurfacePill, TourCard } from '../../cards'
import { dateRange } from '../../dates'
import { Button, Card, ErrorNote, Eyebrow, Loading, Muted, Screen, Title } from '../../ui'

export default function Dashboard() {
  const { phase, me, signOut, retry, error: authError } = useAuth()
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
        <Head username={me?.username} />
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
    <Screen onRefresh={refetch} refreshing={tours.loading && !!tours.data}>
      <Head username={me?.username} />

      <ErrorNote error={tours.error} onRetry={refetch} />
      {loading ? <Loading /> : null}

      <Section title="Pick now" count={buckets.open.length} tone={C.clay}>
        {buckets.open.map(t => (
          <OpenCard key={t.id} t={t} status={entry.data?.[t.id]} now={now} />
        ))}
        {!buckets.open.length && !loading && (
          <Muted>Nothing open. A draw appears here the moment it’s released.</Muted>
        )}
      </Section>

      {buckets.active.length > 0 && (
        <Section title="Playing" count={buckets.active.length} tone={C.greenLit}>
          {buckets.active.map(t => <ActiveCard key={t.id} t={t} userId={me?.id} />)}
        </Section>
      )}

      {buckets.upcoming.length > 0 && (
        <Section title="Next week" count={buckets.upcoming.length} tone={C.muted}>
          {buckets.upcoming.map(t => <CompactRow key={t.id} t={t} />)}
        </Section>
      )}

      {buckets.lastweek.length > 0 && (
        <Section title="Last week" count={buckets.lastweek.length} tone={C.muted}>
          {buckets.lastweek.map(t => <CompactRow key={t.id} t={t} done />)}
        </Section>
      )}

      {empty && (
        <Card>
          <Title>Nothing on right now</Title>
          <Muted>The tour is between events. Draws appear here as they’re released.</Muted>
        </Card>
      )}

      {/* Schedule, Leagues and Status moved to the tab bar; a link to a tab
          is a second way to reach the same place and makes the bar look
          optional. Sign out has nowhere else to live yet, so it stays. */}
      <View style={s.footer}>
        <Pressable onPress={signOut} hitSlop={8}>
          <Text style={[T.smallMed, { color: C.faint }]}>Sign out</Text>
        </Pressable>
      </View>
    </Screen>
  )
}

function Head({ username }) {
  return (
    <View style={s.head}>
      <Text style={s.brand}>UPSET <Text style={{ color: C.clay }}>ALERT!</Text></Text>
      {username ? <Text style={[T.smallMed, { color: C.faint }]}>{username}</Text> : null}
    </View>
  )
}

function Section({ title, count, tone, children }) {
  return (
    <View style={s.section}>
      <View style={s.sectionHead}>
        <Eyebrow color={tone}>{title}</Eyebrow>
        <View style={s.rule} />
        {count ? <Text style={[T.tiny, { color: C.faint }]}>{count}</Text> : null}
      </View>
      {children}
    </View>
  )
}

/* "Sep 21 – 27", the site's date range in its mono face, right-aligned in the
   meta row so it reads as the third item in a summary rather than a heading. */

function Meta({ t }) {
  return (
    <View style={s.meta}>
      {t.city ? (
        <Text style={[T.smallMed, { color: C.inkBody, flexShrink: 1 }]} numberOfLines={1}>
          {t.city}
        </Text>
      ) : null}
      <SurfacePill surface={t.surface} />
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
    <Link href={`/draw/${t.id}`} asChild>
      <Pressable style={({ pressed }) => pressed && { opacity: 0.8 }}>
        <TourCard
          tour={t.gender === 'F' ? 'WTA' : 'ATP'} tier={t.category} name={t.name}
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
      </Pressable>
    </Link>
  )
}

/* Playing: nothing to do, so the only question is where you stand. */
function ActiveCard({ t, userId }) {
  const standings = useApi(`standings:${t.id}`, () => getDrawStandings(t.id))
  const rows = standings.data || []
  const mine = rows.find(r => r.user?.id === userId)

  return (
    <Link href={`/draw/${t.id}`} asChild>
      <Pressable style={({ pressed }) => pressed && { opacity: 0.8 }}>
        <TourCard
          tour={t.gender === 'F' ? 'WTA' : 'ATP'} tier={t.category} name={t.name}
          footer={
            <View style={s.footRow}>
              {mine ? (
                <View style={s.lockLine}>
                  <Text style={[T.score, { color: C.ink }]}>{ordinal(mine.rank)}</Text>
                  <Text style={[T.tiny, { color: C.faint }]}>of {rows.length}</Text>
                </View>
              ) : (
                <Text style={[T.tiny, { color: C.faint }]}>
                  {standings.loading ? '' : 'Not entered'}
                </Text>
              )}
              {mine ? (
                <StatusChip tone="muted">
                  {mine.correct_count} right · {fmtPts(mine.total_points)} pts
                </StatusChip>
              ) : null}
            </View>
          }
        >
          <Meta t={t} />
        </TourCard>
      </Pressable>
    </Link>
  )
}

/* Next/last week: one line, because that is what they are worth. The tour dot
   carries the only thing that distinguishes them at a glance. */
function CompactRow({ t, done }) {
  const isATP = t.gender !== 'F'
  return (
    <Link href={`/draw/${t.id}`} asChild>
      <Pressable style={({ pressed }) => [s.compact, pressed && { opacity: 0.7 }]}>
        <View style={[s.compactDot, { backgroundColor: isATP ? C.atp : C.wta }]} />
        <Text style={[T.small, { color: done ? C.muted : C.inkBody, flex: 1 }]} numberOfLines={1}>
          {t.name}
        </Text>
        <Text style={[T.tiny, { color: C.faint }]}>{dateRange(t)}</Text>
      </Pressable>
    </Link>
  )
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

// Points are a float on the wire but whole in practice; show a decimal only
// when there genuinely is one.
const fmtPts = p => (Number.isInteger(p) ? String(p) : String(Math.round(p * 10) / 10))

const s = StyleSheet.create({
  head: {
    flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between',
    paddingTop: S.sm, paddingBottom: S.xs,
  },
  brand: { ...T.display, color: C.ink },

  section: { gap: S.sm, marginTop: S.md },
  sectionHead: { flexDirection: 'row', alignItems: 'center', gap: S.sm },
  rule: { flex: 1, height: 1, backgroundColor: C.border },

  meta: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  footRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: S.sm },
  lockLine: { flexDirection: 'row', alignItems: 'baseline', gap: 5 },

  compact: {
    flexDirection: 'row', alignItems: 'center', gap: S.sm,
    paddingVertical: S.sm, paddingHorizontal: S.md,
    backgroundColor: C.card, borderRadius: R.md, borderWidth: 1, borderColor: C.border,
  },
  compactDot: { width: 6, height: 6, borderRadius: 3 },

  footer: {
    flexDirection: 'row', gap: S.lg, justifyContent: 'center', flexWrap: 'wrap',
    marginTop: S.xl, paddingTop: S.lg, borderTopWidth: 1, borderTopColor: C.border,
  },
  footerLink: { ...T.smallMed, color: C.muted },
})
