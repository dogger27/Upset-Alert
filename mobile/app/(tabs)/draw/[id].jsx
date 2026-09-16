/*
 * One draw, one round at a time.
 *
 * THE SITE'S BRACKET, ONE COLUMN OF IT. The website shows two rounds side by
 * side on a phone in 107pt columns; one round gets the full width here
 * instead, and every match group is the site's own — the same outline, the
 * same graded boxes, the same pill and gap (bracket.jsx has the anatomy and
 * the reasons). What a single column loses is the shape of the draw — who
 * meets whom two rounds out — and the round strip across the top is the
 * answer to that: it says where you are, and a swipe moves one round.
 *
 * Not under a league: you make one set of picks and every league scores the
 * same ones, so reaching a draw should not require choosing a league first.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocalSearchParams, useRouter } from 'expo-router'
import { FONT_SCALE, leading } from '../../../fontScale.js'
import { Ionicons } from '@expo/vector-icons'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { GestureDetector } from 'react-native-gesture-handler'
import { getDraw, getMyStandouts, getPredictions } from '../../../api'
import { useAuth } from '../../../auth'
import { H2HSheet } from '../../../h2h'
import { useLiveUpdates } from '../../../live'
import { ScoreHistorySheet, entryFromMatch } from '../../../scoreHistory'
import { PredictorsSheet } from '../../../predictors'
import { computeDrawRanks } from '../../../drawRanks'
import { hasDrawData, useChoosableTournaments } from '../../../choosableTournaments'
import { nextLiveDraw } from '../../../drawCycle'
import { useApi } from '../../../useApi'
import { currentRound } from '../../../rounds'
import { C, R, S, T } from '../../../theme'
import { TourSwitch } from '../../../cards'
import { Card, ErrorNote, Loading, Muted, Screen, Title } from '../../../ui'
import { BOX_PITCH, CHIP_OVERHANG, CONNECTOR_W, ChampionGroup, GROUP_H, MatchGroup, buildBracket } from '../../../bracket'
import { RoundScrubView, useRoundScrub } from '../../../RoundScrub'
import { RoundStrip } from '../../../RoundStrip'
import { setCurrentDraw } from '../../../currentDraw'

/* The list's vertical rhythm, named because the round scrub lays a round
   out from these before it has measured one (RoundScrub.jsx); the list
   style below reads the same three. */
const ROW_GAP = 14
const LIST_PAD_TOP = S.md
const LIST_PAD_BOTTOM = S.xxl

export default function DrawScreen() {
  const { id, user, name } = useLocalSearchParams()
  const { me } = useAuth()
  const draw = useApi(`draw:${id}`, () => getDraw(id))
  /* ?user= shows ANOTHER member's picks on this bracket — the site's sidebar
     click, reached here from a standings row. Their name rides along in
     ?name= so the banner can say whose picks these are without a second
     request. Null, or my own id, means me. */
  const viewing = user && Number(user) !== me?.id ? Number(user) : null
  const preds = useApi(`preds:${id}:${viewing ?? 'me'}`, () => getPredictions(id, viewing))
  useLiveUpdates(draw.data?.tournament?.id, [`draw:${id}`, 'hist:'])
  /* The site's standout chips: matches where this bracket called a result
     most of the field missed. Follows ?user= like the picks do. */
  const standouts = useApi(`standouts:${id}:${viewing ?? 'me'}`, () => getMyStandouts(id, viewing))
  const standoutIds = useMemo(() => new Set(standouts.data?.match_ids || []), [standouts.data])
  const [picked, setPicked] = useState(null)   // null = follow the live round

  const t = draw.data?.tournament
  /* THE TWO HALVES OF ONE EVENT — the draws sharing a tournament_id, or the
     name and year where the API has none, which is the rule the standings
     screens use. Only ones with a bracket to open: an unreleased other half
     is a switch to a blank page.

     From `all`, not `live`: a finished event still has two halves, and its
     switch must keep working long after it drops out of the live set. */
  const { all: allDraws, live } = useChoosableTournaments()
  const siblings = useMemo(() => allDraws.filter(x => t && hasDrawData(x) && (
    t.tournament_id != null ? x.tournament_id === t.tournament_id
      : x.name === t.name && x.year === t.year
  )), [allDraws, t])

  /* THE NEXT BRACKET BEING PLAYED, anywhere — not the other half of this one.
     Sorted so the cycle has a fixed order a reader can learn: by start date,
     then the men's draw before the women's, then by name. Without that the
     order is whatever the API listed and "next" means something different
     each visit.

     Hidden when every live draw belongs to THIS tournament, because then the
     tour switch beside it already is this control, and two buttons doing one
     thing is worse than one (owner, 2026-09-14). */
  const cycle = useMemo(() => nextLiveDraw(live, t), [live, t])

  /* The header's old sibling ARROWS are not coming back — stepping one at a
     time through a list you cannot see is the thing the Draw tab's chooser
     replaced. The tour switch above is a different control: it names both
     halves and shows which one you are on. */
  const router = useRouter()

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

  const [h2h, setH2H] = useState(null)
  const [predictors, setPredictors] = useState(null)
  const [scoreMatch, setScoreMatch] = useState(null)

  const pickBy = useMemo(() => {
    const m = new Map()
    for (const p of preds.data || []) m.set(p.match_id, p.predicted_winner_id)
    return m
  }, [preds.data])

  /* The bracket as a whole — who fed whom, whose pick stands where, who is
     already out — built once per fetch. Every group on screen reads it; none
     of them could work it out alone, since a box's colour depends on a match
     in the round BEFORE the one being shown. */
  const B = useMemo(
    () => buildBracket(draw.data?.matches || [], draw.data?.draw_entries, pickBy),
    [draw.data, pickBy],
  )
  const rounds = B.rounds
  const roundIdx = useMemo(() => new Map(rounds.map(([n], i) => [n, i])), [rounds])
  /* ONE renderRow PER DATA CHANGE, not per render. The scrub memoises each
     row on its match and on this function; an inline arrow here made every
     mounted match group re-render on every render of this screen — a live
     refetch, a sheet opening, and the landing's own commit, right when the
     scrub had just come to rest (owner: "some lag", 2026-09-09). Everything
     it closes over is memoised on the data or a state setter. */
  const renderRow = useCallback(m => (m.champion
    ? <ChampionGroup m={m} B={B} drawRanks={drawRanks} />
    : <MatchGroup m={m} roundIdx={roundIdx.get(m.round_number) ?? 0} B={B}
                  drawRanks={drawRanks} zone={zone} onH2H={setH2H}
                  onPredictors={setPredictors} onShowScore={setScoreMatch}
                  standout={standoutIds.has(m.id)} />
  ), [B, drawRanks, roundIdx, zone, standoutIds])

  // Follows the live round until the user picks one, then stays put — moving
  // the screen under someone because a match finished elsewhere is worse than
  // being one round stale.
  /* The Draw TAB has to point somewhere, and "the draw" is whichever one you
     are reading — there are two at every slam. Reported here so the tab
     follows you rather than always reopening the same one. */
  useEffect(() => {
    setCurrentDraw(id)
    /* AND LET GO OF THE ROUND. The draw is a tab now, so this screen stays
       mounted when you switch away and comes back holding whatever round you
       had scrubbed to — right for the same draw, wrong for a different one.
       Swapping the men's bracket for the women's from the chooser would
       otherwise land on the old round number, which may not even exist in a
       draw of a different size. Null means "follow the live round" again. */
    setPicked(null)
  }, [id])

  const active = picked ?? currentRound(rounds)
  /* ONE gesture for the whole screen — header, strip and the draw itself:
     a sideways pull scrubs to the next round, telescoping the bracket
     around the finger, and lands on release (RoundScrub.jsx). One swipe
     moves one round. The vertical axis stays the list's. */
  const { pan, scrub } = useRoundScrub({
    rounds, active, onCommit: setPicked,
    rowHeight: GROUP_H, rowGap: ROW_GAP, padTop: LIST_PAD_TOP, padBottom: LIST_PAD_BOTTOM,
    boxPitch: BOX_PITCH,
  })

  const loading = (draw.loading && !draw.data) || (preds.loading && !preds.data)
  const refetch = () => { draw.refetch(); preds.refetch() }

  return (
    <>
      <Screen onRefresh={refetch} scroll={false} style={s.body}>
        <GestureDetector gesture={pan} touchAction="pan-y">
        <View style={s.sheet}>
        {loading ? <Loading /> : null}
        <ErrorNote error={draw.error} onRetry={refetch} />

        {/* THE HEADER, not a card under one. The navigation bar said
            "US Open" and this box said everything else, so the top of the
            screen was two rows saying one thing. The bar is switched off for
            this tab and the name moved in here, beside the tour it belongs
            to: a pink or blue edge, WTA or ATP, and the tournament. */}
        {t && (
          <View style={s.head}>
            <View style={[s.tint, { backgroundColor: t.gender === 'F' ? C.wta : C.atp }]} />
            <View style={s.headBody}>
              {/* THE PAIR, AS A SWITCH. A combined event is two draws under
                  one name, and the reader on one of them usually wants the
                  other next — the standings screens already offer it this
                  way, so the bracket does too. The tour being read wears the
                  badge; the other is greyed and waiting to be pressed. One
                  draw, and TourSwitch renders the plain badge it always did
                  (owner, 2026-09-14).

                  REPLACE, NOT PUSH: flipping tours is changing what you are
                  looking at, not going somewhere new, and pushing would stack
                  a back-button trail of the same event. setCurrentDraw keeps
                  the Draw tab and the Schedule's default in step — the
                  screen's own effect does it too, but not until the new route
                  has mounted. */}
              {/* pairLevel={false}: with both tours up there the level is the
                  same on both pills and the name is what is short of room. */}
              <TourSwitch draws={siblings} currentId={t.id} showLevel pairLevel={false}
                          style={{ alignSelf: 'center' }}
                          onPick={d => { setCurrentDraw(d.id); router.replace(`/draw/${d.id}`) }} />
              {/* THE NAME TAKES THE SLACK, so the step button sits hard
                  against the right edge whatever the tournament is called,
                  and the pill holds the left whatever its tier reads. */}
              <Text style={s.headName} numberOfLines={1}>{t.name}</Text>
            </View>
            {/* ON TO THE NEXT ONE BEING PLAYED. Not the old stepper arrows:
                those walked a list you could not see, one at a time, which is
                what the Draw tab's chooser replaced. This is one step through
                the draws that are actually live, it names its destination to a
                screen reader, and the chooser is still there for going
                anywhere.

                A SIBLING OF headBody, NOT A CHILD OF IT (owner, 2026-09-16: a
                button the full height of the bar). headBody carries the bar's
                horizontal padding, so a child could never reach the right edge
                and could never be taller than that padding allowed. Out here
                it is the tint stripe's opposite number — the stripe is a
                full-height block on the left and this is one on the right, and
                both take the bar's height for free because `head` is a row
                whose alignItems defaults to stretch. `head`'s overflow:hidden
                is what rounds its outer corner to the card's radius. */}
            {cycle && (
              <Pressable onPress={() => { setCurrentDraw(cycle.id); router.replace(`/draw/${cycle.id}`) }}
                         hitSlop={{ top: 9, bottom: 9 }} accessibilityRole="button"
                         accessibilityLabel={`Next draw: ${cycle.name} ${cycle.gender === 'F' ? 'WTA' : 'ATP'}`}
                         style={({ pressed }) => [s.cycle, pressed && { opacity: 0.6 }]}>
                <Ionicons name="chevron-forward" size={leading(20)} color={C.greenLit} />
              </Pressable>
            )}
          </View>
        )}

        {viewing != null && (
          <View style={s.viewing}>
            <Ionicons name="eye-outline" size={14} color={C.info} />
            <Text style={[T.small, { color: C.ink, flex: 1 }]} numberOfLines={1}>
              {preds.error
                // Only match-by-match draws withhold a bracket, and only until
                // every first-round match has started (locking.predictions_visible).
                ? `${name ? `${name}’s` : 'Their'} picks open once every first-round match has started.`
                : `Viewing ${name ? `${name}’s` : 'their'} picks`}
            </Text>
            <Pressable onPress={() => router.setParams({ user: undefined, name: undefined })} hitSlop={8}
                       accessibilityRole="button" accessibilityLabel="Back to my picks">
              <Text style={[T.smallMed, { color: C.clay }]}>Mine</Text>
            </Pressable>
          </View>
        )}

        {/* Every round on one line, and a scrub along it to move between
            them. RoundScrub below is the same journey at fine resolution;
            this is the coarse one. */}
        {rounds.length > 1 && (
          <RoundStrip rounds={rounds} active={active} onPick={setPicked} scrub={scrub} />
        )}

        {/* Swipe sideways to pull the next round in; the row under the
            finger stays under the finger, and the strip's pill glides. */}
        {rounds.length > 0 && (
          <RoundScrubView
            scrub={scrub}
            /* The strip runs edge to edge — into the body's padding both
               sides — so a group's lines can run off the glass rather than
               stopping at the column: the elbow's stub on the right, the
               lines its boxes arrived on to the left. */
            style={s.scrub}
            rounds={rounds}
            columnStyle={s.list}
            renderRow={renderRow}
          />
        )}
        {draw.data && !rounds.length && (
          <Card><Title>No matches yet</Title><Muted>This draw hasn’t been released.</Muted></Card>
        )}
        </View>
        </GestureDetector>
      </Screen>

      {/* One sheet for the whole screen, not one per match: 64 mounted Modals
          is 64 mounted Modals. The match hands it a pair and it fetches. */}
      <H2HSheet visible={!!h2h} onClose={() => setH2H(null)} a={h2h?.a} b={h2h?.b} />
      {/* The site's scoreInsteadOfPick: a started match answers a tap with its
          score and history — its pick is locked by then, so the tap is free to
          mean "show me". Looked up fresh by id so a live match keeps ticking. */}
      <ScoreHistorySheet visible={!!scoreMatch} onClose={() => setScoreMatch(null)}
                         entry={scoreMatch ? entryFromMatch(
                           (draw.data?.matches || []).find(x => x.id === scoreMatch.id) || scoreMatch,
                           Number(id), drawRanks) : null} />
      <PredictorsSheet
        visible={!!predictors} onClose={() => setPredictors(null)}
        drawId={id} match={predictors} meId={me?.id}
      />
    </>
  )
}

const s = StyleSheet.create({
  viewing: {
    flexDirection: 'row', alignItems: 'center', gap: S.sm,
    borderWidth: 1, borderColor: C.info, borderRadius: R.md, backgroundColor: C.card,
    paddingHorizontal: S.md, paddingVertical: S.sm,
  },
  head: {
    flexDirection: 'row', backgroundColor: C.card, borderRadius: R.md,
    borderWidth: 1, borderColor: C.border, overflow: 'hidden',
  },
  tint: { width: 4 },
  /* One row of one line, so it is padded like a header bar rather than a
     card: S.md across and 2pt down — S.xs was still a touch generous for a
     single line (owner, 2026-09-08), and the title's line box is trimmed
     to match, so the banner is as tall as its name and no more. */
  /* minHeight, AND IT IS LOAD-BEARING NOW. The bar used to be as tall as its
     tallest child, and that child was the 24pt circle — so pulling the button
     out of this row would have SHRUNK the bar it is meant to fill. This gives
     the bar a height it chose rather than one it inherited, and leading() so
     it grows with the reader instead of cropping the name. */
  headBody: {
    flex: 1, flexDirection: 'row', alignItems: 'center', gap: 10,
    paddingHorizontal: S.md, paddingVertical: 0, minHeight: leading(26),
  },
  /* The line box is the type's own height: 19pt Saira Condensed needs no
     more than 19 of line, so the banner is exactly the name plus the
     badge's own padding. */
  /* Nudged DOWN, measured off the phone: with the line box at the type's
     own height iOS sets the caps ~1.5pt above the centre of it, and in a
     banner this short that reads as the name floating. A transform, so
     the banner's height is untouched. */
  /* THE BAR'S FULL HEIGHT, and no ring (owner, 2026-09-16). What the ring was
     doing — saying "this is a control" — the block now does better: a filled
     panel on the bar's right edge, the tint stripe's opposite number.
     NO alignSelf and NO height: `head` is a row, its alignItems defaults to
     stretch, so the block takes the bar's height whatever the reader's text
     size makes it. Stating a height here would be the one way to get this
     wrong.
     greenDeep AND greenLit ARE ROUNDSTRIP'S OWN PAIR — the fill and edge of
     the round pager's selected pill, which is this app's established "a green
     block is a control you press". The fill alone is 1.17:1 against the bar,
     so it tints rather than separates; the left border at 5.46:1 is what
     actually cuts the block out of the bar, which is why the owner asked for
     both. A brighter fill was the alternative and it costs more than it buys:
     C.green reads at 2.48:1 but drops the arrow on it from 5.46 to 2.58. */
  cycle: {
    paddingHorizontal: S.sm, alignItems: 'center', justifyContent: 'center',
    backgroundColor: C.greenDeep,
    borderLeftWidth: 1, borderLeftColor: C.greenLit,
  },
  headName: {
    ...T.h2, lineHeight: leading(19), color: C.ink, flex: 1,
    transform: [{ translateY: 1.5 * FONT_SCALE }],
  },


  /* Screen's shared body padding frames every OTHER screen; this one is a
     full-bleed column between two bars and wants neither end of it.

     TOP: S.lg sat the banner a thumb's width below the status bar for no
     reason — the safe-area inset already clears the island, so at zero the
     banner is the first thing under the clock.

     BOTTOM: S.xxl was black space above the tab bar, and worse than idle.
     This screen does not scroll (scroll={false}); the draw list scrolls
     INSIDE it, so bottom padding here shortened the scroll viewport and
     clipped the last match mid-card. The list keeps its own paddingBottom,
     which is the right place for it: that one scrolls.

     Horizontal padding is untouched. */
  body: { paddingTop: 0, paddingBottom: 0 },
  // Fills the screen so the scrub is available over all of it, not only the
  // rows — a gesture you have to find is a gesture nobody uses.
  sheet: { flex: 1 },
  /* Sideways, the column has to make room for what hangs OFF a group: the
     predictors chip on the left border, the H2H chip and the connector elbow
     on the right. RoundScrub clips its strip, so anything past the column's
     edge is simply cut — these paddings are where the overhang lives.
     Vertically, the status pill straddles each outline's top border and
     stands 9pt above it; the gap between groups and the top padding both
     leave it clear — 14 puts 6pt of black between a pill and the group
     above it, which with the scaled-down group fits four on a screen at the
     phone's larger text size (the point of the scale-down). */
  list: {
    gap: ROW_GAP, paddingTop: LIST_PAD_TOP, paddingBottom: LIST_PAD_BOTTOM,
    /* Both sides now reach the glass: the strip runs into the body's padding
       on the left as well, so the lines a box arrived on can run off the
       screen the way the elbow's stub does on the right. The column pads
       the same amount back, so the groups themselves do not move. */
    paddingLeft: CHIP_OVERHANG + S.lg, paddingRight: CONNECTOR_W + S.lg,
  },
  scrub: { marginLeft: -S.lg, marginRight: -S.lg },
})
