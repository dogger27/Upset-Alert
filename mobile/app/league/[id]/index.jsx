/* The draws a league has played, newest first. Tap one for its standings. */

import { Link, Stack, useLocalSearchParams } from 'expo-router'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { getLeague, getLeagueTournaments } from '../../../api'
import { useApi } from '../../../useApi'
import { C } from '../../../theme'
import { Card, ErrorNote, Loading, Muted, Screen, Title } from '../../../ui'

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
  const tint = t.gender === 'W' ? C.wta : C.atp
  return (
    <Link href={`/league/${leagueId}/draw/${t.id}`} asChild>
      <Pressable style={({ pressed }) => [s.card, pressed && { opacity: 0.75 }]}>
        <View style={[s.stripe, { backgroundColor: tint }]} />
        <View style={s.inner}>
          <Text style={s.name} numberOfLines={2}>{t.name}</Text>
          <Text style={s.meta}>
            {[t.category, t.surface, t.year].filter(Boolean).join(' · ')}
          </Text>
          <Text style={s.meta}>
            {t.draw_size} draw · {pickers} {pickers === 1 ? 'picker' : 'pickers'}
          </Text>
        </View>
        <Text style={s.chev}>›</Text>
      </Pressable>
    </Link>
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
  name: { color: C.ink, fontWeight: '800', fontSize: 16 },
  meta: { color: C.muted, fontSize: 13 },
  chev: { color: C.muted, fontSize: 22, paddingRight: 14 },
})
