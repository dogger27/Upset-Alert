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
import { dateRange, expectedStartLabel } from '../../dates'
import { useAuth } from '../../auth'
import { H2HSheet } from '../../h2h'
import { computeDrawRanks } from '../../drawRanks'
import { useApi } from '../../useApi'
import { slotLabel } from '../../scoring'
import { lockLabel } from '../../lock'
import { currentRound, shortRound } from '../../rounds'
import { C, PICK, R, S, SHADOW, T } from '../../theme'
import { EntryChip, PosBadge, TourBadge } from '../../cards'
import { scoreLine } from '../../score'
import { Card, ErrorNote, Loading, Muted, Screen, Title } from '../../ui'

export default function DrawScreen() {
  const { id } = useLocalSearchParams()
  const { me } = useAuth()
  const draw = useApi(`draw:${id}`, () => getDraw(id))
  const preds = useApi(`preds:${id}`, () => getPredictions(id))
  const [picked, setPicked] = useState(null)   // null = follow the live round

  const t = draw.data?.tournament

  /* WHICH CLOCK an upcoming start is shown in — the site's rule, exactly:
     'venue' means the tournament's own timezone, and ANYTHING ELSE means
     undefined, i.e. this device. The account's `timezone` field is NOT it;
     that is the profile's zone and using it here made the app say
     "Tomorrow at ~1:00 a.m. UTC" where the site said "Today at ~6:00 p.m.
     PDT" — the same instant, a different clock, and no way for a reader to
     know which of the two they were looking at. */
  const zone = me?.schedule_tz === 'venue' ? (t?.venue_timezone || undefined) : undefined

  /* Computed once from draw_entries, not per row: it sorts the whole field. */
  const drawRanks = useMemo(
    () => computeDrawRanks(draw.data?.draw_entries),
    [draw.data?.draw_entries],
  )

  /* Matches carry no te_slug — it lives on draw_entries — so H2H needs this
     bridge. A null slug means the player never matched a Tennis Explorer
     profile, and the button must not be offered for them at all. */
  const slugById = useMemo(() => {
    const m = new Map()
    for (const e of draw.data?.draw_entries || []) if (e.te_slug) m.set(e.id, e.te_slug)
    return m
  }, [draw.data?.draw_entries])

  const [h2h, setH2H] = useState(null)

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
              {/* The draw screen was the one place that never said whose draw
                  it was: no tour, no city, no dates — just "Grand Slam · Hard".
                  With a combined event that made the men's and women's US Open
                  indistinguishable here too, and the screen title alone
                  ("US Open") does not resolve it. */}
              <View style={s.headTitle}>
                <TourBadge gender={t.gender} />
                <Text style={[T.small, { color: C.muted, flexShrink: 1 }]} numberOfLines={1}>
                  {[t.category, t.surface, t.draw_size ? `${t.draw_size} draw` : null]
                    .filter(Boolean).join(' · ')}
                </Text>
              </View>
              {/* `city`, not `location` — the API sends "New York City" under
                  city and leaves location null, so reading location rendered
                  an empty string with no error anywhere. */}
              {(t.city || dateRange(t)) ? (
                <Text style={[T.tiny, { color: C.faint }]} numberOfLines={1}>
                  {[t.city, dateRange(t)].filter(Boolean).join(' · ')}
                </Text>
              ) : null}
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
            <MatchRow key={m.id} m={m} pick={pickBy.get(m.id)} drawRanks={drawRanks}
                      zone={zone} slugById={slugById} onH2H={setH2H} />
          )) : null}
          {draw.data && !rounds.length && (
            <Card><Title>No matches yet</Title><Muted>This draw hasn’t been released.</Muted></Card>
          )}
        </ScrollView>
      </Screen>

      {/* One sheet for the whole screen, not one per match: 64 mounted Modals
          is 64 mounted Modals. The match hands it a pair and it fetches. */}
      <H2HSheet visible={!!h2h} onClose={() => setH2H(null)} a={h2h?.a} b={h2h?.b} />
    </>
  )
}

/* The bracket's match box, ported.
 *
 * THE WHOLE BOX CARRIES THE RESULT — green when your pick came off, red when
 * it did not, background and border together. A tick in the corner of a grey
 * box makes a round read as a list; this makes it scannable without reading.
 *
 * THE SCORE IS A LINE, NOT COLUMNS. The first version gave each set a fixed
 * 15pt cell, so "6(7)" had nowhere to go and wrapped one character per row —
 * a box six hundred points tall with a lone bracket on a line of its own. Sets
 * are a sentence: "6-4  7-5  6⁷-7  6-1", under the names, the way the site
 * puts them under the box.
 */
function MatchRow({ m, pick, drawRanks, zone, slugById, onH2H }) {
  const decided = !!m.winner
  const correct = decided && pick != null && pick === m.winner.id
  const wrong = decided && pick != null && pick !== m.winner.id
  const state = correct ? PICK.correct : wrong ? PICK.wrong : null
  const line = scoreLine(m.scores)
  /* Both players real AND both matched to a TE profile. A qualifier who never
     matched has no slug, and asking the endpoint for one returns nothing
     useful — so the button is simply absent rather than present and empty. */
  const canH2H = !!(m.player1?.id && m.player2?.id && !m.is_bye &&
    slugById?.get(m.player1.id) && slugById?.get(m.player2.id))

  /* Only for a match that has not started. Once there is a result the start
     time is history, and the site drops it there too. */
  const when = !decided && !m.is_bye ? expectedStartLabel(m.expected_start_at, m.expected_source, zone) : null

  return (
    <View style={[
      s.match,
      state && { backgroundColor: state.bg, borderColor: state.border },
      m.is_bye && { opacity: 0.5 },
    ]}>
      {when ? (
        <View style={s.whenRow}>
          <View style={s.schedChip}><Text style={s.schedText}>SCHEDULED</Text></View>
          <Text style={s.whenText} numberOfLines={1}>{when}</Text>
          {m.court ? <Text style={s.courtText} numberOfLines={1}>{m.court}</Text> : null}
        </View>
      ) : null}
      {[m.player1, m.player2].map((p, i) => {
        const isPick = p && pick != null && p.id === pick
        const won = decided && p && m.winner.id === p.id
        return (
          <View key={i} style={[s.side, i === 0 && s.sideDivider]}>
            <PosBadge seed={p?.seed} drawRank={p ? drawRanks[p.id] : null} />
            <Text
              style={[
                T.bodyMed,
                { color: decided && !won ? C.muted : C.ink, flexShrink: 1 },
                isPick && !state && { color: C.clay },
                won && { fontFamily: 'Archivo_700Bold' },
              ]}
              numberOfLines={1}
            >
              {slotLabel(p, m)}
            </Text>
            <EntryChip entryType={p?.entry_type} />
            <View style={{ flex: 1 }} />
            {/* WHO YOU PICKED, always — not only while the match is open.
                The tint says right or wrong; on its own it never says WHICH
                player you backed, and once a match was decided this row lost
                its marker entirely, so a red box left you to infer your own
                pick from the two names. The site marks it with a glyph; so do
                we, and it stays put after the result lands. */}
            {isPick && (
              <Text style={[s.pickMark, { color: state ? state.border : C.clay }]}>
                {correct ? '✓' : wrong ? '✗' : '•'}
              </Text>
            )}
          </View>
        )
      })}
      {(line || canH2H) ? (
        <View style={s.footRow}>
          {line ? (
            <Text style={[s.score, state && { color: state.border }]} numberOfLines={1}>
              {line}
            </Text>
          ) : <View style={{ flex: 1 }} />}
          {canH2H ? (
            <Pressable
              onPress={() => onH2H({
                a: { name: m.player1.name, te_slug: slugById.get(m.player1.id) },
                b: { name: m.player2.name, te_slug: slugById.get(m.player2.id) },
              })}
              hitSlop={8} style={s.h2hChip}
            >
              <Text style={s.h2hText}>H2H</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}
    </View>
  )
}

const s = StyleSheet.create({
  footRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingRight: 2 },
  h2hChip: {
    borderRadius: 4, borderWidth: 1, borderColor: C.borderOn,
    paddingHorizontal: 7, paddingVertical: 2,
  },
  h2hText: { fontFamily: 'Archivo_700Bold', fontSize: 10, lineHeight: 14, letterSpacing: 0.5, color: C.greenLit },
  headTitle: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  whenRow: {
    flexDirection: 'row', alignItems: 'center', gap: 8,
    paddingHorizontal: 10, paddingTop: 8, paddingBottom: 2,
  },
  // The site's SCHEDULED pill: small, outlined, and never competing with a name.
  schedChip: {
    borderRadius: 4, borderWidth: 1, borderColor: '#3b4c8a',
    backgroundColor: '#182140', paddingHorizontal: 5, paddingVertical: 1,
  },
  schedText: { fontFamily: 'Archivo_700Bold', fontSize: 9, lineHeight: 13, letterSpacing: 0.5, color: '#9db4ff' },
  whenText: { ...T.tiny, color: C.muted, flexShrink: 1 },
  courtText: { ...T.tiny, color: C.faint },
  pickMark: { fontFamily: 'Archivo_700Bold', fontSize: 13, marginLeft: 8 },
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
    flexDirection: 'row', alignItems: 'center', gap: 8,
    paddingVertical: 7, paddingHorizontal: 8, minHeight: 34,
  },
  sideDivider: { borderBottomWidth: 1, borderBottomColor: C.border },
  // Under the names, like the site puts it under the box. Tabular so the sets
  // of one match line up with the next one down the column.
  score: {
    fontFamily: 'SairaCondensed_600SemiBold', fontSize: 14, lineHeight: 17,
    color: C.muted, paddingHorizontal: 8, paddingBottom: 7, paddingTop: 1,
    fontVariant: ['tabular-nums'],
  },
})
