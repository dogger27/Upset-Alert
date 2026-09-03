/*
 * Global standings for one draw — the site's Global "league": every player
 * who entered, classic scoring, no league. Reached from the dashboard's
 * position ("29th of 29") and the draw header's tally, where the site's
 * sidebar shows this list beside the bracket.
 *
 * Same two rules as the league standings, for the same reasons: the server's
 * order is kept (its tiebreak is lexicographic over the round vector), and
 * ties share a rank with the next rank skipped.
 */
import { Stack, useLocalSearchParams } from 'expo-router'
import { StyleSheet, Text, View } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { useAuth } from '../../auth'
import { getDrawStandings, listTournaments } from '../../api'
import { useApi } from '../../useApi'
import { competitionRanks } from '../../scoring'
import { othersPicksNote } from '../../lock'
import { C } from '../../theme'
import { PlayerName } from '../../cards'
import { Card, CardLink, ErrorNote, Loading, Muted, Screen, Title } from '../../ui'

export default function GlobalStandings() {
  const { id } = useLocalSearchParams()
  const { me } = useAuth()
  const all = useApi('tournaments', listTournaments)
  const standings = useApi(`standings:${id}`, () => getDrawStandings(id))
  const t = (all.data || []).find(x => String(x.id) === String(id))
  // The league screen's shape, so competitionRanks reads the same field.
  const entries = (standings.data || []).map(r => ({
    user_id: r.user?.id, username: r.user?.username, full_name: r.user?.full_name,
    correct_count: r.correct_count, total: r.total_points,
  }))
  const ranks = competitionRanks(entries)
  const opens = t?.status === 'active' || t?.status === 'completed'

  return (
    <>
      <Stack.Screen options={{ title: t?.name ? `${t.name} · Global` : 'Global standings' }} />
      <Screen onRefresh={standings.refetch}>
        {standings.loading && !standings.data ? <Loading /> : null}
        <ErrorNote error={standings.error} onRetry={standings.refetch} />
        {standings.data && (
          <Muted>{entries.length} entered{t?.draw_size ? ` · ${t.draw_size} draw` : ''}</Muted>
        )}
        {standings.data && entries.length === 0 && (
          <Card>
            <Title>No standings yet</Title>
            <Muted>Nobody has scored in this draw yet.</Muted>
          </Card>
        )}
        {/* The site's sidebar toast, as a line: why a row does not open yet. */}
        {entries.length > 0 && othersPicksNote(t) ? <Muted>{othersPicksNote(t)}</Muted> : null}
        {entries.length > 0 && (
          <View style={s.table}>
            <View style={[s.row, s.head]}>
              <Text style={[s.rank, s.headText]} numberOfLines={1}>#</Text>
              <Text style={[s.who, s.headText]} numberOfLines={1}>Player</Text>
              <Text style={[s.num, s.headText]} numberOfLines={1}>Right</Text>
              <Text style={[s.num, s.headText]} numberOfLines={1}>Pts</Text>
            </View>
            {entries.map((e, i) => {
              const mine = me && e.user_id === me.id
              const Body = opens ? CardLink : View
              return (
                <View key={e.user_id} style={[s.row, i % 2 ? s.alt : null, mine && s.mine]}>
                  <Body href={opens ? { pathname: `/draw/${id}`, params: { user: e.user_id, name: e.username } } : undefined}
                        grow style={s.body}>
                    <Text style={s.rank}>
                      {t?.status === 'completed' && ranks[i] <= 3 ? ['🏆', '🥈', '🥉'][ranks[i] - 1] : ranks[i]}
                    </Text>
                    <View style={s.who}>
                      <PlayerName name={e.username} shrinkOnly style={[s.name, mine && s.nameMine]} />
                    </View>
                    <Text style={s.num}>{e.correct_count}</Text>
                    <Text style={[s.num, s.total]}>{Math.round(e.total)}</Text>
                  </Body>
                  <CardLink href={{ pathname: '/history', params: { user: e.user_id } }} style={s.hist} pressedOpacity={0.6}>
                    <Ionicons name="time-outline" size={16} color={C.muted} />
                  </CardLink>
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
  body: { flexDirection: 'row', alignItems: 'center', flex: 1 },
  table: { borderWidth: 1, borderColor: C.border, borderRadius: 14, overflow: 'hidden', backgroundColor: C.card },
  row: { flexDirection: 'row', alignItems: 'center', paddingVertical: 10, paddingHorizontal: 12, gap: 8 },
  head: { backgroundColor: C.raised, paddingVertical: 8 },
  headText: { color: C.muted, fontSize: 12, fontWeight: '700', textTransform: 'uppercase' },
  alt: { backgroundColor: '#14201c' },
  mine: { backgroundColor: '#1d3329' },
  rank: { color: C.muted, width: 28, fontWeight: '700' },
  who: { flex: 1, minWidth: 0 },
  name: { color: C.ink, fontWeight: '600' },
  nameMine: { color: C.clay, fontWeight: '800' },
  num: { color: C.ink, width: 62, textAlign: 'right' },
  total: { fontWeight: '800' },
  hist: { paddingLeft: 6, paddingVertical: 4 },
})
