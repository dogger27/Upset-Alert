/*
 * Standings for one draw.
 *
 * Two things here are easy to get subtly wrong, and both would make the app
 * disagree with the website in ways nobody would notice for weeks:
 *
 * 1. DO NOT RE-SORT. The server returns entries already ordered by total
 *    points, then by points in the latest rounds first (Final -> SF -> QF ...).
 *    That tiebreak is lexicographic over the round vector, not a weighted sum,
 *    so any client-side sort by `total` alone silently reorders ties.
 *
 * 2. Ties share a rank, and the next rank skips. Competition ranking:
 *    1, 1, 1, 4 — not 1, 1, 1, 2. Two people genuinely level are level, and
 *    the person behind them is fourth.
 */

import { Link, Stack, useLocalSearchParams } from 'expo-router'
import { useState } from 'react'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { useAuth } from '../../../../../auth'
import { getLeague, getLeagueTournaments, getRoundScores } from '../../../../../api'
import { useApi } from '../../../../../useApi'
import { competitionRanks } from '../../../../../scoring'
import { othersPicksNote } from '../../../../../lock'
import { C } from '../../../../../theme'
import { PlayerName } from '../../../../../cards'
import { Card, CardLink, ErrorNote, Loading, Muted, Screen, Title } from '../../../../../ui'

export default function Standings() {
  const { id, drawId } = useLocalSearchParams()
  const { me } = useAuth()

  const league = useApi(`league:${id}`, () => getLeague(id))
  const draws = useApi(`league:${id}:tournaments`, () => getLeagueTournaments(id))
  const scores = useApi(`scores:${id}:${drawId}`, () => getRoundScores(id, drawId))

  const t = draws.data?.find(x => String(x.tournament?.id) === String(drawId))?.tournament
  const entries = scores.data?.entries || []
  const ranks = competitionRanks(entries)
  /* WHICH NUMBER THE ROWS ARE SORTED BY: the score (the standings, and the
     default), the correct count, or the ceiling. A person's RANK never
     changes with it — it is stamped off the standings order here, and
     travels with the row — so sorting by Max reads as "who can still win
     this" with everyone's real standing still beside their name. Ties keep
     the standings order. */
  const [sortKey, setSortKey] = useState('total')
  const rankOf = new Map(entries.map((e, i) => [e.user_id, ranks[i]]))
  const order = new Map(entries.map((e, i) => [e.user_id, i]))
  const rows = sortKey === 'total' ? entries : [...entries].sort((a, b) =>
    ((b[sortKey] ?? 0) - (a[sortKey] ?? 0)) || (order.get(a.user_id) - order.get(b.user_id)))
  const sortHead = (key, label, style, extra, a11y) => (
    <Pressable onPress={() => setSortKey(key)} hitSlop={8} accessibilityRole="button"
               accessibilityState={{ selected: sortKey === key }}
               accessibilityLabel={a11y ?? `Sort by ${label}`}>
      <Text style={[style, s.headText, sortKey === key && s.headOn]} numberOfLines={1} {...extra}>{label}</Text>
    </Pressable>
  )
  const showReal = !!league.data?.show_real_name

  return (
    <>
      <Stack.Screen options={{ title: t?.name || 'Standings' }} />
      <Screen onRefresh={scores.refetch}>
        {scores.loading && !scores.data ? <Loading /> : null}
        <ErrorNote error={scores.error} onRetry={scores.refetch} />

        {scores.data && (
          <View style={s.bar}>
            <Muted>
              {scores.data.completed_matches_count} matches played
              {t ? ` · ${t.draw_size} draw` : ''}
            </Muted>
            <Link href={`/league/${id}/draw/${drawId}/picks`} style={s.link}>
              Your picks ›
            </Link>
          </View>
        )}

        {scores.data && entries.length === 0 && (
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
              {/* numberOfLines on every header cell, without exception: these
                  are FIXED-WIDTH columns, and "Correct" at 12pt uppercase is
                  wider than 62pt, so it broke as "CORREC / T". Wording follows
                  the dashboard's own — "26 right · 26 pts" — rather than being
                  a second vocabulary for the same two numbers. */}
              <Text style={[s.rank, s.headText]} numberOfLines={1}>#</Text>
              <Text style={[s.who, s.headText]} numberOfLines={1}>Player</Text>
              {/* The site's header, exactly: correct picks out of the matches
                  played so far — the count means nothing without its
                  denominator. Shrinks to fit rather than cutting to "RIG…",
                  which is what a fixed column did to "Right" at a larger
                  text size. */}
              {/* The tick alone; the denominator is what a screen reader
                  hears, and what the line above the table already says. */}
              {sortHead('correct_count', '✓', s.right, null,
                        `Correct picks, of ${scores.data?.completed_matches_count ?? 0} matches played — sort by this`)}
              {/* ONE HEADING OVER TWO COLUMNS: "Score", then "Curr." and
                  "Max" beneath it — where a bracket stands and the best it
                  can still finish on are one fact read two ways. The group
                  is exactly two number cells and the gap between them wide,
                  so the sub-labels sit over their columns. Max: every pick
                  that can yet come true, paid out. Quieter than the score,
                  a possibility beside a fact. */}
              <View style={s.scoreHead}>
                <Text style={[s.headText, s.scoreHeadTitle]} numberOfLines={1}
                      adjustsFontSizeToFit minimumFontScale={0.6}>Score (pts)</Text>
                <View style={s.scoreHeadRow}>
                  {sortHead('total', 'Curr.', s.num, { adjustsFontSizeToFit: true, minimumFontScale: 0.6 })}
                  {sortHead('max_points', 'Max', s.num, { adjustsFontSizeToFit: true, minimumFontScale: 0.6 })}
                </View>
              </View>
            </View>
            {rows.map((e, i) => {
              const mine = me && e.user_id === me.id
              /* THE ROW IS A DOOR TO THEIR BRACKET — the site's sidebar click:
                 once the draw is active or finished, a member's row opens the
                 draw with their picks on it. Before that their picks are
                 sealed (the site says so in a toast), so the row stays a row. */
              const opens = t?.status === 'active' || t?.status === 'completed'
              /* The link wraps the row's BODY and the history button sits
                 beside it — never one link inside another (nested anchors on
                 the web build, the TourCard lesson). */
              const Body = opens ? CardLink : View
              return (
                <View key={e.user_id} style={[s.row, i % 2 ? s.alt : null, mine && s.mine]}>
                <Body
                  href={opens ? { pathname: `/draw/${drawId}`, params: { user: e.user_id, name: e.username } } : undefined}
                  grow style={s.body}
                >
                  {/* The site's place medal, on a finished draw only: a
                      podium mid-tournament would be a prediction. Ties share
                      a place, so two 1sts both get the trophy. */}
                  <Text style={s.rank}>
                    {t?.status === 'completed' && rankOf.get(e.user_id) <= 3
                      ? ['🏆', '🥈', '🥉'][rankOf.get(e.user_id) - 1]
                      : rankOf.get(e.user_id)}
                  </Text>
                  <View style={s.who}>
                    <PlayerName name={e.username} shrinkOnly style={[s.name, mine && s.nameMine]} />
                    {showReal && e.full_name ? (
                      <PlayerName name={e.full_name} style={s.real} />
                    ) : null}
                  </View>
                  {/* The sorted column is the lit one: white and bold, the
                      other two muted. */}
                  <Text style={[s.right, sortKey === 'correct_count' && s.on]}>{e.correct_count}</Text>
                  <Text style={[s.num, sortKey === 'total' && s.on]}>{e.total}</Text>
                  <Text style={[s.num, sortKey === 'max_points' && s.on]}>{e.max_points != null ? Math.round(e.max_points) : '–'}</Text>
                </Body>
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
  /* THE SAME GAP AS THE HEADER ROW. The header's cells are direct children
     of the row and sit 8pt apart; the data cells live inside this link,
     which had no gap, so every column right of the name landed 8pt per
     column further left than its header — the ✓ count sat under the "120"
     however it was aligned. One number, in both places. */
  body: { flexDirection: 'row', alignItems: 'center', flex: 1, gap: 8 },
  bar: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 12 },
  link: { color: C.clay, fontWeight: '700', paddingVertical: 6 },
  table: {
    borderWidth: 1, borderColor: C.border, borderRadius: 14,
    overflow: 'hidden', backgroundColor: C.card,
  },
  row: {
    flexDirection: 'row', alignItems: 'center',
    paddingVertical: 10, paddingHorizontal: 12, gap: 8,
  },
  head: { backgroundColor: C.raised, paddingVertical: 8 },
  headText: { color: C.muted, fontSize: 12, fontWeight: '700', textTransform: 'uppercase' },
  // The header the rows are sorted by.
  headOn: { color: C.greenBright, textDecorationLine: 'underline' },
  alt: { backgroundColor: '#14201c' },
  mine: { backgroundColor: '#1d3329' },
  /* The place is the headline of a standings table; it used to be the dimmest
     thing in the row. Wider too, or a three-figure place clips at this size. */
  rank: { color: C.greenBright, width: 34, fontSize: 16, fontWeight: '700' },
  who: { flex: 1, minWidth: 0 },
  name: { color: C.ink, fontWeight: '600' },
  nameMine: { color: C.clay, fontWeight: '800' },
  real: { color: C.muted, fontSize: 12 },
  /* Centred, like the site: a label fills its cell and a number does not.
     The header is a bare tick now, so the column is the score columns'
     width and the name gets the rest. */
  right: { color: C.muted, width: 46, textAlign: 'center' },
  /* Centred, like the ✓ column and the site: a label fills its cell and a
     number does not, so right-aligning both parked the number under the
     label's last letters instead of under the label. */
  num: { color: C.muted, width: 46, textAlign: 'center' },
  // The column the rows are sorted by.
  on: { color: C.ink, fontWeight: '800' },
  // Two `num` cells and the row's gap: the same width the cells below take.
  scoreHead: { width: 46 * 2 + 8, alignItems: 'center', gap: 2 },
  scoreHeadTitle: { color: C.ink, textAlign: 'center' },
  scoreHeadRow: { flexDirection: 'row', gap: 8 },
})
