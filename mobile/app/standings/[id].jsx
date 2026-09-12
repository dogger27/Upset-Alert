/*
 * Global standings for one draw — the site's Global "league": every player
 * who entered, classic scoring, no league. Reached from the dashboard's
 * position ("29th of 29") and the draw header's tally, where the site's
 * sidebar shows this list beside the bracket.
 *
 * Same two rules as the league standings, for the same reasons: the server's
 * order is kept (its tiebreak is lexicographic over the round vector), and
 * ties share a rank with the next rank skipped.
 */
import { Stack, useLocalSearchParams, useRouter } from 'expo-router'
import { useCallback, useState } from 'react'
import { Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native'
import { useAuth } from '../../auth'
import { getGlobalRoundScores, listTournaments, getGlobalPositionChances, getGlobalChancesHistory } from '../../api'
import { useApi } from '../../useApi'
import { byFinish, competitionRanks, finishText, pct } from '../../scoring'
import { StandingsFoot, useStandingsView } from '../../standingsTools'
import { othersPicksNote } from '../../lock'
import { C } from '../../theme'
import { PlayerName, TourSwitch } from '../../cards'
import { Card, CardLink, ErrorNote, Loading, Muted, Screen, Title } from '../../ui'

/* WHAT THE CHANCES ARE, in the reader's words, and who the ratings belong to.
   The heading is the natural place to ask; on a phone there is no hover, so
   a tap opens the same explanation the site's tooltip and info sheet carry.
   The credit line is not decoration: Tennis Abstract's Elo is CC BY-NC-SA,
   and attribution is the licence's one condition. */
function explainChances(attribution, sampled) {
  Alert.alert(
    'Win and Top 3',
    'Every way the rest of the draw can still go is played out, and each of ' +
    'those futures is weighted by how likely its results are — a match\u2019s ' +
    'odds come from the players\u2019 Elo ratings on this surface and their ' +
    'rankings, and a match in progress counts its score. Win is the share of ' +
    'those futures this bracket finishes first in; Top 3 the share it finishes ' +
    'on the podium in. A tie for first counts as a win for everyone level.\n\n' +
    (sampled
      ? 'This early there are more futures than can be counted, so a hundred thousand of ' +
        'them are played out instead — accurate to a fraction of a point, and the same every ' +
        'time you look. Once the draw is down to sixteen matches every future is counted ' +
        'exactly and the Finish column appears.\n\n'
      : '') +
    (attribution || 'Elo ratings from Tennis Abstract (CC BY-NC-SA 4.0)') + '.',
  )
}

export default function GlobalStandings() {
  const { id } = useLocalSearchParams()
  const { me } = useAuth()
  const router = useRouter()
  const all = useApi('tournaments', listTournaments)
  /* The round-scores payload, not /standings: same rows, plus the match
     timeline and the what-if worlds the foot of the screen needs. */
  const standings = useApi(`gscores:${id}`, () => getGlobalRoundScores(id))
  const t = (all.data || []).find(x => String(x.id) === String(id))
  /* The two halves of one event: the draws sharing a tournament_id, or the
     name and year where the API has none — the site's own rule. */
  const siblings = (all.data || []).filter(x => t && (
    t.tournament_id != null ? x.tournament_id === t.tournament_id
      : x.name === t.name && x.year === t.year))
  const view = useStandingsView(standings.data, t,
                                pos => getGlobalPositionChances(id, pos), 'g',
                                () => getGlobalChancesHistory(id))
  const entries = view.entries
  const ranks = competitionRanks(entries)
  /* WHICH NUMBER THE ROWS ARE SORTED BY: the score (the standings, and the
     default), the correct count, or the ceiling. A person's RANK never
     changes with it — it is stamped off the standings order here, and
     travels with the row — so sorting by Max reads as "who can still win
     this" with everyone's real standing still beside their name. Ties keep
     the standings order. */
  const [sortKey, setSortKey] = useState('total')
  /* The spinner is the user's pull, nothing else (Screen's rule). */
  const [pulling, setPulling] = useState(false)
  const pull = useCallback(async () => {
    setPulling(true)
    try { await standings.refetch?.() } finally { setPulling(false) }
  }, [standings]) // eslint: the hook object is stable per screen
  const rankOf = new Map(entries.map((e, i) => [e.user_id, ranks[i]]))
  const order = new Map(entries.map((e, i) => [e.user_id, i]))
  const rows = sortKey === 'total' ? entries
    : sortKey === 'finish' ? [...entries].sort(byFinish(order))
    : [...entries].sort((a, b) =>
      ((b[sortKey] ?? 0) - (a[sortKey] ?? 0)) || (order.get(a.user_id) - order.get(b.user_id)))
  /* WHERE EACH BRACKET CAN STILL FINISH, from R16 on: the server enumerates
     every future of the last fifteen matches and sends the best and worst
     place. Before that there are too many futures and the column is not
     drawn — the site does the same. */
  const finishAvail = entries.some(e => e.best_rank != null)
  /* WIN AND PODIUM CHANCES, from the same R16 line as the range and
     the same enumeration — its own flag, because the model can be off
     for a draw whose range is perfectly computable. */
  const oddsAvail = !!standings.data?.odds_available
  const oddsNote = standings.data?.odds_attribution
  const chancesSampled = view.chancesSampled
  /* TOP 3 NEEDS A WIDER PHONE. Five numbers plus a username is more
     than a 393pt row holds, and the name is the column that must not
     give way — the site drops this same column below 400px for the
     same reason. On a 430pt phone both fit with room to spare. */
  const { width: screenW } = useWindowDimensions()
  const podiumCol = oddsAvail && screenW >= 410
  const cashPool = false

  const sortHead = (key, label, style, extra, a11y) => (
    /* SORTED BY A FUTURE, THE SLIDER STOPS WHERE THAT COLUMN BEGINS.
       Finish and both chances come from the same enumeration, so all
       three share the floor: a table ordered by one of them cannot be
       rewound into positions where it is a column of dashes. */
    <Pressable onPress={() => { setSortKey(key)
                                if (key === 'finish') view.clampToFinish() }}
               hitSlop={8} accessibilityRole="button"
               accessibilityState={{ selected: sortKey === key }}
               accessibilityLabel={a11y ?? `Sort by ${label}`}>
      <Text style={[style, s.headText, sortKey === key && s.headOn]} numberOfLines={1} {...extra}>{label}</Text>
    </Pressable>
  )
  const opens = t?.status === 'active' || t?.status === 'completed'

  return (
    <>
      {/* The tour pill beside the title, as the site's popup puts ATP / WTA
          beside the draw name: which draw this is, at a glance. */}
      {/* THE PAIR, AS A SWITCH: a Slam is two draws under one name, and the
          reader looking at one usually wants the other next. Replace, not
          push, so flipping tours does not stack history. */}
      <Stack.Screen options={{ title: t?.name ? `${t.name} · Global` : 'Global standings',
                               headerRight: () => (
                                 <TourSwitch draws={siblings} currentId={t?.id}
                                             onPick={d => router.replace(`/standings/${d.id}`)} />
                               ) }} />
      {/* THE FOOT IS PINNED. The table scrolls in a bounded box and the
          timeline and What if sit beneath it, always on screen — a control
          for the table should not be somewhere past the table's end. The
          pull-to-refresh moves into the box, since that is what scrolls. */}
      <Screen scroll={false}>
        {standings.loading && !standings.data ? <Loading /> : null}
        <ErrorNote error={standings.error} onRetry={standings.refetch} />
        {standings.data && (
          <Muted>{entries.length} entered{t?.draw_size ? ` · ${t.draw_size} draw` : ''}</Muted>
        )}
        {standings.data && entries.length === 0 && (
          <Card>
            <Title>No standings yet</Title>
            <Muted>Nobody has scored in this draw yet.</Muted>
          </Card>
        )}
        {/* The site's sidebar toast, as a line: why a row does not open yet. */}
        {entries.length > 0 && othersPicksNote(t) ? <Muted>{othersPicksNote(t)}</Muted> : null}
        {entries.length > 0 && (
          <ScrollView style={s.scroller} contentContainerStyle={s.scrollerBody} showsVerticalScrollIndicator={false}
                      refreshControl={<RefreshControl refreshing={pulling} onRefresh={pull} tintColor={C.muted} colors={[C.clay]} />}>
          <View style={s.table}>
            <View style={[s.row, s.head, podiumCol && s.tightRow]}>
              <Text style={[s.rank, s.headText]} numberOfLines={1}>#</Text>
              <Text style={[s.who, s.headText]} numberOfLines={1}>Player</Text>
              {/* The site's header. This endpoint carries no matches-played
                  count, so the tick stands alone here. */}
              {/* The tick gives its track to the finish range from R16 on — the
                  site does the same at phone width; the count is a second
                  reading of the score, the range is news. */}
              {finishAvail ? null : sortHead('correct_count', '✓', s.right, null, 'Correct picks — sort by this')}
              {/* ONE HEADING OVER TWO COLUMNS: "Score", then "Curr." and
                  "Max" beneath it — where a bracket stands and the best it
                  can still finish on are one fact read two ways. The group
                  is exactly two number cells and the gap between them wide,
                  so the sub-labels sit over their columns. Max: every pick
                  that can yet come true, paid out. Quieter than the score,
                  a possibility beside a fact. */}
              {/* WITH THE CHANCES, MAX GOES. The phone row cannot carry
                  five numbers, and of the five the ceiling is the one the
                  chances replace: "could still reach 212" answers, less
                  directly, the question "can this still win". One column
                  left, so the two-line heading collapses to a single word —
                  "Score (pts)" over "Curr." was labelling a pair. */}
              {oddsAvail ? sortHead('total', 'Pts', [s.num, s.numTight],
                                    { adjustsFontSizeToFit: true, minimumFontScale: 0.6 },
                                    'Points scored so far — sort by this') : (
                <View style={s.scoreHead}>
                  <Text style={[s.headText, s.scoreHeadTitle]} numberOfLines={1}
                        adjustsFontSizeToFit minimumFontScale={0.6}>Score (pts)</Text>
                  <View style={s.scoreHeadRow}>
                    {sortHead('total', 'Curr.', s.num, { adjustsFontSizeToFit: true, minimumFontScale: 0.6 })}
                    {sortHead('max_points', 'Max', s.num, { adjustsFontSizeToFit: true, minimumFontScale: 0.6 })}
                  </View>
                </View>
              )}
              {finishAvail ? sortHead('finish', oddsAvail ? 'Fin.' : 'Finish', [s.fin, oddsAvail && s.finTight],
                                      { adjustsFontSizeToFit: true, minimumFontScale: 0.6 },
                                      'Best and worst place this bracket can still finish on — sort by this') : null}
              {/* ONE HEADING OVER TWO COLUMNS again, the site's shape: the
                  chance of finishing first and the chance of finishing top
                  three, over every way the draw can still end, each future
                  weighted by who is likely to win the matches left. Finish
                  says what is possible; these say how likely. */}
              {podiumCol ? (
                <View style={s.chanceHead}>
                  <Pressable onPress={() => explainChances(oddsNote, chancesSampled)} hitSlop={8} accessibilityRole="button"
                             accessibilityLabel="What the chances mean">
                    <Text style={[s.headText, s.scoreHeadTitle]} numberOfLines={1}
                          adjustsFontSizeToFit minimumFontScale={0.6}>Chances ⓘ</Text>
                  </Pressable>
                  <View style={s.scoreHeadRow}>
                    {sortHead('p_win', 'Win', s.chance, { adjustsFontSizeToFit: true, minimumFontScale: 0.6 },
                              'Chance of finishing first — sort by this')}
                    {sortHead('p_podium', 'Top 3', s.chance, { adjustsFontSizeToFit: true, minimumFontScale: 0.6 },
                              'Chance of finishing in the top three — sort by this')}
                  </View>
                </View>
              ) : oddsAvail ? (
                /* One column left, so no group to head: "Chances" over a
                   single "Win" is a heading for a pair that is not there,
                   and it does not fit in one cell either. */
                sortHead('p_win', 'Win', s.chance, { adjustsFontSizeToFit: true, minimumFontScale: 0.6 },
                         'Chance of finishing first — sort by this')
              ) : null}
            </View>
            {rows.map((e, i) => {
              const mine = me && e.user_id === me.id
              const Body = opens ? CardLink : View
              return (
                <View key={e.user_id} style={[s.row, i % 2 ? s.alt : null, mine && s.mine]}>
                  <Body href={opens ? { pathname: `/draw/${id}`, params: { user: e.user_id, name: e.username } } : undefined}
                        grow style={[s.body, podiumCol && s.tightRow]}>
                    <Text style={s.rank}>
                      {view.placesDecided && rankOf.get(e.user_id) <= 3 ? ['🏆', '🥈', '🥉'][rankOf.get(e.user_id) - 1] : rankOf.get(e.user_id)}
                    </Text>
                    <View style={s.who}>
                      <PlayerName name={e.podium_locked && cashPool ? `${e.username} 💰` : e.username} shrinkOnly
                                style={[s.name, mine && s.nameMine, e.podium_locked && s.namePodium]} />
                    </View>
                    {/* The sorted column is the lit one: white and bold, the
                      other two muted. */}
                  {finishAvail ? null : <Text style={[s.right, sortKey === 'correct_count' && s.on]}>{e.correct_count}</Text>}
                    <Text style={[s.num, oddsAvail && s.numTight, sortKey === 'total' && s.on]}>{Math.round(e.total)}</Text>
                    {oddsAvail ? null : <Text style={[s.num, sortKey === 'max_points' && s.on]}>{e.max_points != null ? Math.round(e.max_points) : '–'}</Text>}
                    {/* A place clinched is the one certainty in the column,
                        so it reads in ink like the sorted column does. */}
                    {finishAvail ? (
                      <Text style={[s.fin, oddsAvail && s.finTight, (sortKey === 'finish' || (e.best_rank != null && e.best_rank === e.worst_rank)) && s.on]} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.6}
                            accessibilityLabel={e.best_rank == null ? undefined
                              : e.best_rank === e.worst_rank ? `Finishes ${e.best_rank} whatever happens`
                              : `Can still finish anywhere from ${e.best_rank} to ${e.worst_rank}`}>
                        {finishText(e)}
                      </Text>
                    ) : null}
                    {/* 100% has stopped being a probability, so it reads like the
                        fact it is; 0% is out of the race and steps back. */}
                    {oddsAvail ? (
                      <>
                        <Text style={[s.chance, sortKey === 'p_win' && s.on, e.p_win >= 1 && s.chanceSure, e.p_win === 0 && s.chanceOut]}
                              numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.6}>{pct(e.p_win)}</Text>
                        {podiumCol ? (
                          <Text style={[s.chance, sortKey === 'p_podium' && s.on, e.p_podium >= 1 && s.chanceSure, e.p_podium === 0 && s.chanceOut]}
                                      numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.6}>{pct(e.p_podium)}</Text>
                        ) : null}
                      </>
                    ) : null}
                  </Body>
                </View>
              )
            })}
          </View>
          </ScrollView>
        )}
        {entries.length > 0 ? <StandingsFoot view={view} minPos={sortKey === 'finish' ? (view.finishFrom ?? 0) : 0} /> : null}
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
  /* The bounded box the table scrolls in; the foot sits under it. */
  scroller: { flex: 1, minHeight: 0 },
  scrollerBody: { paddingBottom: 4 },
  table: { borderWidth: 1, borderColor: C.border, borderRadius: 14, overflow: 'hidden', backgroundColor: C.card },
  row: { flexDirection: 'row', alignItems: 'center', paddingVertical: 10, paddingHorizontal: 12, gap: 8 },
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
  /* A podium place locked — third or better in every future — in gold, and
     with the money when the draw runs a cash pool. Beats the clay of "me":
     the certainty is the news. */
  namePodium: { color: C.gold, fontWeight: '800' },
  /* Centred, like the site: a label fills its cell and a number does not.
     The header is a bare tick now, so the column is the score columns'
     width and the name gets the rest. */
  right: { color: C.muted, width: 46, textAlign: 'center' },
  /* Centred, like the ✓ column and the site: a label fills its cell and a
     number does not, so right-aligning both parked the number under the
     label's last letters instead of under the label. */
  num: { color: C.muted, width: 46, textAlign: 'center' },
  /* "FINISH" in the header at 12pt bold, "12–29" below; the name column
     gives up the difference. */
  fin: { color: C.muted, width: 52, textAlign: 'center', fontVariant: ['tabular-nums'] },
  // The column the rows are sorted by.
  on: { color: C.ink, fontWeight: '800' },
  // Two `num` cells and the row's gap: the same width the cells below take.
  scoreHead: { width: 46 * 2 + 8, alignItems: 'center', gap: 2 },
  /* Max gone: one track, so the heading is exactly its own cell wide. */
  /* The chances: two cells and the row's gap, the same arithmetic as the
     score heading above. A point smaller than the score, because "100%" is
     four characters where "177" is three and the name must not pay for it. */
  chanceHead: { width: 42 * 2 + 6, alignItems: 'center', gap: 2 },
  chance: { color: C.muted, width: 42, fontSize: 13, textAlign: 'center', fontVariant: ['tabular-nums'] },
  /* A CERTAINTY IN INK, NOT IN BOLD — the site's rule. 100% is one
     character wider than anything else in the column, and bold on top
     of that is what pushed it out of its cell. Weight stays reserved
     for the column the rows are sorted by. */
  chanceSure: { color: C.ink },
  chanceOut: { opacity: 0.45 },
  /* FIVE NUMBERS ON A PHONE ROW, so the four that are not the name give up a
     few pixels each rather than the name giving up all of them. The score is
     three digits and the range four characters at most ("2-13"). */
  numTight: { width: 40 },
  finTight: { width: 44 },
  scoreHeadTitle: { color: C.ink, textAlign: 'center' },
  scoreHeadRow: { flexDirection: 'row', gap: 8 },
  /* SIX, NOT EIGHT, only when all five numbers are in the row: two
     pixels a gap is ten pixels back for the name, which is the one
     column that cannot be narrowed without losing a word. */
  tightRow: { gap: 6 },
})
