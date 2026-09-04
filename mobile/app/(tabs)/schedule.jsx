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

import { useEffect, useMemo, useState } from 'react'
import { Ionicons } from '@expo/vector-icons'
import { Stack, useLocalSearchParams } from 'expo-router'
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native'
import { getScheduleDates, getScheduleDay, listTournaments, updateMe } from '../../api'
import { useAuth } from '../../auth'
import { H2HSheet } from '../../h2h'
import { isAvailable as lockScreenAvailable } from '../../modules/live-activity'
import { hideFromLockScreen, showMatchOnLockScreen, useShowingOnLockScreen } from '../../liveactivity'
import { useLiveUpdates } from '../../live'
import { useApi } from '../../useApi'
import { isLive, isSuspended, whenLabel } from '../../schedule'
import { clockTime, shortStart } from '../../dates'
import { leading } from '../../fontScale.js'
import { TourBadge } from '../../cards'
import { MatchCard } from '../../scorecard'
import { ScoreHistorySheet } from '../../scoreHistory'
import { C, R, S, T } from '../../theme'
import { Card, CardLink, ErrorNote, Eyebrow, Loading, Muted, Screen, Title } from '../../ui'

const today = () => new Date().toISOString().slice(0, 10)

/* THE EARLIEST DAY WITH TENNIS LEFT IN IT, never earlier than today — the
   site's rule, verbatim in intent. "Today" is not blindly the answer: out of
   season today has no sheet at all, and at the end of a Slam day every match
   is decided and the reader wants tomorrow's card. So the day is chosen from
   the dates that EXIST, a day whose matches are all finished is stepped over,
   and if nothing from today onward has anything open the last such day stands.
   A date that was asked for is clamped to the list so an old link cannot
   strand the page on a day with nothing on it. */
function landingDay(dates, openCounts, asked) {
  if (!dates.length) return asked || today()
  if (asked && dates.includes(asked)) return asked
  const t = today()
  const upcoming = dates.filter(d => d >= t)
  const firstOpen = upcoming.find(d => (openCounts[d] ?? 1) > 0)
  return firstOpen || upcoming[upcoming.length - 1] || dates[dates.length - 1]
}

export default function ScheduleScreen() {
  // From a dashboard card: which tournament's sheets, which draw we came from,
  // and (from a link) which day. The tab still works with none of them.
  const params = useLocalSearchParams()
  const tournament = params.tournament ? Number(params.tournament) : undefined
  const fromDraw = params.draw ? Number(params.draw) : undefined
  const asked = typeof params.date === 'string' ? params.date : undefined
  // null = follow the landing rule; a tap on an arrow pins a day.
  const [pinned, setPinned] = useState(null)
  /* The site's filters and their defaults: completed rows shown, doubles
     hidden, every tour on — except when arriving from a draw, when only that
     draw's tour is on. tourSel is a SET so ATP+WTA is expressible. */
  const [showDone, setShowDone] = useState(true)
  const [showDoubles, setShowDoubles] = useState(false)
  const [tourSel, setTourSel] = useState(null)
  /* Venue clock or the reader's own — an ACCOUNT preference (users.schedule_tz),
     saved through the same PATCH the site uses, so it follows the reader from
     phone to desktop. Optimistic; a failed save keeps the local choice. */
  const { me, retry: refreshMe } = useAuth()
  const [tzMode, setTzModeState] = useState(me?.schedule_tz === 'user' ? 'user' : 'venue')
  const setTzMode = (mode) => {
    setTzModeState(mode)
    updateMe({ schedule_tz: mode }).then(() => refreshMe?.()).catch(() => {})
  }
  const [h2h, setH2H] = useState(null)
  const [hist, setHist] = useState(null)
  const [view, setView] = useState('time')

  const dates = useApi(`schedule-dates:${tournament ?? 'all'}`, () => getScheduleDates(tournament))
  const available = dates.data?.dates || []
  const date = pinned ?? landingDay(available, dates.data?.open_counts || {}, asked)
  const idx = available.indexOf(date)
  const day = useApi(`schedule:${date}`, () => getScheduleDay(date))
  /* Refetch the day whenever any tournament on it changes — the site's rule.
     A day can span two tournaments, and subscribing to only the first would
     leave the other silently stale. The history sheet's key changes with the
     row, so it follows. */
  useLiveUpdates((day.data?.tournaments || []).map(t => t.id), [`schedule:${date}`, 'hist:'])

  // `|| []` allocates a fresh array every render, so the useMemo below would
  // recompute on every keystroke of state elsewhere. Memoised on the identity
  // of the fetched data instead.
  const all = useMemo(() => day.data?.entries || [], [day.data])
  const tours = useMemo(() => [...new Set(all.map(e => e.tour).filter(Boolean))].sort(), [all])
  const hasDoubles = useMemo(() => all.some(e => e.discipline !== 'singles'), [all])
  useEffect(() => {
    if (!all.length) return
    const origin = fromDraw ? all.find(e => e.draw_id === fromDraw) : null
    setTourSel(new Set(origin?.tour ? [origin.tour] : tours))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [day.data, fromDraw])
  const toggleTour = t => setTourSel(prev => {
    const cur = new Set(prev ?? tours)
    if (cur.has(t)) cur.delete(t); else cur.add(t)
    return cur
  })
  const venueMode = tzMode === 'venue'
  // The venue's zone for a row, from the day's tournament list.
  const venueTzOf = e => (day.data?.tournaments || []).find(t => t.id === e.tournament_id)?.venue_timezone || undefined
  // Grey the Draw link when its draw has nothing to show — a Slam's qualifying
  // sheet is live days before the bracket, and a live link to an empty draw
  // reads as a broken page. Same released rule the dashboard cards use.
  const drawsList = useApi(fromDraw ? 'tournaments' : null, listTournaments)
  const fromRow = (drawsList.data || []).find(d => d.id === fromDraw)
  const drawReady = !drawsList.data || !fromRow || fromRow.status === 'completed' || !!fromRow.draw_released_direct_at

  /* The site's rules, applied ONCE so both views see them: doubles only when
     asked and only in the time view; completed rows only when asked; a tour
     only while selected. The first version filtered inside the court loop
     alone, so the time view — the default — ignored every chip. Kept apart
     from the grouping so the empty state can tell "nothing published" from
     "the switches hid everything". */
  const visible = useMemo(() => {
    return all.filter(e => {
      if (view === 'time' && e.discipline !== 'singles' && !showDoubles) return false
      // "Completed" off means no longer upcoming on this day — the site's
      // rule: a match postponed off today's sheet leaves with the finished ones,
      // so what remains is on court now or still waiting to get there.
      if (!showDone && (e.status === 'completed' || e.status === 'postponed')) return false
      if (view === 'time' && tourSel && e.tour && !tourSel.has(e.tour)) return false
      return true
    })
  }, [all, view, showDone, showDoubles, tourSel])

  const groups = useMemo(() => {
    if (view === 'court') {
      const by = new Map()
      for (const e of visible) {
        const k = e.court || 'Court TBA'
        if (!by.has(k)) by.set(k, [])
        by.get(k).push(e)
      }
      for (const list of by.values()) {
        list.sort((a, b) => (a.court_order ?? 99) - (b.court_order ?? 99))
      }
      // The site's rule: courts are ordered by the best seed playing on them,
      // so the show courts rise to the top without hardcoding venue names —
      // every tournament calls its main court something different. Then by
      // how many matches a court hosts, then name. Singles only: a doubles
      // [1] says nothing next to a singles [1]. A finite sentinel, not
      // Infinity — two unseeded courts would compare as NaN and a NaN
      // comparator leaves the array in whatever order it started.
      const NO_SEED = 9999
      const ranked = [...by.entries()].map(([name, list]) => {
        let best = NO_SEED, count = 0
        for (const e of list) {
          if (e.discipline !== 'singles') continue
          count += 1
          for (const p of e.players || []) if (p.seed != null && p.seed < best) best = p.seed
        }
        return { name, list, best, count }
      })
      ranked.sort((a, b) => a.best - b.best || b.count - a.count || a.name.localeCompare(b.name))
      return ranked.map(r => [r.name, r.list])
    }

    // Time: a chronology of the day, the site's rule exactly (Schedule.jsx
    // timeEntries). Sort on the same instant the row DISPLAYS — when a match
    // actually began, else the estimate — or a match that went on late sits
    // among the slots it was printed beside while its own row says "Started
    // at" some quite different time. A match carried over from yesterday
    // keeps yesterday's started_at (that is what the field means), so it is
    // keyed on when it comes back today: resumed_at once it has, the slot it
    // is due in until then.
    const key = e => {
      if (e.resumed_at) return e.resumed_at
      if (e.status === 'to_be_completed') return e.expected_start_at || ''
      return e.started_at || e.expected_start_at || ''
    }
    const sorted = [...visible].sort((a, b) => {
      const ka = key(a), kb = key(b)
      if (ka !== kb) return ka < kb ? -1 : 1
      // Same instant: keep a court's own running order intact.
      return (a.court || '').localeCompare(b.court || '')
        || (a.court_order ?? 99) - (b.court_order ?? 99)
    })
    return [[null, sorted]]
  }, [visible, view])

  const refetch = () => { day.refetch(); dates.refetch() }
  const liveCount = all.filter(isLive).length

  return (
    <>
      <Stack.Screen options={{ title: 'Schedule' }} />
      <Screen onRefresh={refetch}>
        <View style={s.bar}>
          <Pressable
            onPress={() => idx > 0 && setPinned(available[idx - 1])}
            disabled={idx <= 0} hitSlop={10}
            style={({ pressed }) => [s.arrow, (idx <= 0) && s.arrowOff, pressed && { opacity: 0.6 }]}
            accessibilityRole="button" accessibilityLabel="Previous day"
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
            onPress={() => idx >= 0 && idx < available.length - 1 && setPinned(available[idx + 1])}
            disabled={idx < 0 || idx >= available.length - 1} hitSlop={10}
            style={({ pressed }) => [
              s.arrow, (idx < 0 || idx >= available.length - 1) && s.arrowOff,
              pressed && { opacity: 0.6 },
            ]}
            accessibilityRole="button" accessibilityLabel="Next day"
          >
            <Ionicons name="chevron-forward" size={20} color={C.ink} />
          </Pressable>
        </View>

        {fromDraw ? (
          <CardLink href={drawReady ? `/draw/${fromDraw}` : undefined} style={[s.back, !drawReady && s.arrowOff]}>
            <Ionicons name="chevron-back" size={14} color={C.greenLit} />
            <Text style={[T.smallMed, { color: C.greenLit }]}>
              {fromRow?.name ? `${fromRow.name} draw` : 'Draw'}
            </Text>
          </CardLink>
        ) : null}

        <View style={s.filters}>
          {/* The tour chips filter the time view only, so the court view does
              not offer them — the site's rule; a chip that toggles nothing
              reads as broken. And one tour needs no chip. */}
          {view === 'time' && tours.length > 1 && tours.map(t => {
            const on = !tourSel || tourSel.has(t)
            return (
              <Pressable key={t} onPress={() => toggleTour(t)}
                         style={[s.chip, on && (t === 'WTA' ? s.chipWta : s.chipAtp)]}
                         accessibilityRole="button" accessibilityState={{ selected: on }}>
                <Text style={[s.chipText, on && { color: '#fff' }]}>{t}</Text>
              </Pressable>
            )
          })}
          {/* Only a day that HAS doubles offers the switch — the site's rule.
              A chip that toggles nothing reads as broken. */}
          {view === 'time' && hasDoubles && (
            <Pressable onPress={() => setShowDoubles(v => !v)} style={[s.chip, showDoubles && s.chipOn]}
                       accessibilityRole="button" accessibilityState={{ selected: showDoubles }}>
              <Text style={[s.chipText, showDoubles && { color: '#fff' }]}>Doubles</Text>
            </Pressable>
          )}
          <Pressable onPress={() => setShowDone(v => !v)} style={[s.chip, showDone && s.chipOn]}
                     accessibilityRole="button" accessibilityState={{ selected: showDone }}>
            <Text style={[s.chipText, showDone && { color: '#fff' }]}>Completed</Text>
          </Pressable>
          <View style={{ flex: 1 }} />
          <View style={s.tz}>
            {[['venue', 'Venue'], ['user', 'My time']].map(([k, label]) => (
              <Pressable key={k} onPress={() => setTzMode(k)}
                         style={[s.tzBtn, tzMode === k && s.tzOn]}
                         accessibilityRole="button" accessibilityState={{ selected: tzMode === k }}>
                <Text style={[s.chipText, tzMode === k && { color: '#fff' }]}>{label}</Text>
              </Pressable>
            ))}
          </View>
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

        {/* Two kinds of nothing, in the site's words: a day the tournament has
            not published, and a published day the reader's own switches have
            emptied — which used to render as a blank screen. Name the switch
            that brings the rows back. */}
        {day.data && all.length === 0 && (
          <Card>
            <Title>No order of play published for this day.</Title>
            <Muted>Schedules appear once the tournament releases them, usually the evening before.</Muted>
          </Card>
        )}
        {day.data && all.length > 0 && visible.length === 0 && (
          <Card>
            <Title>Nothing left to show for this day.</Title>
            <Muted>
              {!showDone && all.some(e => e.status === 'completed' || e.status === 'postponed')
                ? 'Every match listed is finished or postponed — switch Completed on to see them.'
                : !showDoubles && all.every(e => e.discipline !== 'singles')
                  ? 'Only doubles is listed — switch Doubles on to see it.'
                  : 'The current switches hide every match listed.'}
            </Muted>
          </Card>
        )}

        {groups.map(([court, list]) => (
          <View key={court || 'all'} style={s.group}>
            {court ? <Eyebrow>{court}</Eyebrow> : null}
            {list.map(e => <EntryRow venueMode={venueMode} venueTz={venueTzOf(e)} onH2H={setH2H} onHistory={setHist} key={e.id} e={e} inCourt={view === 'court'} />)}
          </View>
        ))}
      </Screen>
      <H2HSheet visible={!!h2h} onClose={() => setH2H(null)} a={h2h?.a} b={h2h?.b} />
      {/* The row as the schedule holds it NOW, looked up by id, so a live match
          keeps ticking in the sheet while it is open. */}
      <ScoreHistorySheet visible={!!hist} onClose={() => setHist(null)}
                         entry={hist ? (all.find(x => x.id === hist.id) || hist) : null} />
    </>
  )
}

/* ON THE LOCK SCREEN, OR NOT — and the switch for it. Left of H2H, in the
   same chip language. Lit while this match has a Live Activity; a tap on a
   live match puts it there, a tap on a lit one takes it off. Only rows that
   could be there show it: a live singles match, or one still showing after
   it finished (the end push retires that one on its own). Nothing on builds
   without the native module. */
function LockPill({ matchId, live }) {
  const [showing, recheck] = useShowingOnLockScreen(matchId)
  const [busy, setBusy] = useState(false)
  if (!lockScreenAvailable() || (!showing && !live)) return null
  const toggle = async () => {
    if (busy) return
    setBusy(true)
    try {
      if (showing) await hideFromLockScreen(matchId)
      else await showMatchOnLockScreen(matchId)
    } catch (err) {
      Alert.alert('Lock Screen', err?.message || 'Could not change the Lock Screen')
    } finally {
      setBusy(false)
      recheck()
    }
  }
  return (
    <Pressable onPress={toggle} hitSlop={8}
               accessibilityRole="switch" accessibilityState={{ checked: showing, busy }}
               accessibilityLabel={showing ? 'On your Lock Screen — tap to remove' : 'Show on your Lock Screen'}
               style={[s.h2hChip, showing && s.lockChipOn, busy && { opacity: 0.6 }]}>
      <Text style={[s.h2hText, showing && s.lockTextOn]}>{showing ? '🔒 ON LOCK SCREEN' : '🔒 LOCK SCREEN'}</Text>
    </Pressable>
  )
}

function EntryRow({ e, venueMode, venueTz, onH2H, onHistory, inCourt }) {
  const live = isLive(e)
  const suspended = isSuspended(e)
  const done = e.status === 'completed'
  /* resumed_at wins over started_at: after a rain delay the resumption is the
     time that answers "when did this get going", and the original start is
     hours of stopped play ago. See the rain-delay lifecycle. */
  const a = (e.players || []).find(p => p.side === 'a'), b = (e.players || []).find(p => p.side === 'b')
  const h2hPair = e.discipline === 'singles' && a?.te_slug && b?.te_slug
    ? { a: { name: a.entry_name || a.name, te_slug: a.te_slug }, b: { name: b.entry_name || b.name, te_slug: b.te_slug } }
    : null
  /* The same split the site makes: venue mode renders a started match's
     time in the VENUE's zone, the reader's mode in theirs. Both show it —
     hiding it in venue mode was this app's invention. */
  /* The site's startedLine, exactly: only a match on court or finished names
     its start, and one picked up again names the time it came BACK. A row
     carried over from yesterday still holds yesterday's started_at — that is
     what the field means — so it names the slot it returns in instead, like
     any pending row. */
  const resumed = !!e.resumed_at
    && (!e.started_at || new Date(e.resumed_at) > new Date(e.started_at))
  const started = (live || done)
    ? clockTime(resumed ? e.resumed_at : e.started_at, venueMode ? venueTz : undefined)
    : null
  const startedWord = resumed ? 'Resumed' : 'Started'
  const postponed = e.status === 'postponed'
  const carried = e.status === 'to_be_completed'
  /* "Wed 8:00 AM", never "Tomorrow at 8:00 AM PDT" — that ran off the end of
     the row and truncated to "Tomorrow at 8:00 …". Note the site does NOT show
     an expected start on its schedule at all: the printed start already sits at
     the top-right of every row. This is the same moment in the READER's zone
     rather than the venue's, which is the only thing the printed time cannot
     tell them. */
  const upcoming = !started && !done
    ? shortStart(e.expected_start_at, e.expected_source, venueMode ? venueTz : undefined)
    : null

  /* A started match answers a tap with its history — the same sheet, slider
     and card the draw page opens, because the two surfaces describe the same
     match. Scheduled rows stay inert: nothing to show, and a dead tap reading
     as a broken page is the draw page's own documented lesson. */
  const openable = onHistory && ['live', 'completed', 'postponed', 'to_be_completed'].includes(e.status)
  const Wrap = openable ? Pressable : View
  return (
    <Wrap style={[s.entry, live && s.entryLive]} onPress={openable ? () => onHistory(e) : undefined}>
      <View style={s.entryTop}>
        {/* The tour, named. A combined day lists the men's and women's US Open
            as the same "US Open · R128" and nothing else separated them. */}
        <TourBadge gender={e.gender} />
        <Text style={[T.tiny, { color: C.faint, flex: 1 }]} numberOfLines={1}>
          {[e.tournament_name, e.round_label, e.discipline !== 'singles' ? 'Doubles' : null]
            .filter(Boolean).join(' · ')}
        </Text>
        <Text style={[T.tiny, {
          // The site's badge colours: amber for play that stopped, blue for a
          // match carried to a later day, green for one on court.
          color: suspended || postponed ? C.warn : carried ? C.info
            : live ? C.greenLit : done ? C.faint : C.muted,
        }]}>
          {whenLabel(e, venueMode ? venueTz : undefined, venueMode)}
        </Text>
      </View>

      <MatchCard e={e} />

      {/* Court and time on ONE line. The site gives the time its own block, but
          a phone row that already carries two players and a set-by-set score
          cannot spend a whole line saying "Started at". */}
      {/* Court and time on the left, H2H on the right — ONE line. The chip had
          its own row, which cost every match a line for a button most rows
          never tap. The site's rail sits beside the row for the same reason. */}
      {((!inCourt && e.court) || started || upcoming || h2hPair) && (
        <View style={s.footLine}>
          <Text style={[T.tiny, { color: C.faint, flex: 1 }]} numberOfLines={1}>
            {/* Grouped under its court already, a row need not repeat it. */}
            {[inCourt ? null : e.court, started ? `${startedWord} ${started}` : upcoming].filter(Boolean).join(' · ')}
          </Text>
          {e.match_id != null && (live || done) && (
            <LockPill matchId={e.match_id} live={live} />
          )}
          {h2hPair && (
            <Pressable onPress={() => onH2H(h2hPair)} hitSlop={8} style={s.h2hChip}>
              <Text style={s.h2hText}>H2H</Text>
            </Pressable>
          )}
        </View>
      )}
    </Wrap>
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

  back: { flexDirection: 'row', alignItems: 'center', gap: 2, alignSelf: 'flex-start', paddingVertical: 4 },
  filters: { flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' },
  chip: { borderRadius: R.pill, borderWidth: 1, borderColor: C.border, backgroundColor: C.card, paddingHorizontal: 10, paddingVertical: 5 },
  chipOn: { backgroundColor: C.green, borderColor: C.green },
  chipAtp: { backgroundColor: '#2563eb', borderColor: '#2563eb' },
  chipWta: { backgroundColor: '#db2777', borderColor: '#db2777' },
  chipText: { ...T.tiny, color: C.muted, fontFamily: 'Archivo_700Bold' },
  tz: { flexDirection: 'row', backgroundColor: C.sunken, borderRadius: R.pill, padding: 2 },
  tzBtn: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: R.pill },
  tzOn: { backgroundColor: C.green },
  footLine: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  h2hChip: { borderRadius: 4, borderWidth: 1, borderColor: C.borderOn, paddingHorizontal: 7, paddingVertical: 2 },
  h2hText: { fontFamily: 'Archivo_700Bold', fontSize: 10, lineHeight: leading(14), letterSpacing: 0.5, color: C.greenLit },
  lockChipOn: { backgroundColor: C.greenLit, borderColor: C.greenLit },
  lockTextOn: { color: C.bg },
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
})
