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

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocalSearchParams, useRouter } from 'expo-router'
import { leading } from '../../../fontScale.js'
import { Ionicons } from '@expo/vector-icons'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { GestureDetector } from 'react-native-gesture-handler'
import { getDraw, getMyStandouts, getPredictions, savePredictions } from '../../../api'
import {
  blockedByLive, computeNextPicks, picksFromRows, picksMap, projectPicks,
} from '../../../picks'
import { showToast } from '../../../toast'
import { useAuth } from '../../../auth'
import { H2HSheet } from '../../../h2h'
import { FinalGuessBar, FinalGuessSheet } from '../../../finalGuess'
import { useLiveUpdates } from '../../../live'
import { ScoreHistorySheet, entryFromMatch, matchStarted } from '../../../scoreHistory'
import { PredictorsSheet } from '../../../predictors'
import { statusLine } from '../../../score'
import { computeDrawRanks } from '../../../drawRanks'
import { hasDrawData, useChoosableTournaments } from '../../../choosableTournaments'
import { nextLiveDraw } from '../../../drawCycle'
import { invalidate, prime, useApi } from '../../../useApi'
import { currentRound } from '../../../rounds'
import { C, R, S, T } from '../../../theme'
import { DrawHeaderBar } from '../../../drawHeader'
import { Card, ErrorNote, Loading, Muted, Screen, Title } from '../../../ui'
import { BOX_PITCH, CHIP_OVERHANG, CONNECTOR_W, ChampionGroup, GROUP_H, MatchGroup, buildBracket, h2hPairOf } from '../../../bracket'
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
  const predsKey = `preds:${id}:${viewing ?? 'me'}`
  const preds = useApi(predsKey, () => getPredictions(id, viewing))
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
  // THE TIEBREAK QUESTIONS (owner, 2026-09-18): the card shows the answers, the sheet takes them.
  const [finalGuessOpen, setFinalGuessOpen] = useState(false)
  const [finalGuessKey, setFinalGuessKey] = useState(0)
  const [predictors, setPredictors] = useState(null)
  const [scoreMatch, setScoreMatch] = useState(null)

  /* ── MAKING PICKS ────────────────────────────────────────────────────────
     Tapping a player picks them to win the match their box sits in. The
     arithmetic is in picks.js, ported from the site and from what the server
     does on save; this is the screen's half — what is shown, what is sent, and
     what each refused tap says.

     `edits` is null for "whatever the server last told us". A tap fills it
     with the whole PROJECTED set (no match ever shows blank), while the save
     sends the un-projected one (the user's own picks and nothing more). It
     returns to null the moment the save lands — prime() puts the settled rows
     in the cache — or fails, when the server's truth is the only safe thing to
     show. Deliberately not an effect seeded from preds.data: this screen
     refetches on pull and after every save, and state reseeded from fresh data
     is exactly how the app has dropped a reader's input before
     (feedback_effect_reseeds_on_refetch). */
  const [edits, setEdits] = useState(null)
  const serverPicks = useMemo(() => picksFromRows(preds.data), [preds.data])
  const picks = edits || serverPicks
  const pickBy = useMemo(() => picksMap(picks), [picks])

  const drawLocked = !!draw.data?.draw_locked
  /* Matches frozen one at a time under match-by-match locking: the one in play
     AND every match downstream of it, since watching a seed go down 0-6 0-5
     tells you plenty about the quarter-final. The server works this out
     (services/locking._locked_with_downstream) and flags each match, so this
     is a read of its answer rather than a second opinion on the question. */
  const lockedIds = useMemo(
    () => new Set((draw.data?.matches || []).filter(m => m.locked).map(m => m.id)),
    [draw.data],
  )

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
  /* EVERY MATCH WITH A HEAD-TO-HEAD, IN READING ORDER (owner, 2026-09-24):
     down each round top to bottom, then on to the top of the next — what the
     H2H sheet's arrows step through. Matches without one (a bye, a player
     Tennis Explorer never matched) are stepped over, not stopped on. */
  const h2hOrder = useMemo(
    () => rounds.flatMap(([, list]) => list.map(m => h2hPairOf(m, B, { needSlugs: false })).filter(Boolean)),
    [rounds, B])
  /* ONE renderRow PER DATA CHANGE, not per render. The scrub memoises each
     row on its match and on this function; an inline arrow here made every
     mounted match group re-render on every render of this screen — a live
     refetch, a sheet opening, and the landing's own commit, right when the
     scrub had just come to rest (owner: "some lag", 2026-09-09). Everything
     it closes over is memoised on the data or a state setter. */
  /* NOTHING POPS UP WHEN A CHAMPION IS NAMED (owner, 2026-09-18, and the site
     joined this app on 2026-09-22 when the owner asked for its auto-popup to
     go too). A sheet thrown over a bracket the reader is in the middle of
     filling in answers a question nobody asked.

     The way in is FinalGuessBar above the round strip — always on screen,
     which is the other half of that instruction: the card used to sit below
     the final, so "the user needs to scroll to the final to even see it", and
     a bracket that never reached it held last year's average without ever
     being shown the choice. The bar goes red when the answers stop describing
     the picked final.

     `finalRound` went with the card: it existed only to place it. */

  /* Everything a tap needs, read at TAP time rather than closed over.
     handlePick has to be stable: renderRow is memoised on it, and every
     mounted match group re-renders whenever it changes (see renderRow's own
     note below). */
  const latest = useRef({})
  latest.current = {
    picks, matches: draw.data?.matches, entries: draw.data?.draw_entries,
    drawLocked, lockedIds, viewing, meId: me?.id, lockReason: draw.data?.lock_reason,
    drawId: Number(id), predsKey,
    refetchDraw: draw.refetch, refetchPreds: preds.refetch,
  }
  /* AN OUT-OF-ORDER REPLY MUST NOT WIN. Two quick taps are two PUTs, each
     carrying the whole set, and if the first one answers second its rows
     would replace the newer ones on screen. Only the latest save may write. */
  const saveSeq = useRef(0)

  const save = useCallback(async (payload) => {
    const seq = ++saveSeq.current
    const st = latest.current
    try {
      const rows = await savePredictions(st.drawId, payload)
      if (seq !== saveSeq.current) return
      prime(st.predsKey, rows)
      setEdits(null)
      /* Both of these follow from a save: the dashboard's chip counts picks,
         and the card below the final names the two finalists this bracket
         chose, which a pick anywhere in the draw can change. */
      invalidate('entry-status')
      invalidate('final-guess:')
    } catch (e) {
      if (seq !== saveSeq.current) return
      showToast(e?.message || 'Your pick could not be saved')
      /* BACK TO WHAT THE SERVER HOLDS. A refused pick left on screen is the
         worst outcome of the three: the bracket then shows something the
         server never agreed to, and only a reload puts it right. */
      setEdits(null)
      st.refetchPreds()
      // And find out whether the draw locked underneath us — a screen opened
      // before the first ball still holds draw_locked:false, and would go on
      // offering edits it cannot save.
      st.refetchDraw()
    }
  }, [])

  /* EVERY REFUSED TAP SAYS WHY, checked in the order each reason becomes true
     so the toast names the thing actually stopping this pick rather than the
     first rule that happens to apply (TournamentDraw.pickRefusal). A started
     match never reaches here: its tap shows the score instead, which is the
     better answer and needs no words. */
  const handlePick = useCallback((matchId, playerId) => {
    const st = latest.current
    if (!st.meId) { showToast('Sign in to make picks'); return }
    if (st.viewing != null) { showToast('You can only change your own picks'); return }
    if (st.drawLocked) {
      showToast(`Picks are closed — ${st.lockReason || 'the draw has started'}`)
      return
    }
    if (st.lockedIds.has(matchId)) {
      showToast('This match stems from one already under way')
      return
    }
    const next = computeNextPicks(st.picks, matchId, playerId, st.matches)
    /* THE WHOLE CHANGE IS TESTED BEFORE ANY OF IT IS APPLIED. Moving a winner
       clears the path that player was carrying, and if any match on that path
       has started the server refuses those writes — rightly. Asking the same
       question here means nothing moves and nothing has to be put back. */
    if (blockedByLive(st.picks, next, st.lockedIds)) {
      showToast('That would change a match which has already started')
      return
    }
    setEdits(projectPicks(next, st.matches, st.entries))
    save(next)
  }, [save])

  /* ONE SHEET FOR A MATCH (owner, 2026-09-24): the H2H chip, the "who called
     it" chip and a tap on a started score all open the match sheet, on the
     tab that was asked for. A match it cannot show — its players not known
     yet — keeps the old sheet. `open` applies the tab afresh each time. */
  const openSheet = useCallback((m, tab) => {
    const p = h2hPairOf(m, B, { needSlugs: false })
    if (!p) return false
    setH2H({ ...p, tab, open: Date.now() })
    return true
  }, [B])
  const showH2H = useCallback((pair) => setH2H({ ...pair, tab: 'bio', open: Date.now() }), [])
  const showPredictors = useCallback((m) => { if (!openSheet(m, 'prediction')) setPredictors(m) }, [openSheet])
  const showScore = useCallback((m) => { if (!openSheet(m, 'history')) setScoreMatch(m) }, [openSheet])

  /* THE TIEBREAK BUTTON SITS BELOW THE FINAL (owner, 2026-09-18), so a
     reader has to come all the way to the last match to meet it. Leaving it
     alone is an answer in itself — the bracket holds last year's average —
     which is why it can afford to be this far in. */
  const renderRow = useCallback(m => (m.champion
    ? <ChampionGroup m={m} B={B} drawRanks={drawRanks} />
    : (
      <>
        <MatchGroup m={m} roundIdx={roundIdx.get(m.round_number) ?? 0} B={B}
                    drawRanks={drawRanks} zone={zone} onH2H={showH2H}
                    onPredictors={showPredictors} onShowScore={showScore}
                    onPick={handlePick}
                    standout={standoutIds.has(m.id)} />
      </>
    )
  ), [B, drawRanks, roundIdx, zone, standoutIds, handlePick, showH2H, showPredictors, showScore])

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
    // And let go of any pick state belonging to the draw we just left.
    setEdits(null)
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

  /* THE ONE THING A NEW READER HAS TO BE TOLD. Nothing about a player box says
     it is a control, and an empty bracket gives no clue either — so a draw
     that is open and holds no picks yet carries one line, and the first tap
     takes it away for good. */
  const showHint = !viewing && !drawLocked && rounds.length > 0
    && !edits && !Object.keys(serverPicks).length

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
        {/* THE HEADER BAR — shared with the league standings (drawHeader.jsx),
            where the owner asked for this same bar and its next-draw button. */}
        {t && (
          <DrawHeaderBar t={t} siblings={siblings} next={cycle}
                         onPickSibling={d => { setCurrentDraw(d.id); router.replace(`/draw/${d.id}`) }}
                         onNext={d => { setCurrentDraw(d.id); router.replace(`/draw/${d.id}`) }} />
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

        {showHint && (
          <View style={s.hint}>
            <Ionicons name="hand-left-outline" size={leading(13)} color={C.greenLit} />
            <Text style={s.hintText} numberOfLines={1}>Tap a player to pick them to win</Text>
          </View>
        )}

        {/* ABOVE THE ROUND SELECTOR, ALWAYS (owner, 2026-09-22). It used to be
            a card inside the bracket, after the final-round match — four
            rounds away from where anyone is picking on a 32 draw.
            GONE ONCE THE DRAW LOCKS (owner, 2026-09-23): the server refuses
            the answers from then on (put_final_guess, 409), so a bar inviting
            them is a control that cannot do anything. */}
        {!viewing && !drawLocked && (
          <FinalGuessBar tournamentId={Number(id)} enabled refreshKey={finalGuessKey}
                         onOpen={() => setFinalGuessOpen(true)} />
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
      {/* The surface is the DRAW's here — one draw to a page — and one of the
          sheet's comparison rows is "on hard". */}
      {(() => {
        /* The match as the draw holds it NOW — looked up by id each render,
           so a live score in the sheet's title keeps moving. */
        /* Fresh from the draw when it is there, else the match the sheet was
           opened with — a refetch must not make the Points and Stats tabs
           blink out (owner, 2026-09-24: "randomly disappeared"). */
        const hm = h2h ? ((draw.data?.matches || []).find(x => x.id === h2h.matchId) || h2h.match || null) : null
        const decided = hm?.winner?.id != null && hm?.player1?.id != null
        const status = hm ? statusLine({
          winner: decided ? (hm.winner.id === hm.player1.id ? 0 : 1) : null,
          scores: hm.scores, live: !decided && !!(hm.live_scores || hm.live_point),
          live_point: hm.live_point, live_scores: hm.live_scores,
        }) : null
        const pickId = hm ? B.picks?.get(hm.id) : null
        const pickSide = pickId == null ? null : pickId === h2h?.a?.id ? 0 : pickId === h2h?.b?.id ? 1 : null
        const at = h2h ? h2hOrder.findIndex(p => p.matchId === h2h.matchId) : -1
        const prev = at > 0 ? h2hOrder[at - 1] : null
        const next = at >= 0 && at < h2hOrder.length - 1 ? h2hOrder[at + 1] : null
        return (
          <H2HSheet visible={!!h2h} onClose={() => setH2H(null)} a={h2h?.a} b={h2h?.b} drawId={t?.id}
                    surface={draw.data?.surface} status={status} pickSide={pickSide}
                    predictMatch={hm && !hm.is_bye ? hm : null} meId={me?.id}
                    histEntry={hm && matchStarted(hm) ? entryFromMatch(hm, Number(id), drawRanks) : null}
                    round={hm?.round_name ?? null} initialTab={h2h?.tab} openKey={h2h?.open}
                    onPrev={prev ? () => setH2H(prev) : null}
                    onNext={next ? () => setH2H(next) : null} />
        )
      })()}
      <FinalGuessSheet tournamentId={Number(id)} visible={finalGuessOpen} onClose={() => setFinalGuessOpen(false)}
                       onSaved={() => setFinalGuessKey(k => k + 1)} />
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
  /* One line, centred, no box: this is an instruction, not a status, and it
     has to cost the draw as little height as a line of type can. */
  hint: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: S.xs, paddingTop: S.xs,
  },
  hintText: { ...T.small, color: C.muted },
  viewing: {
    flexDirection: 'row', alignItems: 'center', gap: S.sm,
    borderWidth: 1, borderColor: C.info, borderRadius: R.md, backgroundColor: C.card,
    paddingHorizontal: S.md, paddingVertical: S.sm,
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
