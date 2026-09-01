/* The draws a league has played, newest first. Tap one for its standings. */

import { Stack, useLocalSearchParams } from 'expo-router'
import { StyleSheet, Text, View } from 'react-native'
import { getLeague, getLeagueTournaments } from '../../../api'
import { useApi } from '../../../useApi'
import { TourBadge } from '../../../cards'
import { C } from '../../../theme'
import { Card, CardLink, ErrorNote, Loading, Muted, Screen, Title } from '../../../ui'

export default function LeagueDraws() {
  const { id } = useLocalSearchParams()
  const league = useApi(`league:${id}`, () => getLeague(id))
  const draws = useApi(`league:${id}:tournaments`, () => getLeagueTournaments(id))

  // Newest first. The API returns them in its own order and a league can span
  // several seasons, so an explicit sort beats trusting insertion order.
  const items = [...(draws.data || [])].sort((a, b) => {
    const A = a.tournament?.start_date || '', B = b.tournament?.start_date || ''
    return B.localeCompare(A)
  })

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

        {items.map(it => (
          <DrawRow key={it.tournament.id} t={it.tournament}
                   pickers={it.picker_count} leagueId={id} />
        ))}
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
  chev: { color: C.muted, fontSize: 22, paddingRight: 14 },
})
