/*
 * Who called this match right.
 *
 * Offered only on a COMPLETED match: the endpoint answers for nothing else, and
 * a chip on an undecided match would promise something it cannot deliver.
 *
 * USERNAMES, NOT display_name. display_name on this project is very often the
 * person's real name — it is what the standings deliberately hide behind a
 * league's show_real_name flag — and this endpoint returns BOTH fields with no
 * such flag attached. Rendering display_name here would quietly publish real
 * names to every member of every league, from a screen nobody thinks of as a
 * roster.
 */

import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native'
import { getPredictors } from './api'
import { useApi } from './useApi'
import { C, R, S, T } from './theme'
import { Loading } from './ui'

export function PredictorsSheet({ visible, onClose, drawId, match, meId }) {
  const key = visible && match ? `predictors:${drawId}:${match.id}` : null
  const q = useApi(key, () => getPredictors(drawId, match.id))
  const d = q.data

  const winner = match?.winner?.name

  return (
    <Modal visible={!!visible} animationType="slide" transparent onRequestClose={onClose}>
      <Pressable style={s.scrim} onPress={onClose} />
      <View style={s.sheet}>
        <View style={s.grabber} />
        <Text style={s.title}>Who called it</Text>
        {winner ? <Text style={s.sub} numberOfLines={1}>{winner} won</Text> : null}

        {q.loading && !d ? <Loading /> : null}
        {q.error ? <Text style={s.err}>Couldn’t load predictions.</Text> : null}

        {d ? (
          <ScrollView style={s.list} contentContainerStyle={{ paddingBottom: S.lg }}>
            <Group
              label={`Right (${(d.correct || []).length})`}
              tone={C.greenLit} people={d.correct} meId={meId}
            />
            <Group
              label={`Wrong (${(d.incorrect || []).length})`}
              tone={C.bad} people={d.incorrect} meId={meId}
            />
          </ScrollView>
        ) : null}

        <Pressable onPress={onClose} style={s.close} hitSlop={8}>
          <Text style={s.closeText}>Close</Text>
        </Pressable>
      </View>
    </Modal>
  )
}

function Group({ label, tone, people, meId }) {
  if (!people?.length) return null
  return (
    <View style={s.group}>
      <Text style={[s.groupLabel, { color: tone }]}>{label}</Text>
      <View style={s.chips}>
        {people.map(p => {
          const mine = meId != null && p.id === meId
          return (
            <View key={p.id} style={[s.chip, mine && { borderColor: C.clay }]}>
              <Text style={[s.chipText, mine && { color: C.clay }]} numberOfLines={1}>
                {p.username}
              </Text>
            </View>
          )
        })}
      </View>
    </View>
  )
}

const s = StyleSheet.create({
  scrim: { flex: 1, backgroundColor: '#000a' },
  sheet: {
    backgroundColor: C.card, borderTopLeftRadius: 18, borderTopRightRadius: 18,
    borderTopWidth: 1, borderColor: C.border,
    paddingHorizontal: S.md, paddingTop: S.sm, paddingBottom: S.lg,
    maxHeight: '72%',
  },
  grabber: {
    width: 36, height: 4, borderRadius: 2, backgroundColor: C.border,
    alignSelf: 'center', marginBottom: S.sm,
  },
  title: { ...T.h2, color: C.ink, textAlign: 'center' },
  sub: { ...T.small, color: C.muted, textAlign: 'center', marginTop: 2 },
  list: { marginTop: S.md },
  group: { marginBottom: S.md },
  groupLabel: { ...T.smallMed, marginBottom: S.xs },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chip: {
    backgroundColor: C.raised, borderRadius: R.sm, borderWidth: 1, borderColor: C.border,
    paddingHorizontal: 9, paddingVertical: 4, maxWidth: '100%',
  },
  chipText: { ...T.tiny, color: C.inkBody },
  err: { ...T.small, color: C.bad, textAlign: 'center', paddingVertical: S.md },
  close: { alignSelf: 'center', paddingVertical: S.sm, paddingHorizontal: S.lg },
  closeText: { ...T.smallMed, color: C.clay },
})
