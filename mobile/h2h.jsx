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

import { useMemo, useState } from 'react'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { getH2H, getPlayerForm } from './api'
import { FitText, FlagSlot, PlayerName } from './cards'
import { shortDay } from './dates'
import { leading } from './fontScale.js'
import { compareRows, formChips, formCount, formDetail, orient } from './h2hView.js'
import { ScrollPane } from './scrollPane'
import { Sheet } from './sheet'
import { C, PICK, R, S, SIDE, T } from './theme'
import { Loading } from './ui'
import { useApi } from './useApi'

// The two rows whose figures are places in a list rather than counts.
const HASHED = new Set(['rank', 'elo'])

export function H2HSheet({ visible, onClose, a, b, surface }) {
  // Keyed on the pair so switching matches refetches; the backend caches, so a
  // reopen is cheap and there is nothing to memoise here.
  const live = !!(visible && a?.te_slug && b?.te_slug)
  const h2h = useApi(live ? `h2h:${a.te_slug}:${b.te_slug}` : null,
                     () => getH2H(a.te_slug, b.te_slug))
  /* FETCHED APART FROM THE MEETINGS, on purpose: form is one page of Tennis
     Explorer per player and the head-to-head is another, so asking for them
     together would make the whole sheet wait on the slowest of three. Each
     fills in as it lands. */
  const formA = useApi(live ? `form:${a.te_slug}` : null, () => getPlayerForm(a.te_slug))
  const formB = useApi(live ? `form:${b.te_slug}` : null, () => getPlayerForm(b.te_slug))

  /* WHICH RESULT IS OPEN, across both players' rows — held here rather than
     in each row, so opening one closes the other by construction. The site
     floats a popup over the square; on a phone, inside a sheet, that is an
     overlay on an overlay, so the detail arrives as a line of the card
     itself, under the form it belongs to. */
  const [open, setOpen] = useState(null)
  const d = h2h.data
  const view = useMemo(() => orient(d, a?.te_slug), [d, a?.te_slug])
  const rows = useMemo(
    () => compareRows({ view, surface, left: a, right: b }), [view, surface, a, b])

  return (
    <Sheet visible={!!visible} onClose={onClose} title="Head to head">
      {h2h.loading && !d ? <Loading /> : null}
      {h2h.error ? <Text style={s.err}>Couldn’t load the head-to-head.</Text> : null}

      {view ? (
        <ScrollPane contentContainerStyle={s.body}>
          {/* THE TWO NAMES, WITH THE RECORD BETWEEN THEM. Each name wears its
              side's colour as an underline — the key the rest of the sheet is
              read with — and shrinks through the app's own ladder rather than
              truncating: "Botic Van de Zandschulp" becomes "Van de
              Zandschulp" before it becomes smaller, and never becomes "Van de
              Zandsc…". */}
          <View style={s.head}>
            <View style={s.who}>
              <View style={s.whoLine}>
                <FlagSlot codes={[a?.nationality]} />
                <PlayerName name={a?.name} style={s.whoName} />
              </View>
              <View style={[s.rule, { backgroundColor: SIDE.left.line }]} />
            </View>
            <Text style={s.record} numberOfLines={1}>
              <Text style={{ color: SIDE.left.ink }}>{view.wins[0]}</Text>
              <Text style={s.recordDash}>–</Text>
              <Text style={{ color: SIDE.right.ink }}>{view.wins[1]}</Text>
            </Text>
            <View style={[s.who, s.whoEnd]}>
              <View style={[s.whoLine, s.whoLineEnd]}>
                <PlayerName name={b?.name} style={[s.whoName, s.whoNameEnd]} />
                <FlagSlot codes={[b?.nationality]} />
              </View>
              <View style={[s.rule, { backgroundColor: SIDE.right.line }]} />
            </View>
          </View>

          {/* THE SPINE. The label is the axis and the figures flank it, so the
              eye runs down one narrow column of words while the comparison
              happens either side of it — rather than reading two numbers and
              subtracting them, six times. */}
          {rows.length || formA.data?.length || formB.data?.length ? (
            <View style={s.spine}>
              {rows.map((r, i) => (
                <View key={r.key} style={[s.row, i > 0 && s.rowRule]}>
                  <Figure v={r.values[0]} lit={r.better === 0} side="left" hashed={HASHED.has(r.key)} />
                  <FitText style={s.label} min={8} align="center">{r.label}</FitText>
                  <Figure v={r.values[1]} lit={r.better === 1} side="right" hashed={HASHED.has(r.key)} />
                </View>
              ))}
              {formA.data?.length || formB.data?.length ? (
                <View style={[s.row, rows.length > 0 && s.rowRule]}>
                  <Form form={formA.data} side={0} open={open} onOpen={setOpen} />
                  <FitText style={s.label} min={8} align="center">form</FitText>
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
                    <Text style={s.detailLine} numberOfLines={1}>
                      <Text style={{ color: open.detail.won ? PICK.correct.border : PICK.wrong.border }}>
                        {open.detail.won ? 'W' : 'L'}
                      </Text>
                      {`  ${open.detail.line}`}
                    </Text>
                    <Text style={s.detailMeta} numberOfLines={1}>
                      {[open.detail.meta, shortDay(open.match.date)].filter(Boolean).join(' · ')}
                    </Text>
                  </View>
                </Pressable>
              ) : null}
            </View>
          ) : null}

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
                        <Text style={s.meetScore} numberOfLines={1}>{m.score}</Text>
                      </View>
                      <Text style={s.meetMeta} numberOfLines={1}>
                        {[m.tournament, m.year, m.round, m.surface].filter(Boolean).join(' · ')}
                      </Text>
                    </View>
                  </View>
                )
              })}
            </>
          ) : (
            <Text style={s.none}>They have never met.</Text>
          )}
        </ScrollPane>
      ) : null}
    </Sheet>
  )
}

/* One figure in the spine. A plate when this side leads the row; ink alone
   when it does not, and a quiet dash where we hold no number — a blank would
   read as a zero, and a zero is a claim. */
function Figure({ v, lit, side, hashed }) {
  const tone = side === 'left' ? SIDE.left : SIDE.right
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
  const perRow = formCount(width)
  const chips = formChips(form, perRow * 2)
  return (
    <View style={[s.formRow, end && s.formRowEnd]}
          onLayout={e => setWidth(e.nativeEvent.layout.width)}>
      {chips.map((c, i) => {
        const showing = open?.side === side && open?.i === i
        return (
          <Pressable key={i} onPress={() => onOpen(showing ? null
            : { side, i, match: c.match, detail: formDetail(c.match) })}
                     hitSlop={2}
                     style={[s.chip, c.result === 'W' ? s.chipWon : s.chipLost,
                             showing && s.chipOpen]}
                     accessibilityRole="button" accessibilityLabel={c.said}
                     accessibilityState={{ selected: showing }}>
            <Text style={[s.chipText,
                          { color: c.result === 'W' ? PICK.correct.border : PICK.wrong.border }]}>
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
const CHIP = 18

const s = StyleSheet.create({
  body: { paddingBottom: S.md, gap: S.md },

  /* The headline. The record is the widest thing in the row and holds the
     middle; the names take what is left, evenly, and shrink into it. */
  head: { flexDirection: 'row', alignItems: 'flex-end', gap: S.sm },
  who: { flex: 1, minWidth: 0, gap: 3 },
  whoEnd: { alignItems: 'flex-end' },
  whoLine: { flexDirection: 'row', alignItems: 'center', gap: 4, alignSelf: 'stretch' },
  whoLineEnd: { justifyContent: 'flex-end' },
  whoName: { ...T.bodyBold, color: C.ink, flexShrink: 1 },
  whoNameEnd: { textAlign: 'right' },
  // Two points, so the key reads as a deliberate mark rather than a hairline.
  rule: { height: 2, borderRadius: 1, alignSelf: 'stretch' },
  record: { ...T.display, fontSize: 30, color: C.ink, flexShrink: 0 },
  recordDash: { color: C.faint },

  spine: {
    backgroundColor: C.sunken, borderRadius: R.md,
    borderWidth: 1, borderColor: C.border,
  },
  row: { flexDirection: 'row', alignItems: 'center', paddingVertical: 5, paddingHorizontal: S.sm },
  rowRule: { borderTopWidth: 1, borderTopColor: C.border },
  /* THE AXIS: one width for every row, so the figures either side line up
     rather than wandering down the card with the length of each word.
     `leading` is what makes it a width and not a trap — it scales with the
     reader's text size exactly as the glyphs inside it do. Fixed at 88 points
     it fitted "meetings won" on my phone and truncated it on a reader with
     large text turned on, which is the one thing this project does not print
     (owner, 2026-09-23: "fix the …"). FitText is the second guard: whatever
     is left after the column has grown, the word shrinks into it. */
  label: { ...T.tiny, color: C.faint, width: leading(74), textAlign: 'center' },

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
    flex: 1, minWidth: 0, flexDirection: 'row', flexWrap: 'wrap', gap: 3,
    justifyContent: 'flex-end', overflow: 'hidden',
  },
  formRowEnd: { justifyContent: 'flex-start' },
  chip: {
    width: CHIP, height: CHIP, borderRadius: R.xs + 1,
    alignItems: 'center', justifyContent: 'center', borderWidth: 1,
  },
  chipWon: { backgroundColor: PICK.correct.bg, borderColor: PICK.correct.border },
  chipLost: { backgroundColor: PICK.wrong.bg, borderColor: PICK.wrong.border },
  chipText: { fontFamily: 'Archivo_700Bold', fontSize: 10 },
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
