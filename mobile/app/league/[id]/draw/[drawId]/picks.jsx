/*
 * Your picks in one draw, round by round, against what actually happened.
 *
 * This is the detail the standings screen summarises: the standings say you
 * scored 12, this says which twelve. It is a LIST, not a bracket — the web
 * app's bracket is thousands of lines of windowed layout and measured name
 * fitting, and none of that is needed to answer "did I get this one right".
 *
 * Two rendering rules that come from the draw data being genuinely ragged:
 *
 * - An empty slot is NOT a bye. Power-of-two draws have zero byes, and a null
 *   player is simply a match whose feeder has not been played yet. Only
 *   is_bye means a bye.
 * - A qualifier slot is a real entrant with no name yet. It renders as
 *   "Qualifier", not as blank and not as TBD, because that is what the draw
 *   sheet says and what the web app shows.
 */

import { Stack, useLocalSearchParams } from 'expo-router'
import { useMemo } from 'react'
import { StyleSheet, Text, View } from 'react-native'
import { getDraw, getPredictions } from '../../../../../api'
import { useApi } from '../../../../../useApi'
import { C } from '../../../../../theme'
import { Card, ErrorNote, Loading, Muted, Screen, Title } from '../../../../../ui'

function slotLabel(entry, match) {
  // A named entrant always wins: in a bye match one side IS a real player, and
  // labelling both sides "Bye" would hide who received it.
  if (entry?.name) return entry.name
  if (match.is_bye) return 'Bye'
  if (!entry) return 'TBD'
  // Drawn but not yet named. entry_type 'Q' is the qualifier case, and the
  // draw sheet calls it "Qualifier" — not blank, not TBD.
  return entry.entry_type === 'Q' ? 'Qualifier' : 'TBD'
}

export default function Picks() {
  const { id, drawId } = useLocalSearchParams()
  const draw = useApi(`draw:${drawId}`, () => getDraw(drawId))
  const preds = useApi(`preds:${drawId}`, () => getPredictions(drawId))

  const pickBy = useMemo(() => {
    const m = new Map()
    for (const p of preds.data || []) m.set(p.match_id, p.predicted_winner_id)
    return m
  }, [preds.data])

  const rounds = useMemo(() => {
    const byRound = new Map()
    for (const m of draw.data?.matches || []) {
      if (!byRound.has(m.round_number)) byRound.set(m.round_number, [])
      byRound.get(m.round_number).push(m)
    }
    for (const list of byRound.values()) {
      list.sort((a, b) => (a.match_number ?? 0) - (b.match_number ?? 0))
    }
    return [...byRound.entries()].sort((a, b) => a[0] - b[0])
  }, [draw.data])

  // Only decided, non-bye matches can be right or wrong.
  const tally = useMemo(() => {
    let right = 0, decided = 0
    for (const m of draw.data?.matches || []) {
      if (m.is_bye || !m.winner) continue
      const pick = pickBy.get(m.id)
      if (pick == null) continue
      decided += 1
      if (pick === m.winner.id) right += 1
    }
    return { right, decided }
  }, [draw.data, pickBy])

  const loading = (draw.loading && !draw.data) || (preds.loading && !preds.data)
  const refetch = () => { draw.refetch(); preds.refetch() }

  return (
    <>
      <Stack.Screen options={{ title: 'Your picks' }} />
      <Screen onRefresh={refetch} refreshing={draw.loading && !!draw.data}>
        {loading ? <Loading /> : null}
        <ErrorNote error={draw.error || preds.error} onRetry={refetch} />

        {draw.data && (
          <Muted>
            {tally.right} of {tally.decided} decided
            {tally.decided === 0 ? ' — nothing has finished yet' : ''}
          </Muted>
        )}

        {draw.data && (preds.data || []).length === 0 && (
          <Card>
            <Title>No picks in this draw</Title>
            <Muted>You didn’t enter this one.</Muted>
          </Card>
        )}

        {rounds.map(([num, matches]) => (
          <View key={num} style={s.round}>
            <Text style={s.roundName}>
              {matches[0]?.round_name || `Round ${num}`}
            </Text>
            <View style={s.group}>
              {matches.map(m => (
                <MatchRow key={m.id} m={m} pick={pickBy.get(m.id)} />
              ))}
            </View>
          </View>
        ))}
      </Screen>
    </>
  )
}

function MatchRow({ m, pick }) {
  const decided = !!m.winner
  const correct = decided && pick != null && pick === m.winner.id
  const wrong = decided && pick != null && pick !== m.winner.id

  return (
    <View style={s.match}>
      {[m.player1, m.player2].map((p, i) => {
        const picked = p && pick != null && p.id === pick
        const won = decided && p && m.winner.id === p.id
        return (
          <View key={i} style={s.side}>
            <Text
              style={[s.player, won && s.won, picked && s.picked]}
              numberOfLines={1}
            >
              {p?.seed ? <Text style={s.seed}>{p.seed} </Text> : null}
              {slotLabel(p, m)}
            </Text>
            {picked ? (
              <Text style={[s.tag, correct ? s.tagOk : wrong ? s.tagBad : s.tagOpen]}>
                {correct ? '✓' : wrong ? '✗' : 'pick'}
              </Text>
            ) : null}
          </View>
        )
      })}
    </View>
  )
}

const s = StyleSheet.create({
  round: { gap: 6 },
  roundName: {
    color: C.muted, fontSize: 12, fontWeight: '800',
    textTransform: 'uppercase', letterSpacing: 0.6, paddingLeft: 2,
  },
  group: {
    borderWidth: 1, borderColor: C.border, borderRadius: 12,
    overflow: 'hidden', backgroundColor: C.card,
  },
  match: { paddingVertical: 8, paddingHorizontal: 12, gap: 2,
           borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: C.border },
  side: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  player: { color: C.muted, flex: 1, fontSize: 15 },
  seed: { color: C.muted, fontSize: 12 },
  won: { color: C.ink, fontWeight: '700' },
  picked: { color: C.accent },
  tag: { fontSize: 12, fontWeight: '800', width: 34, textAlign: 'right' },
  tagOk: { color: '#4ade80' },
  tagBad: { color: C.error },
  tagOpen: { color: C.muted, fontSize: 10 },
})
