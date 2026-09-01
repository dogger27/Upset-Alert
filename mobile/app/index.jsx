/*
 * The dashboard — what needs your attention, in that order.
 *
 * Not a directory of everything. The website's home page can afford four equal
 * sections side by side; a phone cannot, so this ranks by what it costs you to
 * miss it:
 *
 *   1. A live match you have a stake in   — gone in an hour, and the reason
 *                                           this app exists rather than a site
 *   2. Draws open for picks               — a deadline you can actually miss
 *   3. Draws playing                      — nothing to do, but you want to know
 *   4. Next week / last week              — context, compressed to one line each
 */

import { useEffect, useMemo, useState } from 'react'
import { Link, Redirect } from 'expo-router'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { useAuth } from '../auth'
import { getEntryStatus, getOffer, listTournaments } from '../api'
import { useApi } from '../useApi'
import { computeCohortInfo, getHomeSection } from '../drawStatus'
import { lockLabel } from '../lock'
import { showOnLockScreen } from '../liveactivity'
import { isAvailable } from '../modules/live-activity'
import { C, R, S, T } from '../theme'
import { Button, Card, ErrorNote, Eyebrow, Loading, Muted, Pill, Screen, Title } from '../ui'

export default function Dashboard() {
  const { phase, me, config, signOut, retry, error: authError } = useAuth()
  const ready = phase === 'ready'

  const tours = useApi(ready ? 'tournaments' : null, listTournaments, { enabled: ready })
  const entry = useApi(ready ? 'entry-status' : null, getEntryStatus, { enabled: ready })
  const offer = useApi(ready ? 'offer' : null, getOffer, { enabled: ready })

  // A clock, so countdowns tick without the whole screen refetching. Thirty
  // seconds is enough for a label whose smallest unit is a minute.
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30000)
    return () => clearInterval(id)
  }, [])

  const buckets = useMemo(() => {
    const all = tours.data || []
    // computeCohortInfo needs EVERY draw, not the ones being displayed —
    // clustering on a filtered list moves the "Last Week" boundary.
    const cohort = computeCohortInfo(all)
    const of = k => all.filter(t => getHomeSection(t, cohort) === k)
    return { open: of('open'), active: of('active'), upcoming: of('upcoming'), lastweek: of('lastweek') }
  }, [tours.data])

  const refetch = () => { tours.refetch(); entry.refetch(); offer.refetch() }

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
  const nothing = !loading && !buckets.open.length && !buckets.active.length
    && !buckets.upcoming.length && !buckets.lastweek.length

  return (
    <Screen onRefresh={refetch} refreshing={tours.loading && !!tours.data}>
      <Head username={me?.username} />

      <ErrorNote error={tours.error} onRetry={refetch} />
      {loading ? <Loading /> : null}

      {offer.data?.match ? (
        <LiveNow offer={offer.data} contentVersion={config?.content_state_version ?? 1} />
      ) : null}

      <Section title="Pick now" count={buckets.open.length} tone="open">
        {buckets.open.map(t => (
          <DrawCard key={t.id} t={t} status={entry.data?.[t.id]} now={now} />
        ))}
        {!buckets.open.length && !loading && (
          <Muted>Nothing open for picks. The next draw appears here when it’s released.</Muted>
        )}
      </Section>

      {buckets.active.length > 0 && (
        <Section title="Playing" count={buckets.active.length} tone="live">
          {buckets.active.map(t => (
            <DrawCard key={t.id} t={t} status={entry.data?.[t.id]} now={now} playing />
          ))}
        </Section>
      )}

      {buckets.upcoming.length > 0 && (
        <Section title="Next week" count={buckets.upcoming.length}>
          {buckets.upcoming.map(t => <CompactRow key={t.id} t={t} />)}
        </Section>
      )}

      {buckets.lastweek.length > 0 && (
        <Section title="Last week" count={buckets.lastweek.length}>
          {buckets.lastweek.map(t => <CompactRow key={t.id} t={t} done />)}
        </Section>
      )}

      {nothing && (
        <Card>
          <Title>Nothing on right now</Title>
          <Muted>The tour is between events. Draws appear here as they’re released.</Muted>
        </Card>
      )}

      <View style={s.footer}>
        <Link href="/leagues" style={s.footerLink}>Leagues</Link>
        <Link href="/status" style={s.footerLink}>Status</Link>
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
        <Eyebrow color={tone === 'open' ? C.clay : tone === 'live' ? C.greenLit : C.muted}>
          {title}
        </Eyebrow>
        {count ? <Text style={[T.tiny, { color: C.faint }]}>{count}</Text> : null}
      </View>
      {children}
    </View>
  )
}

/* The reason the app exists, so it sits above everything else. */
function LiveNow({ offer, contentVersion }) {
  const m = offer.match
  const a = m.attributes
  const st = m.content_state
  const [busy, setBusy] = useState(false)
  const [shown, setShown] = useState(false)
  const [err, setErr] = useState('')

  async function show() {
    setBusy(true); setErr('')
    try { await showOnLockScreen(m, contentVersion); setShown(true) }
    catch (e) { setErr(e.message) }
    finally { setBusy(false) }
  }

  const games = st?.games
  const line = side => (games && games[side] ? games[side].filter(Boolean).join('  ') : '')

  return (
    <Card style={s.live} tint={C.greenLit}>
      <View style={s.sectionHead}>
        <Eyebrow color={C.greenLit}>Live now</Eyebrow>
        <Pill tone="live">On court</Pill>
      </View>

      {a ? (
        <>
          <Text style={[T.tiny, { color: C.faint }]}>
            {a.event_label}{a.round_name ? ` · ${a.round_name}` : ''}
          </Text>
          <PlayerLine name={a.p1_name} seed={a.p1_seed} score={line(0)}
                      picked={st?.pick?.side === 1} serving={st?.serving === 1} />
          <PlayerLine name={a.p2_name} seed={a.p2_seed} score={line(1)}
                      picked={st?.pick?.side === 2} serving={st?.serving === 2} />
        </>
      ) : (
        <Title>{m.event}</Title>
      )}

      <Muted>{offer.reason}</Muted>

      {shown ? (
        <Muted>On your Lock Screen. It updates as the match moves.</Muted>
      ) : (
        <Button
          label={isAvailable() ? 'Show on Lock Screen' : 'Needs the latest build'}
          onPress={show} busy={busy}
        />
      )}
      {!!err && <Text style={[T.small, { color: C.bad }]}>{err}</Text>}
    </Card>
  )
}

function PlayerLine({ name, seed, score, picked, serving }) {
  return (
    <View style={s.player}>
      <View style={[s.dot, serving && { backgroundColor: C.clay }]} />
      {seed ? <Text style={[T.tiny, { color: C.faint }]}>{seed}</Text> : null}
      <Text
        style={[T.bodyMed, { color: picked ? C.clay : C.ink, flex: 1 }]}
        numberOfLines={1}
      >
        {name}
      </Text>
      <Text style={[T.score, { color: C.ink }]}>{score}</Text>
    </View>
  )
}

function DrawCard({ t, status, now, playing }) {
  const lock = lockLabel(t, now)
  const tint = t.gender === 'F' ? C.wta : C.atp
  const entered = status === 'complete' ? 'Picks in'
    : status === 'partial' ? 'Partly picked'
    : 'Not entered'

  return (
    <Link href={`/draw/${t.id}`} asChild>
      <Pressable style={({ pressed }) => [s.drawCard, pressed && { opacity: 0.75 }]}>
        <View style={[s.tint, { backgroundColor: tint }]} />
        <View style={s.drawBody}>
          <View style={s.drawTop}>
            <Text style={[T.h2, { color: C.ink, flex: 1 }]} numberOfLines={1}>{t.name}</Text>
            <Text style={[T.tiny, { color: tint }]}>{t.gender === 'F' ? 'WTA' : 'ATP'}</Text>
          </View>
          <Text style={[T.small, { color: C.muted }]} numberOfLines={1}>
            {[t.category, t.surface, t.draw_size ? `${t.draw_size} draw` : null, t.city]
              .filter(Boolean).join(' · ')}
          </Text>
          <View style={s.drawFoot}>
            {lock ? (
              <Text style={[T.smallMed, { color: lock.urgent ? C.clay : C.muted }]}>
                {lock.text}
              </Text>
            ) : <View />}
            <Text style={[T.tiny, {
              color: status === 'complete' ? C.greenLit
                : status === 'partial' ? C.warn
                : playing ? C.faint : C.clay,
            }]}>
              {entered}
            </Text>
          </View>
        </View>
      </Pressable>
    </Link>
  )
}

function CompactRow({ t, done }) {
  return (
    <Link href={`/draw/${t.id}`} asChild>
      <Pressable style={({ pressed }) => [s.compact, pressed && { opacity: 0.7 }]}>
        <View style={[s.compactDot, { backgroundColor: t.gender === 'F' ? C.wta : C.atp }]} />
        <Text style={[T.small, { color: done ? C.muted : C.inkBody, flex: 1 }]} numberOfLines={1}>
          {t.name}
        </Text>
        <Text style={[T.tiny, { color: C.faint }]}>
          {t.surface || ''}{t.draw_size ? ` · ${t.draw_size}` : ''}
        </Text>
      </Pressable>
    </Link>
  )
}

const s = StyleSheet.create({
  head: {
    flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between',
    paddingTop: S.sm, paddingBottom: S.xs,
  },
  brand: { ...T.display, color: C.ink },
  section: { gap: S.sm, marginTop: S.sm },
  sectionHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },

  live: { gap: S.sm },
  player: { flexDirection: 'row', alignItems: 'center', gap: S.sm },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: 'transparent' },

  drawCard: {
    backgroundColor: C.card, borderRadius: R.lg, borderWidth: 1, borderColor: C.border,
    flexDirection: 'row', overflow: 'hidden',
  },
  tint: { width: 4 },
  drawBody: { flex: 1, padding: S.md, gap: 3 },
  drawTop: { flexDirection: 'row', alignItems: 'center', gap: S.sm },
  drawFoot: {
    flexDirection: 'row', justifyContent: 'space-between',
    alignItems: 'baseline', marginTop: S.xs,
  },

  compact: {
    flexDirection: 'row', alignItems: 'center', gap: S.sm,
    paddingVertical: S.sm, paddingHorizontal: S.md,
    backgroundColor: C.card, borderRadius: R.md, borderWidth: 1, borderColor: C.border,
  },
  compactDot: { width: 6, height: 6, borderRadius: 3 },

  footer: {
    flexDirection: 'row', gap: S.xl, justifyContent: 'center',
    marginTop: S.xl, paddingTop: S.lg, borderTopWidth: 1, borderTopColor: C.border,
  },
  footerLink: { ...T.smallMed, color: C.muted },
})
