/*
 * Your record, draw by draw.
 *
 * The endpoint already filters to draws you COMPETED in, which is the whole
 * subtlety: a draw you never picked in is not a result you came last in, and
 * listing it would invent a defeat. So nothing here re-filters or re-sorts —
 * it renders what the server considers your record.
 */

import { Stack, useLocalSearchParams } from 'expo-router'
import { StyleSheet, Text, View } from 'react-native'
import { getMyDrawHistory, getUserDrawHistory } from '../api'
import { useApi } from '../useApi'
import { TourBadge } from '../cards'
import { C, R, S, T } from '../theme'
import { Card, CardLink, ErrorNote, Loading, Muted, Screen, Title } from '../ui'

export default function History() {
  /* ?user= shows someone else's record — the site's per-row Draw History
     button from the standings. The user endpoint answers { username,
     entries }; the caller's own answers a bare list with no name on it. */
  const { user } = useLocalSearchParams()
  const q = useApi(user ? `draw-history:${user}` : 'draw-history',
                   () => (user ? getUserDrawHistory(user) : getMyDrawHistory()))
  const rows = (user ? q.data?.entries : q.data) || []
  const username = user ? q.data?.username : null

  return (
    <>
      <Stack.Screen options={{ title: 'Draw history' }} />
      <Screen onRefresh={q.refetch} refreshing={q.loading && !!q.data}>
        {q.loading && !q.data ? <Loading /> : null}
        <ErrorNote error={q.error} onRetry={q.refetch} />

        {username ? <Muted>{username}</Muted> : null}
        {q.data && rows.length === 0 && (
          <Card>
            <Title>No draws yet</Title>
            <Muted>{username ? `${username} has not yet completed any draws.` : 'Draws you’ve competed in show up here once they finish.'}</Muted>
          </Card>
        )}

        {rows.length > 0 && (
          <Muted>{rows.length} draw{rows.length === 1 ? '' : 's'} played</Muted>
        )}

        {rows.map(r => <Row key={`${r.tournament_id}`} r={r} />)}
      </Screen>
    </>
  )
}

function Row({ r }) {
  // Winning outright is worth saying out loud; so is the field being tiny,
  // because "1st of 2" and "1st of 40" are not the same achievement.
  const won = r.rank === 1
  return (
    <CardLink href={`/draw/${r.tournament_id}`} style={s.card}>
      <View style={[s.stripe, { backgroundColor: r.gender === 'F' ? C.wta : C.atp }]} />
      <View style={s.body}>
        <View style={s.titleRow}>
          <Text style={s.name} numberOfLines={1}>{r.name}</Text>
          <TourBadge gender={r.gender} />
          <Text style={s.year}>{r.year}</Text>
        </View>
        <Text style={s.meta} numberOfLines={1}>
          {[r.category, r.surface].filter(Boolean).join(' · ')}
        </Text>
        <View style={s.statRow}>
          <Text style={[s.rank, won && { color: C.clay }]}>
            {ordinal(r.rank)} <Text style={s.of}>of {r.total_participants}</Text>
          </Text>
          <Text style={s.pts}>
            {r.correct_count}/{r.total_matches} right · {fmt(r.points)} pts
          </Text>
        </View>
      </View>
    </CardLink>
  )
}

function ordinal(n) {
  if (n == null) return '—'
  const suf = ['th', 'st', 'nd', 'rd']
  const v = n % 100
  return n + (suf[(v - 20) % 10] || suf[v] || suf[0])
}
const fmt = p => (Number.isInteger(p) ? String(p) : String(Math.round(p * 10) / 10))

const s = StyleSheet.create({
  card: {
    backgroundColor: C.card, borderRadius: R.md, borderWidth: 1, borderColor: C.border,
    flexDirection: 'row', overflow: 'hidden',
  },
  stripe: { width: 5, alignSelf: 'stretch' },
  body: { flex: 1, paddingVertical: 11, paddingHorizontal: 13, gap: 4 },
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  name: { ...T.h2, color: C.ink, flexShrink: 1 },
  year: { ...T.tiny, color: C.faint, marginLeft: 'auto' },
  meta: { ...T.tiny, color: C.muted },
  statRow: {
    flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between',
    gap: S.sm, borderTopWidth: 1, borderTopColor: C.border, paddingTop: 6, marginTop: 2,
  },
  rank: { ...T.bodyBold, color: C.ink },
  of: { ...T.tiny, color: C.faint, fontWeight: '400' },
  pts: { ...T.tiny, color: C.muted },
})
