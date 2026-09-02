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
import { getEntryScoreHistory, getMatchScoreHistory } from './api'
import { leading } from './fontScale.js'
import { MatchCard } from './scorecard'
import { pointStats, sanitizeSnapshots, timelineMarkers } from './scoreTimeline'
import { Sheet } from './sheet'
import { C, S, T } from './theme'
import { Loading } from './ui'
import { useApi } from './useApi'

const THUMB = 26
const TICK = { break: C.warn, set: C.info, match: C.lossMark }

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

  return (
    <Sheet visible={visible} onClose={onClose}>
      <Text style={[s.when, atEnd && live && { color: C.greenLit }]}>{when}</Text>
      <ScrollView contentContainerStyle={{ gap: S.md, paddingBottom: S.sm }}>
        <MatchCard e={row} />
        {hist.loading && !data ? <Loading /> : null}
        {hist.error ? <Text style={s.err}>Couldn’t load the match history.</Text> : null}
        {max > 0 && (
          <>
            <Scrub max={max} pos={atEnd ? max : pos} onChange={v => setPos(v >= max ? null : v)}
                   markers={markers} topIsP1={topIsP1}
                   top={initialsOf(a[0]?.name)} bottom={initialsOf(b[0]?.name)} />
            {markers.length > 0 && (
              <View style={s.legend}>
                <Legend color={TICK.break} label="break" />
                <Legend color={TICK.set} label="set" />
                {markers.some(m => m.kind === 'match') && <Legend color={TICK.match} label="match" />}
              </View>
            )}
            {statsUsable && (
              <Stats stats={stats} pos={Math.min(atEnd ? stats.at.length - 1 : pos, stats.at.length - 1)}
                     topIsP1={topIsP1} left={cleanName(a[0])} right={cleanName(b[0])} />
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
function Scrub({ max, pos, onChange, markers, topIsP1, top, bottom }) {
  const [w, setW] = useState(0)
  const wRef = useRef(0); wRef.current = w
  const startX = useRef(0)
  const at = (x) => {
    const travel = Math.max(1, wRef.current - THUMB)
    const v = Math.round(((x - THUMB / 2) / travel) * max)
    onChange(Math.max(0, Math.min(max, v)))
  }
  const pan = useRef(PanResponder.create({
    onStartShouldSetPanResponder: () => true,
    onMoveShouldSetPanResponder: () => true,
    onPanResponderGrant: (evt) => { startX.current = evt.nativeEvent.locationX; at(startX.current) },
    onPanResponderMove: (_, g) => at(startX.current + g.dx),
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
        <View style={s.rail} />
        <View style={[s.fill, { width: x }]} />
        {w > 0 && markers.map(m => {
          const up = (m.side === 1) === topIsP1
          const left = THUMB / 2 + (w - THUMB) * (m.i / max) - (m.adj ? 3 : 0) - 1.5
          return (
            <View key={`${m.kind}${m.i}${m.adj ? 'a' : ''}`}
                  style={[s.tick, up ? s.tickUp : s.tickDown, { left, backgroundColor: TICK[m.kind] }]} />
          )
        })}
        <View style={[s.thumb, { left: x - THUMB / 2 }]} />
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
        <Text style={[s.statName, { color: C.clay }]} numberOfLines={1}>{left}</Text>
        <Text style={[s.statName, { color: C.info, textAlign: 'right' }]} numberOfLines={1}>{right}</Text>
      </View>
      {rows.map(([label, lw, lt, rw, rt]) => (
        <View key={label} style={s.statRow}>
          <View style={s.statHalf}>
            <Text style={s.statNum}>{lt ? `${pct(lw, lt)}%` : '—'}<Text style={s.statSmall}>{lt ? ` (${lw}/${lt})` : ''}</Text></Text>
            <View style={s.barL}><View style={[s.barFill, { backgroundColor: C.clay, width: `${lt ? pct(lw, lt) : 0}%` }]} /></View>
          </View>
          <Text style={s.statLabel}>{label}</Text>
          <View style={s.statHalf}>
            <View style={s.barR}><View style={[s.barFill, { backgroundColor: C.info, width: `${rt ? pct(rw, rt) : 0}%` }]} /></View>
            <Text style={[s.statNum, { textAlign: 'right' }]}>{rt ? `${pct(rw, rt)}%` : '—'}<Text style={s.statSmall}>{rt ? ` (${rw}/${rt})` : ''}</Text></Text>
          </View>
        </View>
      ))}
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
  nameTop: { ...T.tiny, color: C.muted, fontFamily: 'Archivo_700Bold' },
  nameBot: { ...T.tiny, color: C.muted, fontFamily: 'Archivo_700Bold' },
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
  stats: { gap: 6, marginTop: S.xs },
  statNames: { flexDirection: 'row', justifyContent: 'space-between', gap: S.sm },
  statName: { ...T.smallMed, flex: 1 },
  statRow: { gap: 2 },
  statHalf: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  statNum: { ...T.tiny, color: C.ink, minWidth: 74 },
  statSmall: { ...T.tiny, color: C.faint },
  statLabel: { ...T.tiny, color: C.faint, textAlign: 'center', lineHeight: leading(14) },
  barL: { flex: 1, height: 6, borderRadius: 3, backgroundColor: C.border, overflow: 'hidden', alignItems: 'flex-end' },
  barR: { flex: 1, height: 6, borderRadius: 3, backgroundColor: C.border, overflow: 'hidden' },
  barFill: { height: 6, borderRadius: 3 },
})
