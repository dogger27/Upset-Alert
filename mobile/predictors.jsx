/*
 * Who called this match right — or, before it is decided, whose pick is still
 * standing and whose has already gone out.
 *
 * Offered on every real match. Undecided (`pending`), the server puts anyone
 * whose pick has not lost yet in `correct`, the rest in `incorrect`, names the
 * pick on both, and orders each by how many backed that player.
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
import { BADGE, C, R, S, T } from './theme'
import { leading } from './fontScale'
import { Loading } from './ui'

export function PredictorsSheet({ visible, onClose, drawId, match, meId }) {
  const key = visible && match ? `predictors:${drawId}:${match.id}` : null
  const q = useApi(key, () => getPredictors(drawId, match.id))
  const d = q.data

  const winner = match?.winner?.name
  const pending = !match?.winner
  // Names only once the ACTUAL players are known; the round and status pills
  // below are always there.
  const known = !!(match?.player1?.name && match?.player2?.name)
  const sub = pending
    ? (known ? `${match.player1.name} vs. ${match.player2.name}` : null)
    : winner ? `${winner} won` : null
  const live = pending && !!(match?.live_scores || match?.live_point)
  const status = !pending ? 'Completed' : !known ? 'TBD' : live ? 'In Progress' : 'Upcoming'
  const statusStyle = !pending ? s.pillDone : !known ? s.pillTbd : live ? s.pillLive : s.pillUpcoming

  return (
    <Modal visible={!!visible} animationType="slide" transparent onRequestClose={onClose}>
      <Pressable style={s.scrim} onPress={onClose} />
      <View style={s.sheet}>
        <View style={s.grabber} />
        <Text style={s.title}>{pending ? 'Who’s still in it' : 'Who called it'}</Text>
        {sub ? <Text style={s.sub} numberOfLines={1}>{sub}</Text> : null}
        <View style={s.meta}>
          <View style={[s.pill, s.pillRound]}><Text style={[s.pillText, s.pillRoundText]}>{match?.round_name || '—'}</Text></View>
          <View style={[s.pill, statusStyle]}><Text style={[s.pillText, statusStyle]}>{status}</Text></View>
        </View>

        {q.loading && !d ? <Loading /> : null}
        {q.error ? <Text style={s.err}>Couldn’t load predictions.</Text> : null}

        {d ? (
          <ScrollView style={s.list} contentContainerStyle={{ paddingBottom: S.lg }}>
            <Group
              label={`${pending ? 'Still in it' : 'Right'} (${(d.correct || []).length})`}
              tone={pending ? BADGE.seeded.fg : C.greenLit} people={d.correct} meId={meId}
            />
            <Group
              label={`${pending ? 'Out' : 'Wrong'} (${(d.incorrect || []).length})`}
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

/** "Sho Shimabukuro" → "Shimabukuro": surname only, as on the site. A
    two-word surname ("Díaz Acosta") stays whole. */
function shortName(raw) {
  const parts = String(raw || '').trim().split(/\s+/)
  return parts.length > 1 ? parts.slice(1).join(' ') : raw
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
                {p.username}{p.picked ? ` (${shortName(p.picked)})` : ''}
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
  meta: { flexDirection: 'row', justifyContent: 'center', gap: 6, marginTop: 6 },
  // The draw's SCHEDULED chip, one per state. `color` on the pill style is
  // read by the Text, borderColor/backgroundColor by the View.
  pill: { borderRadius: 4, borderWidth: 1, paddingHorizontal: 6, paddingVertical: 1 },
  pillText: { fontFamily: 'Archivo_700Bold', fontSize: 9, lineHeight: leading(13), letterSpacing: 0.5 },
  pillRound: { borderColor: C.border, backgroundColor: C.raised },
  pillRoundText: { color: C.inkBody },
  pillLive: { borderColor: C.greenLit, backgroundColor: C.raised, color: C.greenLit },
  pillUpcoming: { borderColor: '#3b4c8a', backgroundColor: '#182140', color: '#9db4ff' },
  pillDone: { borderColor: C.border, backgroundColor: C.raised, color: C.muted },
  pillTbd: { borderColor: C.border, borderStyle: 'dashed', backgroundColor: 'transparent', color: C.muted },
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
