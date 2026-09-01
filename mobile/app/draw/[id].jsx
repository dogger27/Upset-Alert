/*
 * One draw: your picks against what actually happened.
 *
 * Deliberately NOT under a league. A draw belongs to the tour, not to a league
 * — you make one set of picks and every league you are in scores the same ones
 * — so reaching it should not require choosing a league first. The league route
 * keeps its own copy for standings context; this is the one the dashboard uses.
 */

import { useMemo } from 'react'
import { Stack, useLocalSearchParams } from 'expo-router'
import { StyleSheet, Text, View } from 'react-native'
import { getDraw, getPredictions } from '../../api'
import { useApi } from '../../useApi'
import { slotLabel } from '../../scoring'
import { lockLabel } from '../../lock'
import { C, R, S, T } from '../../theme'
import { Card, ErrorNote, Eyebrow, Loading, Muted, Pill, Screen, Title } from '../../ui'

export default function DrawScreen() {
  const { id } = useLocalSearchParams()
  const draw = useApi(`draw:${id}`, () => getDraw(id))
  const preds = useApi(`preds:${id}`, () => getPredictions(id))

  const t = draw.data?.tournament
  const pickBy = useMemo(() => {
    const m = new Map()
    for (const p of preds.data || []) m.set(p.match_id, p.predicted_winner_id)
    return m
  }, [preds.data])

  const rounds = useMemo(() => {
    const by = new Map()
    for (const m of draw.data?.matches || []) {
      if (!by.has(m.round_number)) by.set(m.round_number, [])
      by.get(m.round_number).push(m)
    }
    for (const list of by.values()) list.sort((a, b) => (a.match_number ?? 0) - (b.match_number ?? 0))
    return [...by.entries()].sort((a, b) => a[0] - b[0])
  }, [draw.data])

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
  const lock = lockLabel(t)

  return (
    <>
      <Stack.Screen options={{ title: t?.name || 'Draw' }} />
      <Screen onRefresh={refetch} refreshing={draw.loading && !!draw.data}>
        {loading ? <Loading /> : null}
        <ErrorNote error={draw.error || preds.error} onRetry={refetch} />

        {t && (
          <Card tint={t.gender === 'F' ? C.wta : C.atp}>
            <View style={s.top}>
              <Title>{t.name}</Title>
              <Pill tone={t.gender === 'F' ? 'muted' : 'muted'}>
                {t.gender === 'F' ? 'WTA' : 'ATP'}
              </Pill>
            </View>
            <Muted>
              {[t.category, t.surface, t.draw_size ? `${t.draw_size} draw` : null, t.city]
                .filter(Boolean).join(' · ')}
            </Muted>
            {lock ? (
              <Text style={[T.smallMed, { color: lock.urgent ? C.clay : C.muted }]}>
                {lock.text}
              </Text>
            ) : null}
            {tally.decided > 0 && (
              <Text style={[T.bodyMed, { color: C.ink }]}>
                {tally.right} of {tally.decided} right so far
              </Text>
            )}
          </Card>
        )}

        {draw.data && (preds.data || []).length === 0 && (
          <Card><Title>No picks here</Title><Muted>You didn’t enter this draw.</Muted></Card>
        )}

        {rounds.map(([num, matches]) => (
          <View key={num} style={s.round}>
            <Eyebrow>{matches[0]?.round_name || `Round ${num}`}</Eyebrow>
            <View style={s.group}>
              {matches.map(m => <MatchRow key={m.id} m={m} pick={pickBy.get(m.id)} />)}
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
              style={[
                T.small,
                { color: won ? C.ink : C.muted, flex: 1 },
                picked && { color: C.clay },
              ]}
              numberOfLines={1}
            >
              {p?.seed ? <Text style={[T.tiny, { color: C.faint }]}>{p.seed} </Text> : null}
              {slotLabel(p, m)}
            </Text>
            {picked ? (
              <Text style={[T.tiny, {
                color: correct ? C.ok : wrong ? C.bad : C.muted,
                width: 30, textAlign: 'right',
              }]}>
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
  top: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: S.sm },
  round: { gap: S.xs, marginTop: S.sm },
  group: {
    borderWidth: 1, borderColor: C.border, borderRadius: R.md,
    overflow: 'hidden', backgroundColor: C.card,
  },
  match: {
    paddingVertical: S.sm, paddingHorizontal: S.md, gap: 2,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: C.border,
  },
  side: { flexDirection: 'row', alignItems: 'center', gap: S.sm },
})
