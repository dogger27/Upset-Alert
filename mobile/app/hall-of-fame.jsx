/*
 * Hall of Fame — the best single-draw performances.
 *
 * SPLIT BY TIER AND THEN BY GENDER, and it has to stay that way: a 128-draw
 * Grand Slam and a 32-draw ATP 250 do not produce comparable point totals, so
 * one combined table would just be a list of Slams. The server already groups
 * it; this screen renders the grouping rather than flattening it.
 */

import { Stack } from 'expo-router'
import { StyleSheet, Text, View } from 'react-native'
import { getHallOfFame } from '../api'
import { useApi } from '../useApi'
import { TourBadge } from '../cards'
import { C, R, S, T } from '../theme'
import { Card, ErrorNote, Eyebrow, Loading, Muted, Screen, Title } from '../ui'

export default function HallOfFame() {
  const q = useApi('hall-of-fame', getHallOfFame)
  const groups = q.data || []

  return (
    <>
      <Stack.Screen options={{ title: 'Hall of Fame' }} />
      <Screen onRefresh={q.refetch} refreshing={q.loading && !!q.data}>
        {q.loading && !q.data ? <Loading /> : null}
        <ErrorNote error={q.error} onRetry={q.refetch} />

        {q.data && groups.length === 0 && (
          <Card>
            <Title>Nothing here yet</Title>
            <Muted>Finished draws produce records; none have yet.</Muted>
          </Card>
        )}

        {groups.map(g => (
          <View key={g.tier} style={s.group}>
            <Eyebrow>{g.tier}</Eyebrow>
            <Board gender="M" rows={g.men} />
            <Board gender="F" rows={g.women} />
          </View>
        ))}
      </Screen>
    </>
  )
}

function Board({ gender, rows }) {
  if (!rows?.length) return null
  return (
    <View style={s.board}>
      <View style={s.boardHead}>
        <TourBadge gender={gender} />
        <Text style={s.boardTitle}>Best performances</Text>
      </View>
      {rows.map(r => (
        <View key={`${r.user_id}:${r.tournament_id}`}
              style={[s.row, r.is_current_user && s.mine]}>
          <Text style={[s.rank, r.rank === 1 && { color: C.clay }]}>{r.rank}</Text>
          <View style={s.who}>
            {/* Username, never display_name — see the predictors sheet. */}
            <Text style={[s.user, r.is_current_user && { color: C.clay }]} numberOfLines={1}>
              {r.username}
            </Text>
            <Text style={s.where} numberOfLines={1}>
              {r.tournament_name} {r.tournament_year}
            </Text>
          </View>
          <View style={s.nums}>
            <Text style={s.pts}>{fmt(r.points)}</Text>
            <Text style={s.right}>{r.correct_count}/{r.total_matches}</Text>
          </View>
        </View>
      ))}
    </View>
  )
}

const fmt = p => (Number.isInteger(p) ? String(p) : String(Math.round(p * 10) / 10))

const s = StyleSheet.create({
  group: { gap: S.sm },
  board: {
    borderWidth: 1, borderColor: C.border, borderRadius: R.md,
    backgroundColor: C.card, overflow: 'hidden',
  },
  boardHead: {
    flexDirection: 'row', alignItems: 'center', gap: 8,
    paddingHorizontal: 12, paddingVertical: 8, backgroundColor: C.raised,
  },
  boardTitle: { ...T.tiny, color: C.muted, textTransform: 'uppercase', letterSpacing: 0.6 },
  row: {
    flexDirection: 'row', alignItems: 'center', gap: 10,
    paddingHorizontal: 12, paddingVertical: 9,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: C.border,
  },
  mine: { backgroundColor: '#1d3329' },
  rank: { ...T.bodyBold, color: C.muted, width: 20 },
  who: { flex: 1, minWidth: 0 },
  user: { ...T.smallMed, color: C.ink },
  where: { ...T.tiny, color: C.faint },
  nums: { alignItems: 'flex-end' },
  pts: { ...T.bodyBold, color: C.ink },
  right: { ...T.tiny, color: C.faint },
})
