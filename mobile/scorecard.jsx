/*
 * The match card: two competitor rows with the score, drawn ONE way for every
 * surface — the schedule row and the history sheet — so the two cannot drift.
 * It is the site's MatchScoreCard (CompetitorRows) in React Native, with the
 * same rules in the same order:
 *  - one source per render (score.js scoreSets);
 *  - a set won is bold, the set in play never is;
 *  - the tiebreak is a superscript, never "7(7)";
 *  - "ret." / "w/o" sit BEFORE the tick, so the marks stay in a column;
 *  - a serve slot exists on both lines or on neither, and only while the
 *    match is on court or stopped — a finished row does not hold space for
 *    a ball it can never show;
 *  - the point comes last, tinted apart from the games, and a live row with
 *    no fresh point holds its place with a dim dash rather than shifting.
 */
import { StyleSheet, Text, View } from 'react-native'
import { EntryChip, FlagSlot, PlayerName, PosBadge } from './cards'
import { Bump } from './fx'
import { useFlashOnChange } from './scoreFx'
import { leading } from './fontScale.js'
import { endedWith, parseSet, scoreSets, setCount, setWon, winnerSideOf } from './score'
import { isLive, isSuspended, pointOf, servingSide, sideDrawRank, sideEntryType, sideFlags, sideName, sideSeed } from './schedule'
import { C, S, T } from './theme'

/* `scale` — the block at a fraction of its size for the schedule's mid
   density (owner, 2026-09-17): the same two lines and box score, smaller,
   so more matches fit a screen. Names, marks and the score cells scale
   together; the badge and the flag keep their size (already small). */
/* THE SERVE MARK, as the owner drew it (2026-09-17): a clay disc inside a
   dark ring with a lighter outline — the brand dot's anatomy. */
function ServeMark({ size = 14 }) {
  return (
    <View style={{
      width: size, height: size, borderRadius: size / 2,
      backgroundColor: C.clayDeep + '66', borderWidth: 1, borderColor: C.clayLight + '80',
      alignItems: 'center', justifyContent: 'center',
    }}>
      <View style={{ width: size * 0.55, height: size * 0.55, borderRadius: size * 0.275, backgroundColor: C.clay }} />
    </View>
  )
}

/* `serveMark`: where the server's mark sits — 'left', the row's leading
   slot (the time view), or 'score', just left of the server's score (the
   court view; owner, 2026-09-17). The slot is held on both rows either way,
   so the names and the sets stay in line. */
export function MatchCard({ e, scale = 1, badges = true, serveMark = 'left' }) {
  const live = isLive(e)
  const stopped = isSuspended(e) || e.status === 'postponed' || e.status === 'to_be_completed'
  const lp = e.live_point ?? null
  const sets = scoreSets(e)
  const n = setCount(sets)
  const point = live ? pointOf(e) : null
  // The site's bump on the number that moves — both sides together, since a
  // point won is one event, not two cells changing.
  const flash = useFlashOnChange(point ? `${point[0] ?? '0'}-${point[1] ?? '0'}` : '')
  const serving = (live || stopped) ? servingSide(e) : null
  const winner = winnerSideOf(e)
  const doubles = e.discipline !== 'singles'
  /* Both rows get the SAME number of flag slots — a doubles pair needs two —
     so the two names still start at the same x. */
  const flagSlots = Math.max(1, sideFlags(e.players, 'a').length, sideFlags(e.players, 'b').length)
  /* The column is sized for the widest thing it can hold, per match: a "10"
     from a match tiebreak, else one digit — the site's --sched-set-w. */
  const twoDigit = (sets || []).some(row => (row || []).some(c => parseSet(c).g.length > 1))
  /* FOUR OR FIVE SETS: the cells give way, not the name. At full size a
     five-setter's six columns left the name "Zver…" even after the ladder
     had shortened and shrunk it (US Open R64, 2026-09-04). The site does
     the same with .cv-live-score--s4/--s5. Everything in the block scales
     together so the columns stay columns. */
  /* THE POINT IS A COLUMN TOO. A live three-setter is four columns wide —
     three sets and the running point — and counting only the sets left it at
     full size, which ran off the right edge of the score-history sheet
     (owner, 2026-09-12). Counting the point keeps every existing case
     identical (a finished five-setter is still 0.76, a four still 0.88) and
     densifies the live ones that were overflowing. */
  const cols = n + (point ? 1 : 0)
  const k = (cols >= 5 ? 0.76 : cols === 4 ? 0.88 : 1) * scale
  const dense = k < 1 ? {
    sets: { gap: Math.round(6 * k) },
    box: { minWidth: Math.round((twoDigit ? 26 : 16) * k) },
    set: { fontSize: Math.round(20 * k), lineHeight: leading(Math.round(22 * k)) },
    sup: { fontSize: Math.round(10 * k), lineHeight: leading(Math.round(12 * k)) },
    point: { fontSize: Math.round(20 * k), lineHeight: leading(Math.round(22 * k)), minWidth: Math.round(26 * k) },
  } : null

  return (
    <View style={s.rows}>
      {['a', 'b'].map((side, idx) => {
        const lost = winner != null && winner !== idx
        const end = endedWith(e.scores, idx)
        const ink = lost ? C.muted : C.ink
        // Your pick to win, marked after the name: the server stamps the row
        // with the draw entry you chose (singles only — nobody picks doubles).
        const picked = !doubles && e.pick_entry_id != null
          && (e.players || []).some(p => p.side === side && p.draw_entry_id === e.pick_entry_id)
        return (
          <View key={side} style={s.line}>
            {(live || stopped) && serveMark === 'left' && (
              <View style={s.slot}>
                {serving === side && <View style={s.ball} />}
              </View>
            )}
            {/* `badges` off: no seed column at all — a past day's doubles, grouped
                on their own, have no seeds to align and the column was a hole
                on the left (owner, 2026-09-17). */}
            {badges && <PosBadge seed={sideSeed(e.players, side)} drawRank={sideDrawRank(e.players, side)} />}
            <FlagSlot codes={sideFlags(e.players, side)} slots={flagSlots} />
            <View style={s.nameWrap}>
            <PlayerName
              name={sideName(e.players, side)}
              doubles={doubles}
              /* 1.27x rather than bodyMed's 1.4: tight enough to pull the two
                 rows together, and still clear of the ~1.2 floor where
                 descenders start to clip. */
              style={[T.bodyMed, { color: ink, flexShrink: 1, lineHeight: leading(19) }, scale < 1 && { fontSize: Math.round(T.bodyMed.fontSize * scale), lineHeight: leading(Math.round(19 * scale)) }]}
              after={picked ? <Text style={s.pick} accessibilityLabel="You predicted this player to win">🤞</Text> : null}
            />
            </View>
            {/* AFTER the name slot, not inside it. nameWrap is flex:1, so the
                chip's width comes out of the name's budget before PlayerName
                measures — and PlayerName's own ladder then shortens or shrinks
                to whatever is left. That is the whole of "decrease the font
                size when necessary": it is already the rule, it just has to be
                given the real width (owner, 2026-09-14). */}
            <EntryChip entryType={sideEntryType(e.players, side)} />
            {end && <Text style={s.end}>{end}</Text>}
            {winner != null && (
              <Text style={[s.mark, scale < 1 && { fontSize: Math.round(13 * scale), lineHeight: leading(Math.round(16 * scale)) }, { color: winner === idx ? C.greenLit : C.lossMark }]}>
                {winner === idx ? '✓' : '✗'}
              </Text>
            )}
            {(live || stopped) && serveMark === 'score' && (
              <View style={s.serveSlot}>
                {serving === side && <ServeMark size={Math.round(14 * scale)} />}
              </View>
            )}
            <View style={[s.sets, dense?.sets]}>
              {Array.from({ length: n }, (_, i) => {
                const { g, tb } = parseSet(sets?.[idx]?.[i])
                const won = setWon(sets, i, idx, live, lp)
                if (g === '' && tb == null) {
                  return <Text key={i} style={[s.set, twoDigit && s.setWide, dense?.set, dense?.box, { color: C.faint }]}>·</Text>
                }
                return (
                  <View key={i} style={[s.setBox, twoDigit && s.setWide, dense?.box]}>
                    <Text style={[s.set, dense?.set, { color: won ? C.ink : C.muted }, won && s.setWon]}>{g}</Text>
                    {tb != null && <Text style={[s.sup, dense?.sup, { color: won ? C.ink : C.muted }]}>{tb}</Text>}
                  </View>
                )
              })}
              {point ? (
                <Bump on={flash && !!point}>
                  <Text style={[s.point, dense?.point, lp?.tiebreak && s.pointTb]}>{point[idx] ?? '0'}</Text>
                </Bump>
              ) : live && !stopped ? (
                <Text style={[s.point, dense?.point, { color: C.faint }]}>–</Text>
              ) : null}
            </View>
          </View>
        )
      })}
    </View>
  )
}

const s = StyleSheet.create({
  // The two players are one unit, so they sit close. Most of the air between
  // them was never this gap — it is bodyMed's 21pt line box around 15pt text —
  // so the name below tightens its own leading too, and both stay in leading()
  // so they still grow with Dynamic Type.
  rows: { gap: 2 },
  line: { flexDirection: 'row', alignItems: 'center', gap: S.sm },
  slot: { width: 8, alignItems: 'center' },
  serveSlot: { width: 16, alignItems: 'center', marginLeft: 'auto' },
  ball: { width: 7, height: 7, borderRadius: 4, backgroundColor: C.clay },
  end: { ...T.tiny, color: C.faint, fontStyle: 'italic' },
  pick: { fontSize: 14, lineHeight: leading(18) },
  // leading() on the WIDTH too: a 13pt glyph in a 14pt box has one point of
  // room, so any text size above ~1.08 clipped the tick. The box now grows
  // with the mark it holds.
  mark: { fontSize: 13, lineHeight: leading(16), width: leading(14), textAlign: 'center' },
  /* THE SCORE NEVER GIVES WAY AND THE NAME ALWAYS DOES. Yoga defaults
     flexShrink to 0, so nothing here shrank and the row simply overflowed
     instead; the name is the one part with a ladder to climb down. */
  sets: { flexDirection: 'row', alignItems: 'center', gap: 6, marginLeft: 'auto', flexShrink: 0 },
  nameWrap: { flex: 1, minWidth: 0 },
  setBox: { flexDirection: 'row', alignItems: 'flex-start', minWidth: 16, justifyContent: 'center' },
  setWide: { minWidth: 26 },
  set: { ...T.score },
  setWon: { fontFamily: 'SairaCondensed_700Bold' },
  sup: { fontFamily: 'SairaCondensed_700Bold', fontSize: 10, lineHeight: leading(12), marginTop: 2 },
  point: { ...T.score, color: C.clay, minWidth: 26, textAlign: 'right', flexShrink: 0 },
  pointTb: { color: C.warn },
})
