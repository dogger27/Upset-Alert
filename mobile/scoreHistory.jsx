/*
 * A match's score with a slider through its history — the site's
 * ScoreHistoryPopup as a sheet.
 *
 * Opened from any schedule row that has started (live, finished, postponed,
 * carried over). Each slider position is one CHANGE of the score, rendered
 * through MatchCard, the same component the schedule row draws with, so the
 * two cannot drift apart. Fully right is not a history position: it is "now"
 * — the row as the schedule currently holds it, so a live match keeps ticking
 * while the sheet is open.
 *
 * Ticks on the track are the moments that mattered — a break of serve, the
 * end of a set, the match's end — derived by scoreTimeline.js (the site's
 * module, copied). Each hangs toward the player who earned it.
 */
import { useMemo, useRef, useState } from 'react'
import { PanResponder, ScrollView, StyleSheet, Text, View } from 'react-native'
import { getEntryScoreHistory, getMatchScoreHistory, getMatchStatistics } from './api'
import { leading } from './fontScale.js'
import { MatchCard } from './scorecard'
import { pointStats, sanitizeSnapshots, timelineMarkers } from './scoreTimeline'
import { Sheet } from './sheet'
import { C, S, T } from './theme'
import { Loading } from './ui'
import { useApi } from './useApi'

const THUMB = 26
const TICK = { break: C.warn, set: C.info, match: C.lossMark }

/* The draw page's caller. A bracket match is not a schedule row, but the
   sheet reads one shape — so the match is dressed as a row: its two entrants
   as sides, the winner as a side index, its live and final scores as they
   are. draw_entry_id is the entrant's own id, which is what the history
   endpoint's player1_id names, so orientation lines up by construction. */
export function entryFromMatch(m, drawId, drawRanks) {
  if (!m) return null
  const side = (p, sd) => p ? [{
    side: sd, position: 1, name: p.name, entry_name: p.name, seed: p.seed ?? null,
    nationality: p.nationality ?? null, draw_entry_id: p.id,
    draw_rank: drawRanks?.get?.(p.id) ?? null, te_slug: p.te_slug ?? null,
  }] : []
  const live = !m.winner && !!(m.live_scores || m.live_point)
  return {
    id: `m${m.id}`, draw_id: drawId, match_id: m.id, discipline: 'singles',
    status: m.winner || m.status === 'completed' ? 'completed' : live ? 'live' : 'scheduled',
    players: [...side(m.player1, 'a'), ...side(m.player2, 'b')],
    winner_side: m.winner ? (m.player1 && m.winner.id === m.player1.id ? 0 : 1) : null,
    scores: m.scores ?? null, live_scores: m.live_scores ?? null, live_point: m.live_point ?? null,
  }
}

/* The site's rule for "this match has a score to show": anything with a
   result, a live feed or a scoreline, and never a bye. */
export function matchStarted(m) {
  return !!m && !m.is_bye && !!(m.winner || m.live_scores || m.live_point || m.scores || m.status === 'completed')
}

export function ScoreHistorySheet({ visible, onClose, entry }) {
  // A row with no bracket match — qualifying singles, doubles — keeps its
  // history under its own schedule-entry id; the response shape is identical.
  const entryOnly = !!entry && !entry.match_id
  const live = entry?.status === 'live'
  // The app's fetch cache is keyed by string; a live match's history grows, so
  // its key rolls every 15 s and a re-render picks up the new points. A
  // finished match's history is fixed and its key is too.
  const bucket = live ? Math.floor(Date.now() / 15000) : 'f'
  const key = visible && entry
    ? (entryOnly ? `hist:e:${entry.id}:${bucket}` : `hist:${entry.draw_id}:${entry.match_id}:${bucket}`)
    : null
  const hist = useApi(key, () => entryOnly
    ? getEntryScoreHistory(entry.id)
    : getMatchScoreHistory(entry.draw_id, entry.match_id))
  const data = hist.data

  // null = fully right = follow live / show final. An index otherwise.
  const [pos, setPos] = useState(null)
  // True while a finger is on the slider — see the ScrollView below.
  const [holding, setHolding] = useState(false)
  const [tab, setTab] = useState('points')

  /* Snapshots arrive in the MATCH's orientation (side 1 = the bracket's
     player1); the sheet shows the SHEET's order, which need not agree. Line
     them up by draw_entry_id where the row is stamped, by surname where it is
     not, and only then assume. Getting this wrong flips every score and tick
     to the wrong player, which is worse than no history. */
  const a = (entry?.players || []).filter(p => p.side === 'a')
  const b = (entry?.players || []).filter(p => p.side === 'b')
  const topIsP1 = (() => {
    const top = a[0]
    if (!top || !data) return true
    if (top.draw_entry_id != null && data.player1_id != null) return top.draw_entry_id === data.player1_id
    if (data.player1_name) {
      const last = (top.name || '').split(' ').pop().toLowerCase()
      if (last) return data.player1_name.toLowerCase().includes(last)
    }
    return true
  })()

  const snapshots = useMemo(() => sanitizeSnapshots(data?.snapshots ?? []), [data?.snapshots])
  const max = snapshots.length
  const atEnd = pos == null || pos >= max
  const completed = entry?.status === 'completed' || entry?.winner_side != null
  const winnerSide = (() => {
    if (!completed || entry?.winner_side == null) return null
    return (entry.winner_side === 0) === topIsP1 ? 1 : 2
  })()
  const markers = useMemo(() => timelineMarkers(snapshots, { completed, winnerSide }),
    [snapshots, completed, winnerSide])
  const stats = useMemo(() => pointStats(snapshots), [snapshots])
  const statsUsable = stats.counted >= 20 && stats.counted / Math.max(1, stats.transitions) >= 0.7

  /* THE SECOND TAB — Sofascore's own serve and return figures, which our
     snapshots cannot produce: no score says whether a point was played on a
     first or a second serve. Only for bracket matches; an entry-only row
     (doubles, qualifying) has no match to ask about.

     These have NO per-point history, so unlike the Points tab they do not
     follow the slider — hence two tabs rather than one panel, or a number
     ignoring the thumb would sit beside numbers obeying it. Fetched only when
     the tab is actually open. */
  const canAskStats = !entryOnly && entry?.draw_id != null && entry?.match_id != null
  const sofa = useApi(
    canAskStats ? `match-stats:${entry.draw_id}:${entry.match_id}` : null,
    () => getMatchStatistics(entry.draw_id, entry.match_id),
    { enabled: canAskStats && tab === 'serve' },
  )
  const sofaRows = sofa.data?.periods?.ALL || []

  if (!entry) return null

  /* The row MatchCard reads: a history position is the match as a live row at
     that moment, in the sheet's orientation; the end position is the row
     itself, exactly as the schedule holds it now. */
  const snap = atEnd ? null : snapshots[pos]
  const flip = (sn) => topIsP1 || !sn ? sn : {
    ...sn,
    games: sn.games ? [sn.games[1], sn.games[0]] : sn.games,
    point: sn.point ? [sn.point[1], sn.point[0]] : sn.point,
    serving: sn.serving === 1 ? 2 : sn.serving === 2 ? 1 : sn.serving,
  }
  const row = atEnd ? entry
    : { ...entry, status: 'live', live_point: flip(snap), live_scores: null, scores: null, winner_side: null }

  const when = atEnd
    ? (completed ? 'Final' : live ? 'Live' : 'Now')
    : (snap?.at
        ? new Date(snap.at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
        : `${pos + 1} / ${max}`)

  /* The sheet takes a FIXED height, so the timeline stays where the reader
     left it. The tabs swap panels with different row counts and a bottom sheet
     grows upward, so a content-sized sheet slid the whole timeline up the
     screen on every tab switch. Fixed, the top edge never moves and the
     scroller absorbs the difference.
     (Comment out here, not between `return (` and the element — a comment in
     that position has broken the Metro bundle before.) */
  return (
    <Sheet visible={visible} onClose={onClose} height="80%">
      <Text style={[s.when, atEnd && live && { color: C.greenLit }]}>{when}</Text>
      {/* The scroll is OFF while the slider is held. Refusing to hand the
          responder over is enough on iOS; Android's ScrollView can still take
          a vertical drag, and the symptom is the whole sheet moving under the
          finger. Turning it off for the duration of the drag is the one thing
          that cannot be argued with. */}
      <ScrollView scrollEnabled={!holding} style={{ flex: 1 }}
                  contentContainerStyle={{ gap: S.md, paddingBottom: S.sm }}>
        <MatchCard e={row} />
        {hist.loading && !data ? <Loading /> : null}
        {hist.error ? <Text style={s.err}>Couldn’t load the match history.</Text> : null}
        {max > 0 && (
          <>
            <Scrub max={max} pos={atEnd ? max : pos} onChange={v => setPos(v >= max ? null : v)}
                   onHold={setHolding} markers={markers} topIsP1={topIsP1}
                   top={initialsOf(a[0]?.name)} bottom={initialsOf(b[0]?.name)} />
            {markers.length > 0 && (
              <View style={s.legend}>
                <Legend color={TICK.break} label="break" />
                <Legend color={TICK.set} label="set" />
                {markers.some(m => m.kind === 'match') && <Legend color={TICK.match} label="match" />}
              </View>
            )}
            {/* Tabs only when there IS a second panel — a match with no
                Sofascore event id keeps the single panel it always had. */}
            {statsUsable && canAskStats && (
              <View style={s.tabs}>
                {[['points', 'Points'], ['serve', 'Serve & Return']].map(([k, label]) => (
                  <Text key={k} onPress={() => setTab(k)} accessibilityRole="button"
                        style={[s.tab, tab === k && s.tabOn]}>{label}</Text>
                ))}
              </View>
            )}
            {tab === 'points' && statsUsable && (
              <Stats stats={stats} pos={Math.min(atEnd ? stats.at.length - 1 : pos, stats.at.length - 1)}
                     topIsP1={topIsP1} left={cleanName(a[0])} right={cleanName(b[0])} />
            )}
            {tab === 'serve' && canAskStats && (
              <SofaStats rows={sofaRows} topIsP1={topIsP1} loading={sofa.loading}
                         left={cleanName(a[0])} right={cleanName(b[0])} />
            )}
          </>
        )}
        {data && max === 0 && !hist.loading ? (
          <Text style={s.err}>No point-by-point history was recorded for this match.</Text>
        ) : null}
      </ScrollView>
    </Sheet>
  )
}

/* The slider. A track the thumb travels [THUMB/2, width - THUMB/2] along, so
   a tick at i/max sits exactly under the thumb when the thumb is at i. Drag
   anywhere on the track: the touch decides the position, the same as the
   site's range input. */
function Scrub({ max, pos, onChange, markers, topIsP1, top, bottom, onHold }) {
  const [w, setW] = useState(0)
  const wRef = useRef(0); wRef.current = w
  const startX = useRef(0)
  /* Read through refs inside the responder. PanResponder.create runs ONCE, so
     the handlers close over the first render's props for ever — `max` was
     captured at 0 on the first frame and every drag then computed against it. */
  const maxRef = useRef(max); maxRef.current = max
  const onChangeRef = useRef(onChange); onChangeRef.current = onChange
  const onHoldRef = useRef(onHold); onHoldRef.current = onHold
  const at = (x) => {
    const travel = Math.max(1, wRef.current - THUMB)
    const v = Math.round(((x - THUMB / 2) / travel) * maxRef.current)
    onChangeRef.current(Math.max(0, Math.min(maxRef.current, v)))
  }
  const pan = useRef(PanResponder.create({
    /* CAPTURE, not the plain variants. Two things follow from it, and both
       were bugs: the track claims the touch before its own children, so
       `locationX` is measured against the TRACK rather than against whichever
       tick or thumb happened to be under the finger — a touch on the thumb
       reported a few px and threw the scrub back to the start. And it takes
       the gesture before the enclosing ScrollView can. */
    onStartShouldSetPanResponderCapture: () => true,
    onMoveShouldSetPanResponderCapture: () => true,
    /* NO, the ScrollView may not have it. The default here is YES, which is
       why a few pixels of vertical drift handed the gesture over: the sheet
       scrolled under the finger and the slider was left where it stood. */
    onPanResponderTerminationRequest: () => false,
    onShouldBlockNativeResponder: () => true,
    onPanResponderGrant: (evt) => {
      startX.current = evt.nativeEvent.locationX
      onHoldRef.current?.(true)
      at(startX.current)
    },
    onPanResponderMove: (_, g) => at(startX.current + g.dx),
    onPanResponderRelease: () => onHoldRef.current?.(false),
    onPanResponderTerminate: () => onHoldRef.current?.(false),
  })).current
  const x = THUMB / 2 + (w - THUMB) * (max ? pos / max : 0)
  return (
    <View style={s.scrubRow}>
      <View style={s.names}>
        <Text style={s.nameTop}>{top}</Text>
        <Text style={s.nameBot}>{bottom}</Text>
      </View>
      <View style={[s.track, { touchAction: 'none' }]} onLayout={ev => setW(ev.nativeEvent.layout.width)}
            {...pan.panHandlers} accessibilityRole="adjustable"
            accessibilityLabel="Scrub through the match's score history">
        {/* pointerEvents none on every visual part: belt and braces beside the
            capture above, so a tick or the thumb can never be the touch's
            target and mis-measure locationX. */}
        <View style={s.rail} pointerEvents="none" />
        <View style={[s.fill, { width: x }]} pointerEvents="none" />
        {w > 0 && markers.map(m => {
          const up = (m.side === 1) === topIsP1
          const left = THUMB / 2 + (w - THUMB) * (m.i / max) - (m.adj ? 3 : 0) - 1.5
          return (
            <View key={`${m.kind}${m.i}${m.adj ? 'a' : ''}`}
                  pointerEvents="none"
                  style={[s.tick, up ? s.tickUp : s.tickDown, { left, backgroundColor: TICK[m.kind] }]} />
          )
        })}
        <View style={[s.thumb, { left: x - THUMB / 2 }]} pointerEvents="none" />
      </View>
    </View>
  )
}

function Legend({ color, label }) {
  return (
    <View style={s.legendItem}>
      <View style={[s.legendBox, { backgroundColor: color }]} />
      <Text style={s.legendText}>{label}</Text>
    </View>
  )
}

/* Point statistics at the scrubbed moment — cumulative per position, so the
   numbers wind back with the thumb. Bars grow outward from the label. */
function Stats({ stats, pos, topIsP1, left, right }) {
  const snap = stats.at[pos]
  const top = snap[topIsP1 ? 0 : 1], bot = snap[topIsP1 ? 1 : 0]
  const pct = (w, t) => (t ? Math.round((100 * w) / t) : 0)
  const rows = [
    ['Service points won', top.svcWon, top.svcTot, bot.svcWon, bot.svcTot],
    ['Return points won', top.retWon, top.retTot, bot.retWon, bot.retTot],
    ['Total points won', top.totWon, top.totTot, bot.totWon, bot.totTot],
    ['Break points converted', top.bpConv, top.bpChances, bot.bpConv, bot.bpChances],
    // saved = the opponent's chances that did not convert
    ['Break points saved', bot.bpChances - bot.bpConv, bot.bpChances, top.bpChances - top.bpConv, top.bpChances],
  ]
  return (
    <View style={s.stats}>
      <View style={s.statNames}>
        <Text style={[s.statName, { color: C.h2hP1 }]} numberOfLines={1}>{left}</Text>
        <Text style={[s.statName, { color: C.h2hP2, textAlign: 'right' }]} numberOfLines={1}>{right}</Text>
      </View>
      {/* ONE LINE PER STATISTIC, the site's grid: number, bar, label, bar,
          number. The bars grow from the label outward, in each player's own
          colour, so name, bar and column read as one. */}
      {rows.map(([label, lw, lt, rw, rt]) => (
        <View key={label} style={s.statRow}>
          <Text style={s.statNum} numberOfLines={1}>
            {lt ? `${pct(lw, lt)}%` : '—'}<Text style={s.statSmall}>{lt ? ` (${lw}/${lt})` : ''}</Text>
          </Text>
          <View style={s.barL}><View style={[s.barFill, { backgroundColor: C.h2hP1, width: `${lt ? pct(lw, lt) : 0}%` }]} /></View>
          <Text style={s.statLabel} numberOfLines={1}>{label}</Text>
          <View style={s.barR}><View style={[s.barFill, { backgroundColor: C.h2hP2, width: `${rt ? pct(rw, rt) : 0}%` }]} /></View>
          <Text style={[s.statNum, { textAlign: 'right' }]} numberOfLines={1}>
            {rt ? `${pct(rw, rt)}%` : '—'}<Text style={s.statSmall}>{rt ? ` (${rw}/${rt})` : ''}</Text>
          </Text>
        </View>
      ))}
    </View>
  )
}

/* Sofascore's serve/return tally. Same five-column grid as Stats so the two
   tabs read as one table with two pages — but WHOLE MATCH, said plainly at the
   top because the panel next door moves with the slider and this one cannot. */
function SofaStats({ rows, topIsP1, loading, left, right }) {
  if (loading && rows.length === 0) return <Loading />
  if (rows.length === 0) return <Text style={s.err}>No serve statistics for this match.</Text>
  let section = null
  return (
    <View style={s.stats}>
      {/* The same column heads the Points panel carries, each in that side's
          own bar colour, so name, bar and column read as one. */}
      <View style={s.statNames}>
        <Text style={[s.statName, { color: C.h2hP1 }]} numberOfLines={1}>{left}</Text>
        <Text style={[s.statName, { color: C.h2hP2, textAlign: 'right' }]} numberOfLines={1}>{right}</Text>
      </View>
      {rows.map(r => {
        const l = topIsP1 ? r.home : r.away
        const rt = topIsP1 ? r.away : r.home
        // A bare count has no denominator, so no percentage: "Return games
        // played 13 v 13" as a percentage bar would imply a contest it isn't.
        const ratio = l[1] != null && rt[1] != null
        const pct = (v) => (v[1] ? Math.round((100 * v[0]) / v[1]) : 0)
        const peak = Math.max(l[0], rt[0], 1)
        const width = (v) => (ratio ? pct(v) : Math.round((100 * v[0]) / peak))
        const head = r.section !== section ? (section = r.section) : null
        return (
          <View key={r.label}>
            {head ? <Text style={s.statSection}>{head}</Text> : null}
            <View style={s.statRow}>
              <Text style={s.statNum} numberOfLines={1}>
                {ratio ? `${pct(l)}%` : l[0]}
                <Text style={s.statSmall}>{ratio ? ` (${l[0]}/${l[1]})` : ''}</Text>
              </Text>
              <View style={s.barL}><View style={[s.barFill, { backgroundColor: C.h2hP1, width: `${width(l)}%` }]} /></View>
              <Text style={s.statLabel} numberOfLines={1}>{r.label}</Text>
              <View style={s.barR}><View style={[s.barFill, { backgroundColor: C.h2hP2, width: `${width(rt)}%` }]} /></View>
              <Text style={[s.statNum, { textAlign: 'right' }]} numberOfLines={1}>
                {ratio ? `${pct(rt)}%` : rt[0]}
                <Text style={s.statSmall}>{ratio ? ` (${rt[0]}/${rt[1]})` : ''}</Text>
              </Text>
            </View>
          </View>
        )
      })}
    </View>
  )
}

/* "MK" for the gutter beside the track: the top player's initials above the
   track's level, the bottom player's below — the same order as the card. */
function initialsOf(name) {
  const words = cleanName({ name }).split(/\s+/).filter(Boolean)
  const ini = `${(words[0] || '').charAt(0)}${(words.length > 1 ? words[words.length - 1] : '').charAt(0)}`.toUpperCase()
  return ini || (name || '').slice(0, 2).toUpperCase()
}

/* The card's names, cleaned of sheet furniture ([WC], IOC codes). */
function cleanName(p) {
  return (p?.entry_name || p?.name || '').replace(/\s*\[[^\]]*\]\s*/g, ' ').trim()
}

const s = StyleSheet.create({
  when: { ...T.h2, color: C.ink, textAlign: 'center' },
  err: { ...T.small, color: C.muted, textAlign: 'center' },
  scrubRow: { flexDirection: 'row', alignItems: 'center', gap: S.sm, marginTop: S.xs },
  names: { width: 28, height: 44, justifyContent: 'space-between' },
  nameTop: { ...T.tiny, color: C.h2hP1, fontFamily: 'Archivo_700Bold' },
  nameBot: { ...T.tiny, color: C.h2hP2, fontFamily: 'Archivo_700Bold' },
  track: { flex: 1, height: 44, justifyContent: 'center' },
  rail: { height: 4, borderRadius: 2, backgroundColor: C.border },
  fill: { position: 'absolute', left: 0, height: 4, borderRadius: 2, backgroundColor: C.greenLit },
  tick: { position: 'absolute', width: 3, height: 9, borderRadius: 1 },
  tickUp: { top: 8 },
  tickDown: { bottom: 8 },
  thumb: {
    position: 'absolute', width: THUMB, height: THUMB, borderRadius: THUMB / 2,
    backgroundColor: C.ink, borderWidth: 2, borderColor: C.card,
  },
  legend: { flexDirection: 'row', justifyContent: 'center', gap: S.md },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  legendBox: { width: 8, height: 8, borderRadius: 2 },
  legendText: { ...T.tiny, color: C.faint },
  /* Tabs: two views of the same table. The active one is marked by weight
     and an underline, not a filled pill — a pill here would compete with the
     score card above it for the eye. */
  tabs: { flexDirection: 'row', gap: 2, marginTop: S.sm,
          borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: C.border },
  tab: { ...T.tiny, color: C.faint, fontFamily: 'Archivo_700Bold',
         paddingVertical: 5, paddingHorizontal: 10, marginBottom: -StyleSheet.hairlineWidth,
         borderBottomWidth: 2, borderBottomColor: 'transparent' },
  tabOn: { color: C.ink, borderBottomColor: C.greenLit },
  statSection: { ...T.tiny, color: C.faint, fontFamily: 'Archivo_700Bold',
                 letterSpacing: 0.6, textTransform: 'uppercase', marginTop: 6, marginBottom: 1 },
  stats: { gap: 8, marginTop: S.xs },
  statNames: { flexDirection: 'row', justifyContent: 'space-between', gap: S.sm },
  statName: { ...T.smallMed, flex: 1 },
  statRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  statNum: { ...T.tiny, color: C.ink, fontFamily: 'Archivo_700Bold', width: 78 },
  statSmall: { ...T.tiny, color: C.faint, fontFamily: 'Archivo_400Regular' },
  statLabel: { ...T.tiny, color: C.faint, textAlign: 'center', flexShrink: 1 },
  barL: { flex: 1, height: 5, borderRadius: 3, backgroundColor: C.border, overflow: 'hidden', alignItems: 'flex-end' },
  barR: { flex: 1, height: 5, borderRadius: 3, backgroundColor: C.border, overflow: 'hidden' },
  barFill: { height: 5, borderRadius: 3 },
})
