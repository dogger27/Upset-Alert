/* The draws a league has played, newest first. Tap one for its standings. */

import { Stack, useLocalSearchParams } from 'expo-router'
import { useMemo, useState } from 'react'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { getLeague, getLeagueTournaments } from '../../../api'
import { useApi } from '../../../useApi'
import { TourBadge } from '../../../cards'
import { computeCohortInfo, getHomeSection } from '../../../drawStatus'
import { C, T } from '../../../theme'
import { Card, CardLink, ErrorNote, Eyebrow, Loading, Muted, Screen, Title } from '../../../ui'

export default function LeagueDraws() {
  const { id } = useLocalSearchParams()
  const league = useApi(`league:${id}`, () => getLeague(id))
  const draws = useApi(`league:${id}:tournaments`, () => getLeagueTournaments(id))

  /* GROUPED THE WAY THE SITE GROUPS THEM. Every draw is filed by the same
     getHomeSection the dashboard uses — computed over ALL of this league's
     draws, because the cohort clustering moves the "last week" boundary if
     it is fed a subset — and then folded into two lists: what is open or
     running, and everything before. Previous is recency-first and shows
     five at a time, as on the site, so a league two seasons old does not
     open on a wall of history. */
  const { current, previous } = useMemo(() => {
    const ts = (draws.data || []).map(x => x.tournament).filter(Boolean)
    const cohort = computeCohortInfo(ts)
    const cur = [], prev = []
    for (const it of draws.data || []) {
      const t = it.tournament
      if (!t) continue
      const sec = getHomeSection(t, cohort)
      ;(sec === 'open' || sec === 'active' || sec === 'upcoming' ? cur : prev).push(it)
    }
    const byStart = (a, b) => (b.tournament?.start_date || '').localeCompare(a.tournament?.start_date || '')
    cur.sort(byStart); prev.sort(byStart)
    return { current: cur, previous: prev }
  }, [draws.data])
  const [prevShown, setPrevShown] = useState(5)

  return (
    <>
      <Stack.Screen options={{ title: league.data?.name || 'League' }} />
      <Screen onRefresh={draws.refetch} refreshing={draws.loading && !!draws.data}>
        {draws.loading && !draws.data ? <Loading /> : null}
        <ErrorNote error={draws.error} onRetry={draws.refetch} />

        {draws.data?.length === 0 && (
          <Card>
            <Title>No draws yet</Title>
            <Muted>This league hasn’t played a draw yet.</Muted>
          </Card>
        )}

        {current.length > 0 && (
          <>
            <Eyebrow>Open / Active</Eyebrow>
            {current.map(it => (
              <DrawRow key={it.tournament.id} t={it.tournament}
                       pickers={it.picker_count} leagueId={id} />
            ))}
          </>
        )}
        {previous.length > 0 && (
          <>
            <Eyebrow>Previous ({previous.length})</Eyebrow>
            {previous.slice(0, prevShown).map(it => (
              <DrawRow key={it.tournament.id} t={it.tournament}
                       pickers={it.picker_count} leagueId={id} />
            ))}
            {prevShown < previous.length && (
              <Pressable onPress={() => setPrevShown(n => n + 5)} style={s.more} hitSlop={8}>
                <Text style={[T.smallMed, { color: C.greenLit }]}>
                  Show {Math.min(5, previous.length - prevShown)} more
                </Text>
              </Pressable>
            )}
          </>
        )}
      </Screen>
    </>
  )
}

function DrawRow({ t, pickers, leagueId }) {
  // Gender drives the accent because it is the fastest way to tell two halves
  // of the same combined event apart, which is exactly the case the web app's
  // combined cards exist for.
  // 'F', not 'W' — the API's genders are 'M' and 'F'. This tested 'W', which is
  // never true, so every stripe in the list rendered ATP blue including the WTA
  // draws. The TourBadge beside it keys on the same field correctly, which is
  // what made the disagreement visible at all.
  const tint = t.gender === 'F' ? C.wta : C.atp
  return (
    <CardLink href={`/league/${leagueId}/draw/${t.id}`} style={s.card}>
      <View style={[s.stripe, { backgroundColor: tint }]} />
      <View style={s.inner}>
        <View style={s.nameRow}>
          <Text style={s.name} numberOfLines={2}>{t.name}</Text>
          {/* Same reason as the dashboard: a combined event lists two draws
              under one name, and the accent stripe alone does not say which
              is which. */}
          <TourBadge gender={t.gender} />
        </View>
        <Text style={s.meta}>
          {[t.category, t.surface, t.year].filter(Boolean).join(' · ')}
        </Text>
        <Text style={s.meta}>
          {t.draw_size} draw · {pickers} {pickers === 1 ? 'picker' : 'pickers'}
        </Text>
      </View>
      <Text style={s.chev}>›</Text>
    </CardLink>
  )
}

const s = StyleSheet.create({
  card: {
    backgroundColor: C.card, borderRadius: 14, borderWidth: 1,
    borderColor: C.border, flexDirection: 'row', alignItems: 'center',
    overflow: 'hidden',
  },
  stripe: { width: 5, alignSelf: 'stretch' },
  inner: { flex: 1, padding: 14, gap: 3 },
  nameRow: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  name: { color: C.ink, fontWeight: '800', fontSize: 16, flexShrink: 1 },
  meta: { color: C.muted, fontSize: 13 },
  more: { alignSelf: 'center', paddingVertical: 8 },
  chev: { color: C.muted, fontSize: 22, paddingRight: 14 },
})
