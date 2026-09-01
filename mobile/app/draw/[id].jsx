/*
 * One draw, one round at a time.
 *
 * NOT A SCALED-DOWN BRACKET, and that is the point. The website shows four
 * rounds at once in 252pt columns; two of those on a 393pt phone would be
 * 171pt each — below what the desktop already treats as its minimum, before
 * any name-fitting. One round gets the full width instead, which is MORE room
 * per match than the desktop ever gives it: both names, both seeds and a full
 * score line, with nothing squeezed.
 *
 * What that loses is the shape of the draw — who meets whom two rounds out.
 * The round strip across the top is the answer to that: it says where you are
 * in the draw without pretending a phone can render connectors nobody could
 * follow at that size.
 *
 * Not under a league: you make one set of picks and every league scores the
 * same ones, so reaching a draw should not require choosing a league first.
 */

import { useMemo, useState } from 'react'
import { Stack, useLocalSearchParams } from 'expo-router'
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native'
import { getDraw, getPredictions } from '../../api'
import { useApi } from '../../useApi'
import { slotLabel } from '../../scoring'
import { lockLabel } from '../../lock'
import { currentRound, shortRound } from '../../rounds'
import { C, PICK, R, S, SHADOW, T } from '../../theme'
import { Card, ErrorNote, Loading, Muted, Screen, Title } from '../../ui'

export default function DrawScreen() {
  const { id } = useLocalSearchParams()
  const draw = useApi(`draw:${id}`, () => getDraw(id))
  const preds = useApi(`preds:${id}`, () => getPredictions(id))
  const [picked, setPicked] = useState(null)   // null = follow the live round

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
    for (const list of by.values()) {
      list.sort((a, b) => (a.match_number ?? 0) - (b.match_number ?? 0))
    }
    return [...by.entries()].sort((a, b) => a[0] - b[0])
  }, [draw.data])

  // Follows the live round until the user picks one, then stays put — moving
  // the screen under someone because a match finished elsewhere is worse than
  // being one round stale.
  const active = picked ?? currentRound(rounds)
  const shown = rounds.find(([n]) => n === active) || rounds[0]

  const tally = useMemo(() => {
    let right = 0, decided = 0
    for (const m of draw.data?.matches || []) {
      if (m.is_bye || !m.winner) continue
      const p = pickBy.get(m.id)
      if (p == null) continue
      decided += 1
      if (p === m.winner.id) right += 1
    }
    return { right, decided }
  }, [draw.data, pickBy])

  const loading = (draw.loading && !draw.data) || (preds.loading && !preds.data)
  const refetch = () => { draw.refetch(); preds.refetch() }
  const lock = lockLabel(t)

  return (
    <>
      <Stack.Screen options={{ title: t?.name || 'Draw' }} />
      <Screen onRefresh={refetch} refreshing={draw.loading && !!draw.data} scroll={false}>
        {loading ? <Loading /> : null}
        <ErrorNote error={draw.error} onRetry={refetch} />

        {t && (
          <View style={s.head}>
            <View style={[s.tint, { backgroundColor: t.gender === 'F' ? C.wta : C.atp }]} />
            <View style={s.headBody}>
              <Text style={[T.small, { color: C.muted }]} numberOfLines={1}>
                {[t.category, t.surface, t.draw_size ? `${t.draw_size} draw` : null]
                  .filter(Boolean).join(' · ')}
              </Text>
              <View style={s.headStats}>
                {tally.decided > 0 && (
                  <Text style={[T.smallMed, { color: C.ink }]}>
                    {tally.right} of {tally.decided} right
                  </Text>
                )}
                {lock ? (
                  <Text style={[T.small, { color: lock.urgent ? C.clay : C.muted }]}>
                    {lock.text}
                  </Text>
                ) : null}
              </View>
            </View>
          </View>
        )}

        {rounds.length > 1 && (
          <ScrollView
            horizontal showsHorizontalScrollIndicator={false}
            contentContainerStyle={s.strip}
            style={s.stripWrap}
          >
            {rounds.map(([num, matches]) => {
              const on = num === active
              const done = matches.every(m => m.is_bye || m.winner)
              return (
                <Pressable key={num} onPress={() => setPicked(num)}
                           style={[s.chip, on && s.chipOn]}>
                  <Text style={[T.tiny, {
                    color: on ? C.ink : done ? C.faint : C.muted,
                  }]}>
                    {shortRound(matches[0]?.round_name, num)}
                  </Text>
                </Pressable>
              )
            })}
          </ScrollView>
        )}

        <ScrollView
          contentContainerStyle={s.list}
          showsVerticalScrollIndicator={false}
        >
          {shown ? shown[1].map(m => (
            <MatchRow key={m.id} m={m} pick={pickBy.get(m.id)} />
          )) : null}
          {draw.data && !rounds.length && (
            <Card><Title>No matches yet</Title><Muted>This draw hasn’t been released.</Muted></Card>
          )}
        </ScrollView>
      </Screen>
    </>
  )
}

/* The bracket's match box, ported.
 *
 * THE WHOLE BOX CARRIES THE RESULT — green when your pick came off, red when
 * it did not, amber-bordered when the match is live. The first version put a
 * tick in the corner and left the box grey, which is why a screen of them read
 * as a list rather than a bracket: nothing was scannable without reading.
 *
 * Two rows divided by a hairline, the winner in full ink and the loser dimmed,
 * with the set scores right-aligned in fixed cells so every box lines up down
 * the column.
 */
function MatchRow({ m, pick }) {
  const decided = !!m.winner
  const correct = decided && pick != null && pick === m.winner.id
  const wrong = decided && pick != null && pick !== m.winner.id
  const state = correct ? PICK.correct : wrong ? PICK.wrong : null

  return (
    <View style={[
      s.match,
      state && { backgroundColor: state.bg, borderColor: state.border },
      m.is_bye && { opacity: 0.5 },
    ]}>
      {[m.player1, m.player2].map((p, i) => {
        const isPick = p && pick != null && p.id === pick
        const won = decided && p && m.winner.id === p.id
        const games = m.scores ? m.scores[i] : null
        return (
          <View key={i} style={[s.side, i === 0 && s.sideDivider]}>
            <Text style={[T.tiny, { color: C.faint, width: 16 }]}>
              {p?.seed ?? ''}
            </Text>
            <Text
              style={[
                T.bodyMed,
                { color: decided && !won ? C.muted : C.ink, flex: 1 },
                isPick && !state && { color: C.clay },
                won && { fontFamily: 'Archivo_700Bold' },
              ]}
              numberOfLines={1}
            >
              {slotLabel(p, m)}
            </Text>
            <View style={s.games}>
              {(games || []).map((g, k) => (
                <Text key={k} style={[T.score, {
                  color: decided && !won ? C.muted : C.ink, width: 15, textAlign: 'center',
                }]}>
                  {g === null || g === '' ? '' : g}
                </Text>
              ))}
            </View>
          </View>
        )
      })}
    </View>
  )
}

const s = StyleSheet.create({
  head: {
    flexDirection: 'row', backgroundColor: C.card, borderRadius: R.md,
    borderWidth: 1, borderColor: C.border, overflow: 'hidden',
  },
  tint: { width: 4 },
  headBody: { flex: 1, padding: S.md, gap: 3 },
  headStats: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline', gap: S.md },

  stripWrap: { flexGrow: 0, marginTop: S.sm },
  strip: { gap: S.xs, paddingVertical: 2 },
  chip: {
    paddingHorizontal: S.md, paddingVertical: S.sm, borderRadius: R.pill,
    borderWidth: 1, borderColor: C.border, backgroundColor: C.card, minWidth: 46,
    alignItems: 'center',
  },
  chipOn: { backgroundColor: C.raised, borderColor: C.borderOn },

  list: { gap: S.xs, paddingTop: S.sm, paddingBottom: S.xxl },
  // radius 5 and a 1px border, from BracketView.css — a bracket's boxes are
  // squarer than the app's cards, and that difference is part of reading as one.
  match: {
    backgroundColor: C.card, borderRadius: 5, borderWidth: 1, borderColor: C.borderOn,
    overflow: 'hidden', ...SHADOW,
  },
  // min-height 28 on the web at a 252pt column; 34 here, because a phone gives
  // the column 361pt and the extra goes into being readable.
  side: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    paddingVertical: 6, paddingLeft: 6, paddingRight: 8, minHeight: 34,
  },
  sideDivider: { borderBottomWidth: 1, borderBottomColor: C.border },
  games: { flexDirection: 'row', gap: 4 },
})
