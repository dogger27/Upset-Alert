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
import { FlagSlot, PlayerName, PosBadge } from './cards'
import { leading } from './fontScale.js'
import { endedWith, parseSet, scoreSets, setCount, setWon, winnerSideOf } from './score'
import { isLive, isSuspended, pointOf, servingSide, sideDrawRank, sideFlags, sideName, sideSeed } from './schedule'
import { C, S, T } from './theme'

export function MatchCard({ e }) {
  const live = isLive(e)
  const stopped = isSuspended(e) || e.status === 'postponed' || e.status === 'to_be_completed'
  const lp = e.live_point ?? null
  const sets = scoreSets(e)
  const n = setCount(sets)
  const point = live ? pointOf(e) : null
  const serving = (live || stopped) ? servingSide(e) : null
  const winner = winnerSideOf(e)
  const doubles = e.discipline !== 'singles'
  /* Both rows get the SAME number of flag slots — a doubles pair needs two —
     so the two names still start at the same x. */
  const flagSlots = Math.max(1, sideFlags(e.players, 'a').length, sideFlags(e.players, 'b').length)
  /* The column is sized for the widest thing it can hold, per match: a "10"
     from a match tiebreak, else one digit — the site's --sched-set-w. */
  const twoDigit = (sets || []).some(row => (row || []).some(c => parseSet(c).g.length > 1))

  return (
    <View style={s.rows}>
      {['a', 'b'].map((side, idx) => {
        const lost = winner != null && winner !== idx
        const end = endedWith(e.scores, idx)
        const ink = lost ? C.muted : C.ink
        return (
          <View key={side} style={s.line}>
            {(live || stopped) && (
              <View style={s.slot}>
                {serving === side && <View style={s.ball} />}
              </View>
            )}
            <PosBadge seed={sideSeed(e.players, side)} drawRank={sideDrawRank(e.players, side)} />
            <FlagSlot codes={sideFlags(e.players, side)} slots={flagSlots} />
            <PlayerName
              name={sideName(e.players, side)}
              doubles={doubles}
              style={[T.bodyMed, { color: ink, flexShrink: 1 }]}
            />
            {end && <Text style={s.end}>{end}</Text>}
            {winner != null && (
              <Text style={[s.mark, { color: winner === idx ? C.greenLit : C.lossMark }]}>
                {winner === idx ? '✓' : '✗'}
              </Text>
            )}
            <View style={s.sets}>
              {Array.from({ length: n }, (_, i) => {
                const { g, tb } = parseSet(sets?.[idx]?.[i])
                const won = setWon(sets, i, idx, live, lp)
                if (g === '' && tb == null) {
                  return <Text key={i} style={[s.set, twoDigit && s.setWide, { color: C.faint }]}>·</Text>
                }
                return (
                  <View key={i} style={[s.setBox, twoDigit && s.setWide]}>
                    <Text style={[s.set, { color: won ? C.ink : C.muted }, won && s.setWon]}>{g}</Text>
                    {tb != null && <Text style={[s.sup, { color: won ? C.ink : C.muted }]}>{tb}</Text>}
                  </View>
                )
              })}
              {point ? (
                <Text style={[s.point, lp?.tiebreak && s.pointTb]}>{point[idx] ?? '0'}</Text>
              ) : live && !stopped ? (
                <Text style={[s.point, { color: C.faint }]}>–</Text>
              ) : null}
            </View>
          </View>
        )
      })}
    </View>
  )
}

const s = StyleSheet.create({
  rows: { gap: 4 },
  line: { flexDirection: 'row', alignItems: 'center', gap: S.sm },
  slot: { width: 8, alignItems: 'center' },
  ball: { width: 7, height: 7, borderRadius: 4, backgroundColor: C.clay },
  end: { ...T.tiny, color: C.faint, fontStyle: 'italic' },
  mark: { fontSize: 13, lineHeight: leading(16), width: 14, textAlign: 'center' },
  sets: { flexDirection: 'row', alignItems: 'center', gap: 6, marginLeft: 'auto' },
  setBox: { flexDirection: 'row', alignItems: 'flex-start', minWidth: 16, justifyContent: 'center' },
  setWide: { minWidth: 26 },
  set: { ...T.score },
  setWon: { fontFamily: 'SairaCondensed_700Bold' },
  sup: { fontFamily: 'SairaCondensed_700Bold', fontSize: 10, lineHeight: leading(12), marginTop: 2 },
  point: { ...T.score, color: C.clay, minWidth: 26, textAlign: 'right' },
  pointTb: { color: C.warn },
})
