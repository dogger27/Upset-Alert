/*
 * HEAD TO HEAD, as a sheet.
 *
 * The site puts an H2H rail beside every match; a phone has no room for a
 * rail, so the same information arrives as a sheet raised from the match
 * itself. Until 2026-09-23 it arrived as a great deal less: a tally, a surface
 * chip and a list of dates. The owner, holding the two side by side: "the h2h
 * on our RN app sucks compared to the PWA."
 *
 * THE DESIGN, in one line: a comparison spine, and two colours that mean the
 * two players everywhere on the screen.
 *
 *   the spine   a centre column of quiet labels with each player's figure
 *               flanking it — meetings won, meetings on this surface, ranking,
 *               Elo, age, form. The side that leads a row wears a plate in its
 *               OWN colour, so "who is ahead here" is answered by looking down
 *               one column rather than by comparing two numbers six times.
 *   the key     theme.SIDE: brand green is the player on the left, the one
 *               warm clay is the player on the right. Learned once, from the
 *               underline beneath each name, and then reused for the plates
 *               and for the edge of every meeting card. The tour colours
 *               cannot do this job — in a men's match both players are ATP
 *               navy — which is why that pair exists.
 *
 * What the site has and this deliberately does not: a match-to-match pager
 * (the app navigates by tapping another row), a surface filter (the spine
 * already shows both lines at once), and a popup on every form square (one
 * screen, no nested overlays — each square tells a screen reader what it was
 * instead).
 *
 * WHOSE NUMBER IS WHICH is the one thing here that can be wrong without
 * looking wrong, and it is not decided in this file: h2hView.orient resolves
 * the payload against the left player's slug once, and nothing below ever sees
 * the endpoint's own a/b again.
 */

import { useEffect, useMemo, useState } from 'react'
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native'
import { Gesture, GestureDetector, GestureHandlerRootView } from 'react-native-gesture-handler'
import { getH2H, getPairOdds, getPlayerForm } from './api'
import { FitText, FlagSlot, PlayerName } from './cards'
import { nameLines } from './names'
import { shortDay } from './dates'
import { FONT_SCALE, leading } from './fontScale.js'
import { textWidth } from './measure'
import { FORM_GAP, compareRows, formChipText, formChips, formDetail, formGrid, orient, roundWord, shortEvent, singlesOnly }
  from './h2hView.js'
import { ScrollPane } from './scrollPane'
import { Sheet } from './sheet'
import { PredictorsBody } from './predictors'
import { ScoreHistoryBody, clockOf, prettyDuration, useHistory } from './scoreHistory'
import { shortRound } from './rounds'
import { BETTER, C, PICK, R, S, SIDE, T } from './theme'
import { Loading } from './ui'
import { useApi } from './useApi'

// The two rows whose figures are places in a list rather than counts.
const HASHED = new Set(['rank', 'elo'])
// The ✓ / ✗ and the gap before it, for measuring the surname line.
const MARK_W = 26 * FONT_SCALE + 6

/* THE MATCH SHEET (owner, 2026-09-24): one header for the match — its score
   as the title, the arrows, both players with their flags, and on the inside
   of each name the result's tick or cross and the reader's 🤞 — over three
   tabs: Bio (the comparison and form), Meetings (their head-to-head) and
   Prediction (who called it, where the match is a bracket match).

   `status` is { line, winner, live } from score.statusLine; `pickSide` 0/1
   for the side the reader picked; `predictMatch` the site-shaped match the
   Prediction tab asks about (null: no tab). */
export function H2HSheet({ visible, onClose, a, b, surface, drawId, onPrev, onNext,
                           status = null, pickSide = null, predictMatch = null, meId = null,
                           histEntry = null, round = null, initialTab = null, openKey = null }) {
  // Keyed on the pair so switching matches refetches; the backend caches, so a
  // reopen is cheap and there is nothing to memoise here.
  const live = !!(visible && a?.te_slug && b?.te_slug)
  const h2h = useApi(live ? `h2h:${a.te_slug}:${b.te_slug}` : null,
                     () => getH2H(a.te_slug, b.te_slug))
  /* FETCHED APART FROM THE MEETINGS, on purpose: form is one page of Tennis
     Explorer per player and the head-to-head is another, so asking for them
     together would make the whole sheet wait on the slowest of three. Each
     fills in as it lands. */
  const ua = useApi(live ? `ua:${a.te_slug}:${b.te_slug}:${drawId || surface || ''}` : null,
                    () => getPairOdds(a.te_slug, b.te_slug, { surface, drawId }))
  const formA = useApi(live ? `form:${a.te_slug}` : null, () => getPlayerForm(a.te_slug))
  const formB = useApi(live ? `form:${b.te_slug}` : null, () => getPlayerForm(b.te_slug))

  /* WHICH RESULT IS OPEN, across both players' rows — held here rather than
     in each row, so opening one closes the other by construction. The site
     floats a popup over the square; on a phone, inside a sheet, that is an
     overlay on an overlay, so the detail arrives as a line of the card
     itself, under the form it belongs to. */
  const [open, setOpen] = useState(null)
  const [tab, setTab] = useState('bio')
  /* OPENED FOR A REASON (owner, 2026-09-24): the H2H chip opens Bio, "who
     called it" Prediction, a tap on a score Points. Applied on each OPENING
     (openKey), never on stepping to the next match, which keeps the tab. */
  useEffect(() => { if (visible && initialTab) setTab(initialTab) }, [visible, openKey]) // eslint-disable-line react-hooks/exhaustive-deps
  /* POINT HISTORY AND MATCH STATS, once there is play to show (owner,
     2026-09-24) — a live or finished match; `histEntry` is the row the
     history sheet reads. */
  const played = !!histEntry && !!status
  // A tab this match does not have falls back to Bio.
  const shownTab = (tab === 'prediction' && !predictMatch) || ((tab === 'history' || tab === 'stats') && !played)
    ? 'bio' : tab
  /* SWIPE BETWEEN MATCHES (owner, 2026-09-24), the arrows' twin: left for
     the next match, right for the one before. Sideways only — 20pt across
     before it is ours, and any 12pt of vertical first hands the finger to
     the scroll — so reading down the sheet never changes the match. On
     only where the arrows are (the draw); the schedule's sheet has none. */
  const swipe = useMemo(() => Gesture.Pan()
    // Not on the timeline: dragging its slider sideways must never change match.
    .enabled(!!(onPrev || onNext) && shownTab !== 'history')
    .activeOffsetX([-20, 20])
    .failOffsetY([-12, 12])
    .runOnJS(true)
    .onEnd(e => {
      if ((e.translationX < -60 || e.velocityX < -600) && onNext) onNext()
      else if ((e.translationX > 60 || e.velocityX > 600) && onPrev) onPrev()
    }), [onPrev, onNext, shownTab])
  // Stepping to another match (the arrows) closes the result that was open.
  useEffect(() => { setOpen(null) }, [a?.te_slug, b?.te_slug])
  const d = h2h.data
  const view = useMemo(() => orient(d, a?.te_slug), [d, a?.te_slug])
  const rows = useMemo(
    () => compareRows({ view, surface, left: a, right: b,
                        odds: ua.data ? [ua.data.p_a, ua.data.p_b] : null }), [view, surface, a, b, ua.data])

  const [tabsW, setTabsW] = useState(0)
  /* BETWEEN THE NAMES (owner, 2026-09-24): the round, and under it how long
     the match took — or, while it is on, when it started. The duration comes
     with the point history, fetched by the same key the Points tab uses. */
  const { hist: histQ } = useHistory(histEntry, !!visible && played)
  const hd = histQ.data
  const roundText = shortRound(round) || hd?.round_label || null
  const durText = status?.live
    ? (hd?.started_at ? `Started ${clockOf(hd.started_at)}` : null)
    : prettyDuration(hd?.duration_min && hd.duration_min <= 900 ? hd.duration_min : null)
  const nMeet = view?.meetings?.length
  const tabs = [['bio', 'Bio'], ['meetings', nMeet ? `Meetings (${nMeet})` : 'Meetings'],
                ...(predictMatch ? [['prediction', 'Prediction']] : []),
                ...(played ? [['history', 'Points'], ['stats', 'Stats']] : [])]

  /* THE TABS, AS LARGE AS THE ROW ALLOWS (owner, 2026-09-24): one type size
     for every label, the largest at which all of them fit side by side with
     just TAB_PAD either side, and each cell as wide as its own word. Measured
     in bold, the chosen tab's weight, so choosing one never overflows it. */
  // Every cell starts at its own word's width plus padding, and any room
  // left over is shared EQUALLY — so every tab has the same margin around
  // its word (owner, 2026-09-24), not one in proportion to its length.
  const TAB_PAD = 4
  const TAB_RULE = 1.5
  const TAB_MAX = 18 * FONT_SCALE
  const tabUnit = tabs.map(([, l]) => textWidth(l, 'Archivo_700Bold', 1))
  const tabSize = (() => {
    if (!tabsW) return 13 * FONT_SCALE
    const room = tabsW - 1 - tabs.length * 2 * TAB_PAD - (tabs.length - 1) * TAB_RULE   // padding, rules
    return Math.max(8, Math.min(TAB_MAX, (room - 1) / tabUnit.reduce((a, b) => a + b, 0)))
  })()

  return (
    <Sheet visible={!!visible} onClose={onClose} height="92%"
           title={status?.line || 'Upcoming'}
           titleStyle={status?.live ? { color: C.greenLit } : !status ? { color: C.muted } : null}
           titleNav={onPrev !== undefined || onNext !== undefined ? { onPrev, onNext } : undefined}>
      {/* Its own gesture root: a Modal is a separate native tree, outside
          the app's GestureHandlerRootView. */}
      <GestureHandlerRootView style={s.swipeRoot}>
      <GestureDetector gesture={swipe}>
      <View style={s.swipeRoot}>
        {/* THE PLAYERS, on every tab: each name over its side's coloured underline
            (the key the rest of the sheet is read with), sized by measurement
            rather than truncated. */}
        <View style={s.head}>
          {/* FROM THE SCREEN'S EDGE IN (owner, 2026-09-24): the reader's 🤞
              outermost, then the flag, the name, and the result's ✓ or ✗
              right beside it — all over the side's underline. */}
          <View style={s.who}>
            <View style={s.whoLine}>
              {pickSide === 0 ? <PickFingers /> : null}
              <FlagSlot codes={[a?.nationality]} />
              <TwoLineName name={a?.name} won={status?.winner == null ? null : status.winner === 0} />
            </View>
            <View style={[s.rule, { backgroundColor: SIDE.left.line }]} />
          </View>
          <View style={s.mid}>
            {roundText ? <Text style={s.midRound} allowFontScaling={false}>{roundText}</Text> : null}
            {durText ? <Text style={s.midDur} allowFontScaling={false}>{durText}</Text> : null}
          </View>
          <View style={[s.who, s.whoEnd]}>
            <View style={[s.whoLine, s.whoLineEnd]}>
              <TwoLineName name={b?.name} end won={status?.winner == null ? null : status.winner === 1} />
              <FlagSlot codes={[b?.nationality]} />
              {pickSide === 1 ? <PickFingers /> : null}
            </View>
            <View style={[s.rule, { backgroundColor: SIDE.right.line }]} />
          </View>
        </View>

        {/* EVERY TAB IN VIEW AT ONCE, a rule between each; cells as wide as
            their words, the words as large as the row allows (tabSize). */}
        <View style={s.tabs} onLayout={e => setTabsW(e.nativeEvent.layout.width)}>
          {tabs.map(([k, label], i) => (
            <Pressable key={k} onPress={() => setTab(k)} hitSlop={4}
                       style={[s.tabBtn, { flexGrow: 1, flexBasis: tabUnit[i] * tabSize + 2 * TAB_PAD + (i > 0 ? TAB_RULE : 0) },
                               i > 0 && s.tabBtnRule, shownTab === k && s.tabBtnOn]}
                       accessibilityRole="tab" accessibilityState={{ selected: shownTab === k }}>
              <Text style={[s.tab, shownTab === k && s.tabOn, { fontSize: tabSize }]}
                    allowFontScaling={false}>{label}</Text>
            </Pressable>
          ))}
        </View>

        {shownTab === 'history' || shownTab === 'stats' ? (
          <ScoreHistoryBody visible={!!visible} entry={histEntry}
                            part={shownTab === 'history' ? 'timeline' : 'stats'} />
        ) : (
        <ScrollPane style={s.pane} contentContainerStyle={s.body}>
          {shownTab === 'prediction' ? (
            <PredictorsBody drawId={predictMatch.draw_id ?? drawId} match={predictMatch} meId={meId} scroll={false} />
          ) : (
            <>
              {!live && visible ? (
                <Text style={s.none}>No head-to-head record: {!a?.te_slug ? a?.name : b?.name} is not on Tennis Explorer yet.</Text>
              ) : null}
              {h2h.loading && !d ? <Loading /> : null}
              {h2h.error ? <Text style={s.err}>Couldn’t load the head-to-head.</Text> : null}
              {view && shownTab === 'bio' ? (
                <>
                {/* THE SPINE. The label is the axis and the figures flank it, so the
                    eye runs down one narrow column of words while the comparison
                    happens either side of it — rather than reading two numbers and
                    subtracting them, six times. */}
                {rows.length || formA.data?.length || formB.data?.length ? (
                  <View style={s.spine}>
                    {rows.map((r, i) => (
                      <View key={r.key} style={[s.row, i > 0 && s.rowRule]}>
                        <Figure v={r.values[0]} lit={r.better === 0} side="left" hashed={HASHED.has(r.key)} />
                        {r.info ? (
                          /* The ⓘ opens the row's explanation — the standings'
                             "Chances ⓘ" pattern. */
                          <Pressable style={s.labelPress} hitSlop={8} accessibilityRole="button"
                                     accessibilityLabel={`${r.label}: ${r.info}`}
                                     onPress={() => Alert.alert(r.label, r.info)}>
                            <FitText style={s.label} min={8} align="center">{`${r.label} ⓘ`}</FitText>
                          </Pressable>
                        ) : (
                          <FitText style={s.label} min={8} align="center">{r.label}</FitText>
                        )}
                        <Figure v={r.values[1]} lit={r.better === 1} side="right" hashed={HASHED.has(r.key)} />
                      </View>
                    ))}
                    {formA.data?.length || formB.data?.length ? (
                      <View style={[s.row, rows.length > 0 && s.rowRule]}>
                        {/* A NARROWER AXIS FOR THIS ROW ONLY (owner, 2026-09-23:
                            "the W / L pills are still way too small"). The word is
                            four letters and the figures elsewhere need the wide
                            column for "#258"; here that width is better spent on
                            the squares, which is what the row is for. */}
                        <Form form={formA.data} side={0} open={open} onOpen={setOpen} />
                        {/* A PLAIN TEXT OF ITS OWN WIDTH, not FitText: FitText's slot is
                            flex: 1, so the word took a full third of the row
                            and each side's squares only a third too — why
                            raising their size ceiling changed nothing (owner,
                            2026-09-24, asked three times). */}
                        <Text style={[s.label, s.labelNarrow]} allowFontScaling={false}>form</Text>
                        <Form form={formB.data} side={1} end open={open} onOpen={setOpen} />
                      </View>
                    ) : null}
                    {/* THE TAPPED RESULT, said in full. One line for the match and
                        one for where it was — the same two-line shape as a meeting
                        card, because it is the same kind of fact. The edge names
                        whose result it is, in the key the sheet is read with. */}
                    {open ? (
                      <Pressable style={[s.row, s.rowRule, s.detail]} onPress={() => setOpen(null)}
                                 accessibilityRole="button" accessibilityLabel="Close this result">
                        <View style={[s.detailEdge,
                                      { backgroundColor: (open.side === 0 ? SIDE.left : SIDE.right).line }]} />
                        <View style={s.detailBody}>
                          {/* TWO LINES, NOT A CUT (owner's rule, again): "lost to
                              Fancutt T. / Watanabe S. · 6-3,…" is what a fixed line
                              and a long pair of names produce. A card with room
                              below it wraps. */}
                          <Text style={s.detailLine} numberOfLines={2}>
                            <Text style={{ color: open.detail.won ? PICK.correct.border : PICK.wrong.border }}>
                              {open.detail.won ? 'W' : 'L'}
                            </Text>
                            {`  ${open.detail.line}`}
                          </Text>
                          <Text style={s.detailMeta} numberOfLines={2}>
                            {[open.detail.meta, shortDay(open.match.date)].filter(Boolean).join(' · ')}
                          </Text>
                        </View>
                      </Pressable>
                    ) : null}
                  </View>
                ) : null}
                </>
              ) : null}
              {view && shownTab === 'meetings' ? (
                <>
                {/* THE MEETINGS. One card each, with a bar down the winner's own
                    side in the winner's own colour: a column of green edges says one
                    player has owned this rivalry before a single score is read. */}
                {view.meetings.length ? (
                  <>
                    <Text style={s.section}>
                      {view.meetings.length === 1 ? 'Their one meeting'
                        : `All ${view.meetings.length} meetings`}
                    </Text>
                    {view.meetings.map((m, i) => {
                      const side = m.side === 0 ? SIDE.left : SIDE.right
                      return (
                        <View key={`${m.year}-${m.tournament}-${i}`}
                              style={[s.meet, m.side === 1 && s.meetEnd]}>
                          <View style={[s.edge, { backgroundColor: side.line }]} />
                          <View style={s.meetBody}>
                            <View style={s.meetTop}>
                              <PlayerName name={m.side === 0 ? a?.name : b?.name}
                                          style={[s.meetWho, { color: side.ink }]} />
                              {/* A five-set score with two tiebreaks is long, and a
                                  cut score is unreadable in a way a smaller one is
                                  not: shrink, never truncate. */}
                              <FitText style={s.meetScore} min={10} align="right">{m.score}</FitText>
                            </View>
                            <Text style={s.meetMeta} numberOfLines={2}>
                              {[shortEvent(m.tournament), m.year, roundWord(m.round), m.surface]
                                .filter(Boolean).join(' · ')}
                            </Text>
                          </View>
                        </View>
                      )
                    })}
                  </>
                ) : (
                  <Text style={s.none}>They have never met.</Text>
                )}
                </>
              ) : null}
            </>
          )}
        </ScrollPane>
        )}
      </View>
      </GestureDetector>
      </GestureHandlerRootView>
    </Sheet>
  )
}

/* The reader's pick, at the screen's edge, outside that player's flag. Its own box,
   as tall as the emoji needs — inline in a Text line, iOS clipped its top. */
function PickFingers() {
  return <Text style={s.pickInline} allowFontScaling={false} accessibilityLabel="Your pick">🤞</Text>
}

/* The result's mark, beside the surname. */
function ResultMark({ won }) {
  return (
    <Text style={[s.resultMark, { color: won ? C.greenLit : C.lossMark }]} allowFontScaling={false}
          accessibilityLabel={won ? 'Won' : 'Lost'}>{won ? '✓' : '✗'}</Text>
  )
}

/* One figure in the spine. A plate when this side leads the row; ink alone
   when it does not, and a quiet dash where we hold no number — a blank would
   read as a zero, and a zero is a claim. */
function Figure({ v, lit, side, hashed }) {
  // The better figure wears BETTER on either side — see theme.js.
  const tone = BETTER
  const end = side === 'right'
  if (v == null) {
    return (
      <View style={[s.figureWrap, end && s.figureWrapEnd]}>
        <Text style={s.figureNone}>–</Text>
      </View>
    )
  }
  return (
    <View style={[s.figureWrap, end && s.figureWrapEnd]}>
      <View style={[s.plate, lit && { backgroundColor: tone.plate, borderColor: tone.line }]}>
        <Text style={[s.figure, { color: lit ? tone.ink : C.inkBody }]} numberOfLines={1}>
          {hashed ? `#${v}` : `${v}`}
        </Text>
      </View>
    </View>
  )
}

/* Five results, newest first, in the bracket's own pick colours — a green W
   means the same thing there. Each square tells a screen reader what it was
   rather than opening anything. */
function Form({ form, side, end = false, open, onOpen }) {
  /* TEN RESULTS, IN TWO ROWS OF FIVE (owner, 2026-09-23) — the site's own
     depth, and the most a phone can show without the squares becoming a
     barcode.
     MEASURED, NOT ASSUMED, for how many go on a row: five fit this column at
     ordinary text size and fall off the end at 2x, where the label column has
     grown and taken the room from these. So the row asks how wide it is and
     formCount says what that holds; ten chips then wrap into however many
     rows that makes. */
  const [width, setWidth] = useState(null)
  /* THE SQUARES ARE SIZED FROM THE COLUMN, not fixed: five to a row, filling
     the width the row has, which is what brings them up to the word in the
     middle. See h2hView.formChipSize for why the ceiling and the floor. */
  /* FILLING THE HALF (owner, 2026-09-24): the Bio table runs edge to edge
     now, so each side of the form row is wider than the 34pt ceiling was set
     for, and the squares stopped short of the word. The ceiling is lifted to
     what five squares across a phone's half can reach. */
  const { size, per } = formGrid(width, { max: 64 })
  // Two rows of whatever a row holds: ten at ordinary text size, eight where
  // large text has narrowed the column.
  // Singles only: this sheet previews a singles match — see singlesOnly.
  const chips = formChips(singlesOnly(form), per * 2)
  return (
    <View style={[s.formRow, end && s.formRowEnd]}
          onLayout={e => setWidth(e.nativeEvent.layout.width)}>
      {chips.map((c, i) => {
        const showing = open?.side === side && open?.i === i
        return (
          <Pressable key={i} onPress={() => onOpen(showing ? null
            : { side, i, match: c.match, detail: formDetail(c.match) })}
                     hitSlop={2}
                     style={[s.chip, { width: size, height: size },
                             c.result === 'W' ? s.chipWon : s.chipLost,
                             showing && s.chipOpen]}
                     accessibilityRole="button" accessibilityLabel={c.said}
                     accessibilityState={{ selected: showing }}>
            <Text style={[s.chipText, { fontSize: formChipText(size),
                          color: c.result === 'W' ? PICK.correct.border : PICK.wrong.border }]}>
              {c.result}
            </Text>
          </Pressable>
        )
      })}
    </View>
  )
}

/* A SWATCH, NOT A LINE OF TEXT — so it does NOT take the reader's text scale.
   At leading(19) five of them plus their gaps outgrew the column they sit in
   and were cut off against both edges of the sheet on a phone with large text
   (owner's screenshot, 2026-09-23). The letter inside is small and fixed for
   the same reason: it labels a colour, it is not prose. */
/* No CHIP constant any more: the square is measured from the row it sits in
   (h2hView.formChipSize), which is the only way it can fill the column on a
   wide phone and still fit on one with large text. */

/* FIRST NAME OVER SURNAME (owner, 2026-09-24: "two lines for the name").
   The surname is the headline, the first name the line above it; each shrinks
   to its own width rather than wrapping or ending in "…". */
function TwoLineName({ name, end = false, won = null }) {
  const [first, last] = nameLines(name)
  /* PLAIN TEXT, SIZED BY ARITHMETIC — no adjustsFontSizeToFit (owner,
     2026-09-24: names blank, then "miniscule"). iOS's shrink-to-fit reads a
     box's slack or its height as a reason to shrink, and in the fixed header
     it did both. Each line is its style's own size, made smaller only when
     the font's own measurement says it does not fit the column's width. */
  const [w, setW] = useState(0)
  const mark = won == null ? null : <ResultMark won={won} />
  const fit = (text, style) => {
    const base = style.fontSize
    if (!w || !text) return base
    // The ✓ / ✗ rides on the surname line, so that line's width counts it.
    const need = textWidth(text, style.fontFamily, base * FONT_SCALE) + (style === s.whoName && mark ? MARK_W : 0)
    return need <= w - 1 ? base : Math.max(base * 0.7, (base * (w - 1)) / need)
  }
  const line = (text, style, extra) => {
    const size = fit(text, style)
    const t = (
      <Text style={[style, { fontSize: size * FONT_SCALE, lineHeight: Math.round((style.lineHeight * size) / style.fontSize) },
                    end && s.whoNameEnd]}
            allowFontScaling={false}>{text}</Text>
    )
    // The surname carries the mark beside it, toward the middle.
    return (
      <View style={[s.nameRow, end && s.nameRowEnd, extra]}>
        {style === s.whoName && end ? mark : null}{t}{style === s.whoName && !end ? mark : null}
      </View>
    )
  }
  return (
    <View style={s.whoNames} onLayout={e => setW(e.nativeEvent.layout.width)}>
      {first ? line(first, s.whoFirst) : null}
      {line(last, s.whoName, first ? s.whoLast : null)}
    </View>
  )
}

const s = StyleSheet.create({
  /* The scroller runs to the sheet's edges (the sheet pads S.md a side) and
     gives the padding back to its content — so a row can reach the edges
     without the ScrollView clipping it. */
  pane: { marginHorizontal: -S.md },
  body: { paddingBottom: S.md, gap: S.md, paddingHorizontal: S.md },
  /* ONE HEIGHT, WHATEVER IS IN IT (owner, 2026-09-24: "always keep the
     drawer at FULL height"). The sheet used to size to its content, so
     stepping to the next match collapsed it to a spinner and grew it back
     when the data landed, and each tab was a different height. It is a
     fixed 92% of the screen now (owner: "open HIGHER") and this fills
     it; a short tab leaves room below rather than shrinking the sheet. */
  swipeRoot: { flex: 1, minHeight: 0 },

  /* The headline. The record is the widest thing in the row and holds the
     middle; the names take what is left, evenly, and shrink into it. */
  /* BASELINE, NOT BOTTOM (owner, 2026-09-23: "move the h2h score down more,
     in line with the player names"). Aligning the bottoms lined up the boxes
     rather than the type: the tally is a 30pt condensed face whose line box
     carries descender room the names' 15pt one does not, so it floated a
     third of a line above them. On the baseline the three read as one line,
     which is what they are. */
  head: { flexDirection: 'row', alignItems: 'center', gap: S.sm, marginTop: S.xs },
  // The round over the duration, between the two players.
  mid: { alignItems: 'center', gap: 4, flexShrink: 0 },
  midRound: {
    fontFamily: 'Archivo_700Bold', fontSize: 12 * FONT_SCALE, color: C.inkBody, letterSpacing: 0.4,
    paddingHorizontal: 8, paddingVertical: 2, borderWidth: 1, borderColor: C.borderOn, borderRadius: R.pill,
    overflow: 'hidden',
  },
  midDur: { fontFamily: 'Archivo_500Medium', fontSize: 12 * FONT_SCALE, color: C.faint },
  pickInline: { fontSize: 15 * FONT_SCALE, lineHeight: Math.round(22 * FONT_SCALE) },
  nameRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  nameRowEnd: { justifyContent: 'flex-end' },
  /* The tabs, the Points / Serve & Return pair's idiom: words, the chosen one
     in ink with a green underline. */
  /* THE TAB BAR AS COURT LINES (owner, 2026-09-24: "edge to edge, more
     dominant borders, pimp it out"). A band across the whole sheet on the
     sunken ground, ruled top and bottom in the brightest edge the palette
     has, the tabs split by full-height lines like a court's. The chosen tab
     is the one lit patch: court green, white type, and a bright baseline
     along its foot. Everything else stays quiet so that patch is the news. */
  tabs: { flexDirection: 'row', marginTop: S.sm, marginBottom: S.sm, marginHorizontal: -S.md,
          backgroundColor: C.sunken, borderTopWidth: 2, borderBottomWidth: 2, borderColor: C.borderLit },
  tabBtn: { alignItems: 'center', justifyContent: 'center', paddingVertical: 11, paddingHorizontal: 4,
            borderBottomWidth: 3, borderBottomColor: 'transparent', marginBottom: -2 },
  // The line between two tabs, full height.
  tabBtnRule: { borderLeftWidth: 1.5, borderLeftColor: C.borderLit },
  tabBtnOn: { backgroundColor: C.greenDeep, borderBottomColor: C.greenBright },
  /* ONE WEIGHT FOR EVERY TAB (owner, 2026-09-24: margins must be equal). The
     cells are sized from the words in BOLD; an unchosen tab drawn in the
     medium weight was narrower than its cell by an amount that grew with the
     word, so long labels sat in wide margins. Colour alone says which is
     chosen, and choosing one no longer changes any word's width. */
  tab: { ...T.smallMed, fontFamily: 'Archivo_700Bold', color: C.faint },
  tabOn: { color: '#ffffff' },
  /* Tight to the names above and the table below (owner, 2026-09-24: "remove
     all that excess space"): the body's gap cancelled to 2pt either side. */
  resultMark: { fontSize: 20 * FONT_SCALE, lineHeight: Math.round(24 * FONT_SCALE), fontFamily: 'Archivo_700Bold' },
  who: { flex: 1, minWidth: 0, gap: 3, alignSelf: 'flex-end' },
  whoEnd: { alignItems: 'flex-end' },
  whoLine: { flexDirection: 'row', alignItems: 'center', gap: 4, alignSelf: 'stretch' },
  whoLineEnd: { justifyContent: 'flex-end' },
  whoName: { ...T.bodyBold, color: C.ink, flexShrink: 1 },
  whoNames: { flex: 1, minWidth: 0 },

  whoLast: { marginTop: -leading(6) },
  whoFirst: { ...T.small, color: C.inkBody },
  whoNameEnd: { textAlign: 'right' },
  // Two points, so the key reads as a deliberate mark rather than a hairline.
  rule: { height: 2, borderRadius: 1, alignSelf: 'stretch' },

  /* EDGE TO EDGE (owner, 2026-09-24): the Bio table's rows run the full
     width of the screen — ruled top and bottom, no side edges or corners —
     with the figures kept in from the edge by the row's own padding. */
  spine: {
    backgroundColor: C.sunken, marginHorizontal: -S.md,
    borderTopWidth: 1, borderBottomWidth: 1, borderColor: C.border,
  },
  row: { flexDirection: 'row', alignItems: 'center', paddingVertical: 5, paddingHorizontal: S.md },
  rowRule: { borderTopWidth: 1, borderTopColor: C.border },
  /* THE AXIS: one width for every row, so the figures either side line up
     rather than wandering down the card with the length of each word.
     `leading` is what makes it a width and not a trap — it scales with the
     reader's text size exactly as the glyphs inside it do. Fixed at 88 points
     it fitted "meetings won" on my phone and truncated it on a reader with
     large text turned on, which is the one thing this project does not print
     (owner, 2026-09-23: "fix the …"). FitText is the second guard: whatever
     is left after the column has grown, the word shrinks into it. */
  labelPress: { alignItems: 'center', justifyContent: 'center' },
  label: { ...T.tiny, color: C.faint, width: leading(74), textAlign: 'center' },
  // "form" is four letters; the room belongs to the squares either side.
  labelNarrow: { width: Math.ceil(textWidth('form', 'Archivo_500Medium', 11 * FONT_SCALE)) + 10, fontSize: 11 * FONT_SCALE },

  figureWrap: { flex: 1, minWidth: 0, alignItems: 'flex-end' },
  figureWrapEnd: { alignItems: 'flex-start' },
  plate: {
    borderRadius: R.sm, borderWidth: 1, borderColor: 'transparent',
    paddingHorizontal: 7, paddingVertical: 1, minWidth: leading(30), alignItems: 'center',
  },
  figure: { ...T.bodyBold, fontVariant: ['tabular-nums'] },
  figureNone: { ...T.bodyBold, color: C.border },

  /* `overflow: hidden` is the honest backstop, not the plan: five 18pt chips
     and four 3pt gaps are 102 points against the ~120 this column has at any
     text size. It is here so that a future sixth chip is CLIPPED at the
     column's edge rather than drawn over the sheet's. */
  /* Wraps, so ten swatches make two rows of five — and three rows of four on
     a phone with large text, which is the same information either way. */
  formRow: {
    flex: 1, minWidth: 0, flexDirection: 'row', flexWrap: 'wrap', gap: FORM_GAP,
    justifyContent: 'flex-end', overflow: 'hidden',
  },
  formRowEnd: { justifyContent: 'flex-start' },
  chip: {
    borderRadius: R.xs + 1,
    alignItems: 'center', justifyContent: 'center', borderWidth: 1,
  },
  chipWon: { backgroundColor: PICK.correct.bg, borderColor: PICK.correct.border },
  chipLost: { backgroundColor: PICK.wrong.bg, borderColor: PICK.wrong.border },
  chipText: { fontFamily: 'Archivo_700Bold' },
  /* The open one wears the app's own "chosen" ring rather than a brighter
     fill: the fill already says won or lost, and a second meaning in the same
     property would fight it. */
  chipOpen: { borderColor: C.ink, borderWidth: 2 },

  detail: { alignItems: 'stretch', gap: S.sm, paddingVertical: 0, paddingLeft: 0 },
  detailEdge: { width: 3, borderRadius: 2 },
  detailBody: { flex: 1, minWidth: 0, paddingVertical: 5, gap: 1 },
  detailLine: { ...T.smallMed, color: C.inkBody },
  detailMeta: { ...T.tiny, color: C.faint },

  section: { ...T.smallBold, color: C.muted, marginTop: S.xs },
  /* A card the bar belongs to rather than a card with a bar in it: the edge is
     drawn inside the rounded frame, and `row-reverse` puts it on the right
     player's side without moving the text. */
  meet: {
    flexDirection: 'row', backgroundColor: C.raised, borderRadius: R.sm,
    borderWidth: 1, borderColor: C.border, overflow: 'hidden',
  },
  meetEnd: { flexDirection: 'row-reverse' },
  edge: { width: 3 },
  meetBody: { flex: 1, minWidth: 0, paddingVertical: 6, paddingHorizontal: S.sm, gap: 1 },
  meetTop: { flexDirection: 'row', alignItems: 'baseline', gap: S.sm },
  meetWho: { ...T.smallMed, flexShrink: 1 },
  meetScore: { ...T.smallMed, color: C.ink, marginLeft: 'auto', fontVariant: ['tabular-nums'] },
  meetMeta: { ...T.tiny, color: C.faint },

  none: { ...T.small, color: C.muted, textAlign: 'center', paddingVertical: S.lg },
  err: { ...T.small, color: C.bad, textAlign: 'center', paddingVertical: S.md },
})
