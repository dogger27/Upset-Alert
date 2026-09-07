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

import { useMemo, useState } from 'react'
import { Ionicons } from '@expo/vector-icons'
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native'
import { getPredictors } from './api'
import { useApi } from './useApi'
import { C, R, S, T } from './theme'
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
        <Text style={s.title}>Who got it right?</Text>
        {sub ? <Text style={s.sub} numberOfLines={1}>{sub}</Text> : null}
        <View style={s.meta}>
          <View style={[s.pill, s.pillRound]}><Text style={[s.pillText, s.pillRoundText]}>{match?.round_name || '—'}</Text></View>
          <View style={[s.pill, statusStyle]}><Text style={[s.pillText, statusStyle]}>{status}</Text></View>
        </View>

        {q.loading && !d ? <Loading /> : null}
        {q.error ? <Text style={s.err}>Couldn’t load predictions.</Text> : null}

        {d ? (
          <ScrollView style={s.list} contentContainerStyle={{ paddingBottom: S.lg }}>
            {/* BOTH, always, empty or not. A missing heading reads as a
                loading gap or a bug, where "Right (0)" is a fact about the
                match — and a strong one: every pick in the draw has already
                gone out. Holding both positions between matches also lets the
                eye learn where to look.

                Right and wrong even before a result: the server puts a pick
                whose player has already lost into `incorrect`, and that pick
                is not provisionally wrong, it is wrong. */}
            <Group label="Right" tone={C.greenLit} people={d.correct} meId={meId} />
            <Group label="Wrong" tone={C.bad} people={d.incorrect} meId={meId} />
          </ScrollView>
        ) : null}

        <Pressable onPress={onClose} style={s.close} hitSlop={8}>
          <Text style={s.closeText}>Close</Text>
        </Pressable>
      </View>
    </Modal>
  )
}

/* One PLAYER and everyone who backed them, collapsed until asked.
 *
 * A flat list of names repeated the same pick twenty-nine times and made the
 * reader count to learn the only thing the screen is for: how the field
 * split. The pick is the heading now and the names are behind it.
 *
 * FEWEST FIRST. The lopsided side is never the news — on a screen called
 * Upset Alert the three people who went the other way are — and putting the
 * long list last also keeps the short ones above the fold.
 */
function PickBucket({ picked, people, tone, meId, defaultOpen }) {
  const [open, setOpen] = useState(!!defaultOpen)
  return (
    <View style={s.bucket}>
      <Pressable onPress={() => setOpen(o => !o)} hitSlop={6}
                 accessibilityRole="button"
                 accessibilityState={{ expanded: open }}
                 accessibilityLabel={`${picked || 'No pick'}, ${people.length} `
                   + `${people.length === 1 ? 'person' : 'people'}`}
                 style={s.bucketHead}>
        <Ionicons name={open ? 'chevron-down' : 'chevron-forward'}
                  size={14} color={tone} style={s.chev} />
        {/* The FULL name here, where the chips used to carry a surname. The
            surname was right when the pick was a parenthetical on a crowded
            chip; as the heading it is the main fact on the row, and the player
            picked is often not one of the two in the subtitle above — someone
            beaten a round ago. */}
        <Text style={[s.bucketName, { color: tone }]} numberOfLines={1}>
          {picked || 'No pick'}
        </Text>
        <Text style={[s.bucketCount, { color: tone }]}>({people.length})</Text>
      </Pressable>
      {open ? (
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
      ) : null}
    </View>
  )
}

function Group({ label, tone, people, meId }) {
  /* Bucketed by pick, fewest backers first. Ties keep the order the server
     sent, which is already by weight of support. */
  const buckets = useMemo(() => {
    const by = new Map()
    for (const p of people || []) {
      const key = p.picked || ''
      if (!by.has(key)) by.set(key, [])
      by.get(key).push(p)
    }
    return [...by.entries()]
      .map(([picked, list]) => ({ picked, list }))
      .sort((a, b) => a.list.length - b.list.length)
  }, [people])

  return (
    <View style={s.group}>
      <Text style={[s.groupLabel, { color: tone }]}>
        {label} ({(people || []).length})
      </Text>
      {!people?.length ? <Text style={s.none}>No one.</Text> : null}
      <View>
        {buckets.map(b => (
          <PickBucket
            key={b.picked || '_none'} picked={b.picked} people={b.list}
            tone={tone} meId={meId}
            /* Your own pick opens itself: it is the one row a reader came to
               find, and making them hunt for it defeats the collapsing. */
            defaultOpen={meId != null && b.list.some(p => p.id === meId)}
          />
        ))}
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
  /* A pick and its backers. The header is a touch target, so it takes the
     full width and a real row height rather than hugging its text. */
  none: { ...T.tiny, color: C.faint, paddingVertical: 4 },
  bucket: { marginBottom: S.xs },
  bucketHead: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    paddingVertical: 7, paddingHorizontal: 2,
  },
  chev: { width: 14, textAlign: 'center' },
  // The name takes the space and the count sits tight against it, so the
  // count never drifts to the far edge on a short name.
  bucketName: { ...T.smallMed, flexShrink: 1 },
  bucketCount: { ...T.smallMed, opacity: 0.75 },
  // Indented under their heading, so an open bucket reads as belonging to it.
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6,
           paddingLeft: 20, paddingBottom: S.xs },
  chip: {
    backgroundColor: C.raised, borderRadius: R.sm, borderWidth: 1, borderColor: C.border,
    paddingHorizontal: 9, paddingVertical: 4, maxWidth: '100%',
  },
  chipText: { ...T.tiny, color: C.inkBody },
  err: { ...T.small, color: C.bad, textAlign: 'center', paddingVertical: S.md },
  close: { alignSelf: 'center', paddingVertical: S.sm, paddingHorizontal: S.lg },
  closeText: { ...T.smallMed, color: C.clay },
})
