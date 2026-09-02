/*
 * The order of play.
 *
 * Two views, because they answer different questions and the website learned
 * that the hard way:
 *
 *   Time   "what is on now / next" — one chronological list
 *   Court  "what is happening on Ashe" — grouped, in the sheet's own order
 *
 * Live matches float to the top in Time view. On a phone this is the screen
 * someone opens twenty times a day during a slam, so the thing they came for
 * has to be above the fold rather than sorted correctly.
 */

import { useMemo, useState } from 'react'
import { Ionicons } from '@expo/vector-icons'
import { Stack } from 'expo-router'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { getScheduleDates, getScheduleDay } from '../../api'
import { useApi } from '../../useApi'
import {
  gamesOf, isLive, isSuspended, pointOf, servingSide, sideDrawRank, sideFlags,
  sideName, sideSeed, whenLabel, winnerSide,
} from '../../schedule'
import { clockTime, shortStart } from '../../dates'
import { FlagSlot, PlayerName, PosBadge, TourBadge } from '../../cards'
import { C, R, S, T } from '../../theme'
import { Card, ErrorNote, Eyebrow, Loading, Muted, Screen, Title } from '../../ui'

const today = () => new Date().toISOString().slice(0, 10)

export default function ScheduleScreen() {
  const [date, setDate] = useState(today)
  const [view, setView] = useState('time')

  const dates = useApi('schedule-dates', getScheduleDates)
  const day = useApi(`schedule:${date}`, () => getScheduleDay(date))

  // `|| []` allocates a fresh array every render, so the useMemo below would
  // recompute on every keystroke of state elsewhere. Memoised on the identity
  // of the fetched data instead.
  const all = useMemo(() => day.data?.entries || [], [day.data])
  const available = dates.data?.dates || []
  const idx = available.indexOf(date)

  const groups = useMemo(() => {
    if (view === 'court') {
      const order = day.data?.courts || []
      const by = new Map()
      for (const e of all) {
        const k = e.court || 'Court TBA'
        if (!by.has(k)) by.set(k, [])
        by.get(k).push(e)
      }
      for (const list of by.values()) {
        list.sort((a, b) => (a.court_order ?? 99) - (b.court_order ?? 99))
      }
      // The sheet's own court order, not alphabetical: Ashe is not "A".
      const known = order.filter(c => by.has(c))
      const rest = [...by.keys()].filter(c => !order.includes(c))
      return [...known, ...rest].map(c => [c, by.get(c)])
    }

    // Time: live first — this screen is opened to find what is on NOW — then
    // by the sheet's expected start, then by court order within a slot.
    const sorted = [...all].sort((a, b) => {
      const la = isLive(a) ? 0 : a.status === 'completed' ? 2 : 1
      const lb = isLive(b) ? 0 : b.status === 'completed' ? 2 : 1
      if (la !== lb) return la - lb
      const ta = a.expected_start_at || a.printed_start_at || ''
      const tb = b.expected_start_at || b.printed_start_at || ''
      if (ta !== tb) return ta.localeCompare(tb)
      return (a.court_order ?? 99) - (b.court_order ?? 99)
    })
    return [[null, sorted]]
  }, [all, view, day.data])

  const refetch = () => { day.refetch(); dates.refetch() }
  const liveCount = all.filter(isLive).length

  return (
    <>
      <Stack.Screen options={{ title: 'Schedule' }} />
      <Screen onRefresh={refetch} refreshing={day.loading && !!day.data}>
        <View style={s.bar}>
          <Pressable
            onPress={() => idx > 0 && setDate(available[idx - 1])}
            disabled={idx <= 0} hitSlop={10}
            style={({ pressed }) => [s.arrow, (idx <= 0) && s.arrowOff, pressed && { opacity: 0.6 }]}
          >
            <Ionicons name="chevron-back" size={20} color={C.ink} />
          </Pressable>
          <View style={s.dateBox}>
            <Text style={[T.h2, { color: C.ink }]}>{prettyDate(date)}</Text>
            {liveCount > 0 && (
              <Text style={[T.tiny, { color: C.greenLit }]}>{liveCount} on court</Text>
            )}
          </View>
          <Pressable
            onPress={() => idx >= 0 && idx < available.length - 1 && setDate(available[idx + 1])}
            disabled={idx < 0 || idx >= available.length - 1} hitSlop={10}
            style={({ pressed }) => [
              s.arrow, (idx < 0 || idx >= available.length - 1) && s.arrowOff,
              pressed && { opacity: 0.6 },
            ]}
          >
            <Ionicons name="chevron-forward" size={20} color={C.ink} />
          </Pressable>
        </View>

        <View style={s.tabs}>
          {['time', 'court'].map(v => (
            <Pressable key={v} onPress={() => setView(v)}
                       style={[s.tab, view === v && s.tabOn]}>
              <Text style={[T.smallMed, { color: view === v ? C.ink : C.muted }]}>
                {v === 'time' ? 'Time' : 'Court'}
              </Text>
            </Pressable>
          ))}
        </View>

        {day.loading && !day.data ? <Loading /> : null}
        <ErrorNote error={day.error} onRetry={refetch} />

        {day.data && all.length === 0 && (
          <Card>
            <Title>No play scheduled</Title>
            <Muted>Nothing is listed for this day.</Muted>
          </Card>
        )}

        {groups.map(([court, list]) => (
          <View key={court || 'all'} style={s.group}>
            {court ? <Eyebrow>{court}</Eyebrow> : null}
            {list.map(e => <EntryRow key={e.id} e={e} />)}
          </View>
        ))}
      </Screen>
    </>
  )
}

function EntryRow({ e }) {
  const live = isLive(e)
  const suspended = isSuspended(e)
  const games = gamesOf(e)
  const point = pointOf(e)
  const serving = servingSide(e)
  const won = winnerSide(e)
  const done = e.status === 'completed'
  /* resumed_at wins over started_at: after a rain delay the resumption is the
     time that answers "when did this get going", and the original start is
     hours of stopped play ago. See the rain-delay lifecycle. */
  /* Both rows get the SAME number of flag slots — a doubles pair needs two —
     so the two names still start at the same x. */
  const flagSlots = Math.max(
    1, sideFlags(e.players, 'a').length, sideFlags(e.players, 'b').length)
  const started = clockTime(e.resumed_at || e.started_at)
  /* "Wed 8:00 AM", never "Tomorrow at 8:00 AM PDT" — that ran off the end of
     the row and truncated to "Tomorrow at 8:00 …". Note the site does NOT show
     an expected start on its schedule at all: the printed start already sits at
     the top-right of every row. This is the same moment in the READER's zone
     rather than the venue's, which is the only thing the printed time cannot
     tell them. */
  const upcoming = !started && !done
    ? shortStart(e.expected_start_at, e.expected_source)
    : null

  return (
    <View style={[s.entry, live && s.entryLive]}>
      <View style={s.entryTop}>
        {/* The tour, named. A combined day lists the men's and women's US Open
            as the same "US Open · R128" and nothing else separated them. */}
        <TourBadge gender={e.gender} />
        <Text style={[T.tiny, { color: C.faint, flex: 1 }]} numberOfLines={1}>
          {[e.tournament_name, e.round_label, e.discipline !== 'singles' ? 'Doubles' : null]
            .filter(Boolean).join(' · ')}
        </Text>
        <Text style={[T.tiny, {
          color: suspended ? C.warn : live ? C.greenLit : done ? C.faint : C.muted,
        }]}>
          {whenLabel(e)}
        </Text>
      </View>

      {['a', 'b'].map(side => (
        <PlayerLine
          key={side}
          name={sideName(e.players, side)}
          doubles={e.discipline !== 'singles'}
          seed={sideSeed(e.players, side)}
          drawRank={sideDrawRank(e.players, side)}
          flags={sideFlags(e.players, side)}
          flagSlots={flagSlots}
          games={games ? games[side === 'a' ? 0 : 1] : null}
          point={point ? point[side === 'a' ? 0 : 1] : null}
          serving={serving === side && !done}
          won={won === side}
          dim={done && won && won !== side}
        />
      ))}

      {/* Court and time on ONE line. The site gives the time its own block, but
          a phone row that already carries two players and a set-by-set score
          cannot spend a whole line saying "Started at". */}
      {(e.court || started || upcoming) && (
        <Text style={[T.tiny, { color: C.faint }]} numberOfLines={1}>
          {[e.court, started ? `Started ${started}` : upcoming].filter(Boolean).join(' · ')}
        </Text>
      )}
    </View>
  )
}

function PlayerLine({ name, doubles, seed, drawRank, flags, flagSlots, games, point, serving, won, dim }) {
  return (
    <View style={s.line}>
      <View style={[s.dot, serving && { backgroundColor: C.clay }]} />
      {/* Badge and flag are FIXED-WIDTH columns and are drawn even when empty.
          That is the whole point: a seeded player and an unseeded one, a player
          with a flag and a neutral athlete without, all start their name at the
          same x. Without it the rows staggered and the pair stopped reading as
          one match. */}
      <PosBadge seed={seed} drawRank={drawRank} />
      <FlagSlot codes={flags} slots={flagSlots} />
      <PlayerName
        name={name}
        doubles={doubles}
        style={[T.bodyMed, { color: dim ? C.muted : C.ink, flexShrink: 1 }, won && { color: C.ink }]}
      />
      <View style={{ flex: 1 }} />
      <View style={s.scores}>
        {(games || []).map((g, i) => (
          <Text key={i} style={[T.score, { color: dim ? C.muted : C.ink }]}>
            {g === null || g === '' ? '–' : g}
          </Text>
        ))}
        {point != null && (
          <Text style={[T.score, { color: C.clay, minWidth: 26, textAlign: 'right' }]}>
            {point}
          </Text>
        )}
      </View>
    </View>
  )
}

function prettyDate(iso) {
  const d = new Date(iso + 'T12:00:00Z')
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
}

const s = StyleSheet.create({
  bar: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: S.md },
  dateBox: { alignItems: 'center' },
  arrow: {
    width: 40, height: 40, borderRadius: R.pill, alignItems: 'center', justifyContent: 'center',
    borderWidth: 1, borderColor: C.border, backgroundColor: C.card,
  },
  arrowOff: { opacity: 0.3 },
  /* The arrows are ICONS, not text glyphs. "‹" in a 40pt circle sat visibly
     high: a typographic glyph carries its font's own vertical metrics, and a
     hand-set lineHeight (26 here) fights the centring rather than fixing it.
     An icon font draws inside its box, so it centres by construction. */

  tabs: { flexDirection: 'row', gap: S.xs, backgroundColor: C.sunken, borderRadius: R.md, padding: 3 },
  tab: { flex: 1, alignItems: 'center', paddingVertical: S.sm, borderRadius: R.sm },
  tabOn: { backgroundColor: C.raised },

  group: { gap: S.xs, marginTop: S.sm },
  entry: {
    backgroundColor: C.card, borderRadius: R.md, borderWidth: 1, borderColor: C.border,
    padding: S.md, gap: 3,
  },
  entryLive: { borderColor: C.green },
  entryTop: { flexDirection: 'row', alignItems: 'center', gap: S.sm },
  line: { flexDirection: 'row', alignItems: 'center', gap: S.sm },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: 'transparent' },
  flag: { fontSize: 13 },
  scores: { flexDirection: 'row', alignItems: 'center', gap: S.sm },
})
