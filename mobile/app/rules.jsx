/* The site's Rules page, verbatim — the scoring table is the one thing every
   new player asks about, and it should not need a browser to answer. */
import { Stack } from 'expo-router'
import { ScrollView, StyleSheet, Text, View } from 'react-native'
import { C, R, S, T } from '../theme'
import { Card, Muted, Screen, Title } from '../ui'

const COLS = ['Tier', 'R128/96', 'R64', 'R32', 'R16', 'QF', 'SF', 'F']
const ROWS = [
  ['250', '—', '1', '1', '2', '3', '4', '6'],
  ['500', '—', '1', '1', '2', '4', '8', '12'],
  ['1000', '1', '1', '2', '4', '8', '12', '16'],
  ['Slam', '1', '2', '4', '8', '12', '16', '20'],
]

export default function Rules() {
  return (
    <>
      <Stack.Screen options={{ title: 'Rules' }} />
      <Screen>
        <Card>
          <Title>🎾 Pick the Draw</Title>
          <Muted>
            When a tournament draw is released, predict the winner of every match.
            Each correct pick earns points — later rounds are worth more, and
            higher-tier tournaments offer more points.
          </Muted>
          <ScrollView horizontal showsHorizontalScrollIndicator={false}>
            <View style={s.table}>
              <View style={[s.row, s.head]}>
                {COLS.map((c, i) => <Text key={c} style={[s.cell, i === 0 && s.tier, s.headText]}>{c}</Text>)}
              </View>
              {ROWS.map(r => (
                <View key={r[0]} style={s.row}>
                  {r.map((v, i) => <Text key={i} style={[s.cell, i === 0 && s.tier, i === 0 && s.tierText]}>{v}</Text>)}
                </View>
              ))}
            </View>
          </ScrollView>
          <Muted>
            Tiebreak: if a league is tied when a draw completes, results are weighted
            towards competitors who performed better in the later rounds.
          </Muted>
        </Card>
        <Card>
          <Title>🏆 Leagues</Title>
          <Muted>
            Create a private league to compete with your friends, or compete in the
            Global league against everyone. Compare your progress by round in the
            group standings.
          </Muted>
        </Card>
      </Screen>
    </>
  )
}

const s = StyleSheet.create({
  table: { borderWidth: 1, borderColor: C.border, borderRadius: R.sm, overflow: 'hidden', marginVertical: S.xs },
  row: { flexDirection: 'row' },
  head: { backgroundColor: C.raised },
  cell: { ...T.small, color: C.inkBody, width: 52, textAlign: 'center', paddingVertical: 6, borderRightWidth: StyleSheet.hairlineWidth, borderRightColor: C.border, fontVariant: ['tabular-nums'] },
  headText: { ...T.tiny, color: C.muted, textTransform: 'uppercase' },
  tier: { width: 56, textAlign: 'left', paddingLeft: 8 },
  tierText: { ...T.smallMed, color: C.ink },
})
