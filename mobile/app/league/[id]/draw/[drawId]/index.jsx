/*
 * Standings for one draw.
 *
 * Two things here are easy to get subtly wrong, and both would make the app
 * disagree with the website in ways nobody would notice for weeks:
 *
 * 1. DO NOT RE-SORT. The server returns entries already ordered by total
 *    points, then by points in the latest rounds first (Final -> SF -> QF ...).
 *    That tiebreak is lexicographic over the round vector, not a weighted sum,
 *    so any client-side sort by `total` alone silently reorders ties.
 *
 * 2. Ties share a rank, and the next rank skips. Competition ranking:
 *    1, 1, 1, 4 — not 1, 1, 1, 2. Two people genuinely level are level, and
 *    the person behind them is fourth.
 */

import { Link, Stack, useLocalSearchParams } from 'expo-router'
import { StyleSheet, Text, View } from 'react-native'
import { useAuth } from '../../../../../auth'
import { getLeague, getLeagueTournaments, getRoundScores } from '../../../../../api'
import { useApi } from '../../../../../useApi'
import { competitionRanks } from '../../../../../scoring'
import { C } from '../../../../../theme'
import { Card, ErrorNote, Loading, Muted, Screen, Title } from '../../../../../ui'

export default function Standings() {
  const { id, drawId } = useLocalSearchParams()
  const { me } = useAuth()

  const league = useApi(`league:${id}`, () => getLeague(id))
  const draws = useApi(`league:${id}:tournaments`, () => getLeagueTournaments(id))
  const scores = useApi(`scores:${id}:${drawId}`, () => getRoundScores(id, drawId))

  const t = draws.data?.find(x => String(x.tournament?.id) === String(drawId))?.tournament
  const entries = scores.data?.entries || []
  const ranks = competitionRanks(entries)
  const showReal = !!league.data?.show_real_name

  return (
    <>
      <Stack.Screen options={{ title: t?.name || 'Standings' }} />
      <Screen onRefresh={scores.refetch} refreshing={scores.loading && !!scores.data}>
        {scores.loading && !scores.data ? <Loading /> : null}
        <ErrorNote error={scores.error} onRetry={scores.refetch} />

        {scores.data && (
          <View style={s.bar}>
            <Muted>
              {scores.data.completed_matches_count} matches played
              {t ? ` · ${t.draw_size} draw` : ''}
            </Muted>
            <Link href={`/league/${id}/draw/${drawId}/picks`} style={s.link}>
              Your picks ›
            </Link>
          </View>
        )}

        {scores.data && entries.length === 0 && (
          <Card>
            <Title>No standings yet</Title>
            <Muted>Nobody has scored in this draw yet.</Muted>
          </Card>
        )}

        {entries.length > 0 && (
          <View style={s.table}>
            <View style={[s.row, s.head]}>
              {/* numberOfLines on every header cell, without exception: these
                  are FIXED-WIDTH columns, and "Correct" at 12pt uppercase is
                  wider than 62pt, so it broke as "CORREC / T". Wording follows
                  the dashboard's own — "26 right · 26 pts" — rather than being
                  a second vocabulary for the same two numbers. */}
              <Text style={[s.rank, s.headText]} numberOfLines={1}>#</Text>
              <Text style={[s.who, s.headText]} numberOfLines={1}>Player</Text>
              <Text style={[s.num, s.headText]} numberOfLines={1}>Right</Text>
              <Text style={[s.num, s.headText]} numberOfLines={1}>Pts</Text>
            </View>
            {entries.map((e, i) => {
              const mine = me && e.user_id === me.id
              return (
                <View
                  key={e.user_id}
                  style={[s.row, i % 2 ? s.alt : null, mine && s.mine]}
                >
                  <Text style={s.rank}>{ranks[i]}</Text>
                  <View style={s.who}>
                    <Text style={[s.name, mine && s.nameMine]} numberOfLines={1}>
                      {e.username}
                    </Text>
                    {showReal && e.full_name ? (
                      <Text style={s.real} numberOfLines={1}>{e.full_name}</Text>
                    ) : null}
                  </View>
                  <Text style={s.num}>{e.correct_count}</Text>
                  <Text style={[s.num, s.total]}>{e.total}</Text>
                </View>
              )
            })}
          </View>
        )}
      </Screen>
    </>
  )
}

const s = StyleSheet.create({
  bar: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 12 },
  link: { color: C.accent, fontWeight: '700', paddingVertical: 6 },
  table: {
    borderWidth: 1, borderColor: C.border, borderRadius: 14,
    overflow: 'hidden', backgroundColor: C.card,
  },
  row: {
    flexDirection: 'row', alignItems: 'center',
    paddingVertical: 10, paddingHorizontal: 12, gap: 8,
  },
  head: { backgroundColor: C.raised, paddingVertical: 8 },
  headText: { color: C.muted, fontSize: 12, fontWeight: '700', textTransform: 'uppercase' },
  alt: { backgroundColor: '#14201c' },
  mine: { backgroundColor: '#1d3329' },
  rank: { color: C.muted, width: 28, fontWeight: '700' },
  who: { flex: 1, minWidth: 0 },
  name: { color: C.ink, fontWeight: '600' },
  nameMine: { color: C.accent, fontWeight: '800' },
  real: { color: C.muted, fontSize: 12 },
  num: { color: C.ink, width: 62, textAlign: 'right' },
  total: { fontWeight: '800' },
})
