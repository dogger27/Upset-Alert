/*
 * Head-to-head, as a sheet.
 *
 * The site puts an H2H rail beside every match; a phone has no room for a rail,
 * so the same information arrives as a sheet raised from the match itself.
 *
 * WHOSE NUMBER IS WHICH is the whole risk here. The endpoint answers in its own
 * order — slug_a / slug_b with wins_a / wins_b — and that order is NOT the order
 * the two players appear in the bracket. Reading wins_a as "the top player" is
 * wrong roughly half the time, and wrong in a way that looks perfectly
 * plausible: a 6-0 record simply points at the wrong man. So everything below
 * is resolved against slug_a rather than against position.
 */

import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native'
import { getH2H } from './api'
import { useApi } from './useApi'
import { C, R, S, T } from './theme'
import { Loading } from './ui'

export function H2HSheet({ visible, onClose, a, b }) {
  // Keyed on the pair so switching matches refetches; the backend caches, so a
  // reopen is cheap and there is nothing to memoise here.
  const key = visible && a?.te_slug && b?.te_slug ? `h2h:${a.te_slug}:${b.te_slug}` : null
  const h2h = useApi(key, () => getH2H(a.te_slug, b.te_slug))
  const d = h2h.data

  // a is the player shown FIRST in the bracket; the payload's slug_a may be
  // either of them. Everything downstream reads through this one flip.
  const flipped = d ? d.slug_a !== a?.te_slug : false
  const winsTop = d ? (flipped ? d.wins_b : d.wins_a) : null
  const winsBot = d ? (flipped ? d.wins_a : d.wins_b) : null

  return (
    <Modal visible={!!visible} animationType="slide" transparent onRequestClose={onClose}>
      <Pressable style={s.scrim} onPress={onClose} />
      <View style={s.sheet}>
        <View style={s.grabber} />
        <Text style={s.title}>Head to head</Text>

        {h2h.loading && !d ? <Loading /> : null}
        {h2h.error ? <Text style={s.err}>Couldn’t load the head-to-head.</Text> : null}

        {d ? (
          <>
            <View style={s.tallyRow}>
              <Text style={[s.name, { textAlign: 'left' }]} numberOfLines={2}>{a?.name}</Text>
              <Text style={s.tally}>{winsTop}–{winsBot}</Text>
              <Text style={[s.name, { textAlign: 'right' }]} numberOfLines={2}>{b?.name}</Text>
            </View>

            {/* Surface splits, each read through the same flip. */}
            <View style={s.surfRow}>
              {Object.entries(d.surface_wins || {}).map(([surf, pair]) => {
                const top = flipped ? pair[1] : pair[0]
                const bot = flipped ? pair[0] : pair[1]
                return (
                  <View key={surf} style={s.surf}>
                    <Text style={s.surfName}>{surf}</Text>
                    <Text style={s.surfVal}>{top}–{bot}</Text>
                  </View>
                )
              })}
            </View>

            <ScrollView style={s.list} contentContainerStyle={{ paddingBottom: S.lg }}>
              {(d.matches || []).map((m, i) => {
                // 'a'/'b' in a match row refer to the PAYLOAD's a/b, so the same
                // flip decides whether the bracket's top player won it.
                const topWon = flipped ? m.winner === 'b' : m.winner === 'a'
                return (
                  <View key={i} style={s.match}>
                    <Text style={s.matchWho} numberOfLines={1}>
                      {topWon ? a?.name : b?.name}
                    </Text>
                    <Text style={s.matchMeta} numberOfLines={1}>
                      {[m.year, m.tournament, m.round, m.surface].filter(Boolean).join(' · ')}
                    </Text>
                    <Text style={s.matchScore} numberOfLines={1}>{m.score}</Text>
                  </View>
                )
              })}
              {(d.matches || []).length === 0 && (
                <Text style={s.none}>They have never met.</Text>
              )}
            </ScrollView>
          </>
        ) : null}

        <Pressable onPress={onClose} style={s.close} hitSlop={8}>
          <Text style={s.closeText}>Close</Text>
        </Pressable>
      </View>
    </Modal>
  )
}

const s = StyleSheet.create({
  scrim: { flex: 1, backgroundColor: '#000a' },
  sheet: {
    backgroundColor: C.card, borderTopLeftRadius: 18, borderTopRightRadius: 18,
    borderTopWidth: 1, borderColor: C.border,
    paddingHorizontal: S.md, paddingTop: S.sm, paddingBottom: S.lg,
    maxHeight: '78%',
  },
  grabber: {
    width: 36, height: 4, borderRadius: 2, backgroundColor: C.border,
    alignSelf: 'center', marginBottom: S.sm,
  },
  title: { ...T.h2, color: C.ink, textAlign: 'center', marginBottom: S.sm },
  tallyRow: { flexDirection: 'row', alignItems: 'center', gap: S.sm },
  name: { ...T.smallMed, color: C.inkBody, flex: 1 },
  tally: { ...T.display, color: C.ink, fontSize: 26 },
  surfRow: { flexDirection: 'row', gap: S.sm, marginTop: S.md, flexWrap: 'wrap' },
  surf: {
    backgroundColor: C.raised, borderRadius: R.sm, borderWidth: 1, borderColor: C.border,
    paddingHorizontal: 8, paddingVertical: 4, alignItems: 'center', minWidth: 62,
  },
  surfName: { ...T.tiny, color: C.faint },
  surfVal: { ...T.smallMed, color: C.ink },
  list: { marginTop: S.md },
  match: { paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: C.border },
  matchWho: { ...T.smallMed, color: C.ink },
  matchMeta: { ...T.tiny, color: C.faint },
  matchScore: { ...T.tiny, color: C.muted },
  none: { ...T.small, color: C.muted, textAlign: 'center', paddingVertical: S.lg },
  err: { ...T.small, color: C.error, textAlign: 'center', paddingVertical: S.md },
  close: { alignSelf: 'center', paddingVertical: S.sm, paddingHorizontal: S.lg },
  closeText: { ...T.smallMed, color: C.clay },
})
