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

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Ionicons } from '@expo/vector-icons'
import { useLocalSearchParams } from 'expo-router'
import { Alert, Pressable, StyleSheet, Text, View, useWindowDimensions } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import { scheduleOnRN } from 'react-native-worklets'
import { getScheduleDates, getScheduleDay, listTournaments } from '../../api'
import { useAuth } from '../../auth'
import { ChampionFanfare, TierFx } from '../../fx'
import { FX_MS, arrivalTier, scoreMarks, useScoreEvent } from '../../scoreFx'
import { H2HSheet } from '../../h2h'
import { PredictorsSheet } from '../../predictors'
import { isAvailable as lockScreenAvailable } from '../../modules/live-activity'
import { hideFromLockScreen, showMatchOnLockScreen, useShowingOnLockScreen } from '../../liveactivity'
import { showToast } from '../../toast'
import { useLiveUpdates } from '../../live'
import { useApi } from '../../useApi'
import { PHASES, byTimeOfDay, effectivePhase, matchPhase, phaseCounts, footTime, isLive, isSuspended, hasStarted, matchFromEntry, rowClock, rowWhen, sideFlags, startedFirst, whenLabel } from '../../schedule'
import { leading } from '../../fontScale.js'
import { FitText, FlagSlot, TierBadge, TourBadge } from '../../cards'
import { setScheduleTournaments, useScheduleTournaments } from '../../scheduleFilter'
import { useChoosableTournaments } from '../../choosableTournaments'
import { DayStrip } from '../../DayStrip'
import { SWIPE_PX, SWIPE_VX, swipeStep } from '../../swipeDay'
import { beginSwipe, endSwipe, unlessSwiping } from '../../swipeGuard'
import { dayLabels, relativeDayWord } from '../../dayLabels'
import { holdSelection, rowInTournaments } from '../../scheduleRows'
import { eventTour, tierWord } from '../../category'
import { MatchCard } from '../../scorecard'
import { matchLine } from '../../matchLine'
import { courtGroups } from '../../courtGroups'
import { fitPillSize, textWidth } from '../../measure'
import { bestLeftColumn } from '../../nameColumns'
import { groupPastDay } from '../../pastGroups'
import { stampsFor } from '../../logos'
import { longRound } from '../../rounds'
import { CourtRenameSheet, TournamentRenameSheet } from '../../rename'
import { MatchMenu, actionsFor } from '../../matchMenu'
import { ScoreHistorySheet } from '../../scoreHistory'
import { C, R, S, T } from '../../theme'
import { Card, CardLink, ErrorNote, Loading, Muted, Screen, Title, eyebrowType } from '../../ui'

/* The DEVICE's calendar date — the schedule's rule (the zone is the device).
   toISOString() is UTC, which after 5 PM Pacific already names tomorrow: the
   page then landed on tomorrow's sheet during the evening session, and the
   strip would have called the wrong day "Today" every night. */
const today = () => {
  const d = new Date()
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
}

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
  /* AND IT RESETS ON ARRIVAL. This screen is a TAB, so it stays mounted: read
     an active tournament's sheets, page to a day, go back to the dashboard and
     open a finished event's Order of Play, and the same component re-renders
     with new params and the OLD day still pinned. The US Open opened on
     15 September — a day it never played — with nothing listed, both arrows
     dead (that day is not in its date list, so there is no neighbour to step
     to) and the header counting the three matches on court at OTHER
     tournaments (owner, 2026-09-15).

     Keyed on the arrival, not on the route: the same params re-rendering is
     not an arrival, and paging days inside one visit must not undo itself. */
  useEffect(() => { setPinned(null) }, [tournament, fromDraw, asked])
  /* WHICH OF THE DAY'S THREE the reader is looking at — null until they pick
     one, and then it follows them (owner, 2026-09-20). This replaces a
     Completed toggle that answered a narrower question: the day has finished
     matches, matches on court and matches to come, and one switch across the
     page says which of the three rather than hiding one of them. */
  const [phase, setPhase] = useState(null)
  const [showDoubles, setShowDoubles] = useState(false)
  /* Venue clock or the reader's own — an ACCOUNT preference (users.schedule_tz)
     this screen READS and no longer offers. The switch sat in the filter strip,
     beside controls people change every visit, to set something they change
     once; it is on the Status tab with the other preferences now. Absent means
     my time: that is the question a schedule is usually being asked. */
  const { me } = useAuth()
  const isAdmin = !!me?.is_admin
  const tzMode = me?.schedule_tz === 'venue' ? 'venue' : 'user'
  const [h2h, setH2H] = useState(null)
  const [hist, setHist] = useState(null)
  const [predictors, setPredictors] = useState(null)
  const [viewChoice, setViewChoice] = useState('time')
  // The compact list: one match, one row (owner, 2026-09-17). Session-only, like the switches above.
  const [density, setDensity] = useState('cards')   // 'cards' | 'mid' | 'list' — the button cycles
  const compact = density === 'list'
  const dense = density !== 'cards'
  // The court being renamed by an admin: { tournament_id, court_key, current }, or null.
  const [renaming, setRenaming] = useState(null)
  const [renamingEvent, setRenamingEvent] = useState(null)
  const [menuFor, setMenuFor] = useState(null)

  /* WHICH TOURNAMENTS THE TAB CHOSE (scheduleFilter). A schedule row always
     carries a tournament_id — unlike draw_id, which is null for qualifying and
     doubles — so this needs nothing derived and nothing to go wrong. */
  const eventSel = useScheduleTournaments()
  /* WHAT THE PAGE'S OWN CHECKBOXES OFFER — the same derivation the tab bar's
     sheet uses, so the two controls list the same tournaments and either can
     undo the other. */
  const { all: allDraws, choosable: events } = useChoosableTournaments()
  /* PINNED TO ONE EVENT — arriving from a tournament the chooser does not
     offer.
   *
   * The chooser lists what is open or being played. Press Order of Play on a
   * finished event (or one that has not opened) and you land here with its
   * tournament in the URL and NOTHING on screen about it: the boxes name two
   * other tournaments, and the selection they hold decides what you see, so
   * the sheets you asked for are filtered by a control that cannot even name
   * them (owner, 2026-09-15).
   *
   * So that arrival pins the page to that one event: its rows only, and no
   * chooser, because there is nothing to choose between. The date list
   * follows `scope` below, so the arrows walk that event's days and no
   * others.
   *
   * READINESS IS THE DRAW LIST, NOT THE CHOOSABLE SET. The first version
   * waited for `events.length`, on the theory that an empty list meant the
   * answer was still in flight — but an empty list is also a RIGHT answer, and
   * a common one: nothing live in the off-season, or a week whose sheets are
   * not out yet. So the pin never engaged in the case it exists for, and the
   * page went on showing every tournament playing that day (three of them, on
   * 26 August in the dev snapshot). `all` is the draw list the choosable set
   * is derived FROM: non-empty means the question has been answered, whatever
   * the answer turned out to be. */
  const pinnedEvent = tournament != null && allDraws.length > 0
    && !events.some(e => e.id === tournament)
    ? tournament
    : null
  /* `null` in the store means EVERY tournament, so a box is ticked when there
     is no selection at all. Turning the last one off would empty the screen
     with nothing on it to explain why, so the whole set comes back instead —
     which is the same state, said the other way, and leaves every box ticked
     rather than every box blank. */
  /* TWO SCOPES (owner, 2026-09-17). The DAYS are every live tournament's:
     the strip's labels must not change as boxes are ticked — unticking
     Guadalajara turned "Q1 1 2 3 4 5" into "Q1 Q2 1 2 3". The ROWS are the
     ticked tournaments'; a day the ticked ones do not play says "No matches
     to show". A pin is both scopes at once; `null` while the draw list is
     in flight — not none, not yet known.

     "ALL" USED TO MEAN ALL ON RECORD. The store's null is "every tournament",
     and the date list once took that literally — fetched with no tournament
     at all, it held every date the sheets have ever named, and rows from a
     tournament the chooser could not even name came through a filter of
     null. All means the boxes on screen.

     Keyed on primitives so the arrays — and the Set built from them — keep
     their identity across renders; `events` is rebuilt every render, and a
     fresh Set each time would re-run every filter below. */
  const liveKey = events.map(t => t.id).join(',')
  const live = useMemo(() => (liveKey ? liveKey.split(',').map(Number) : []), [liveKey])
  const scope = useMemo(() => {
    if (pinnedEvent != null) return [pinnedEvent]
    return allDraws.length === 0 ? null : live
  }, [pinnedEvent, allDraws.length, live])
  const scopeKey = scope ? scope.join(',') : null
  const rowScope = useMemo(() => {
    if (pinnedEvent != null) return [pinnedEvent]
    if (allDraws.length === 0) return null
    const chosen = eventSel ? live.filter(id => eventSel.has(id)) : live
    // A stored selection naming nothing live is no selection — the store's
    // own rule: turning the last box off brings every box back.
    return chosen.length ? chosen : live
  }, [pinnedEvent, allDraws.length, live, eventSel])
  /* Rows are tested against a Set, never against null: while the scope is
     unknown nothing passes, so a slow draw list shows a page that fills
     rather than rows that vanish. */
  const eventFilter = useMemo(() => new Set(rowScope || []), [rowScope])
  /* THE DAYS ON OFFER ARE THE SCOPE'S DAYS. Nothing is fetched until the
     scope is known, and nothing is fetched for an empty one — an unscoped
     call answers with every date on record, which is the bug above. */
  const dates = useApi(scope?.length ? `schedule-dates:${scopeKey}` : null,
                       () => getScheduleDates(scope), { enabled: !!scope?.length })
  // Memoised on the answer: `|| []` is a fresh array per render otherwise,
  // and the swipe's step callback keys on it.
  const available = useMemo(() => dates.data?.dates || [], [dates.data])
  /* Q1, Q2, 1, 2 … for the strip: the sheet days before the first main-draw
     singles day, then the count from it. Memoised on the answer, not on
     `available`, which is a fresh array whenever there is no answer yet. */
  const days = useMemo(
    () => dayLabels(dates.data?.dates || [], dates.data?.main_start ?? null, today()),
    [dates.data],
  )
  /* A pinned day only counts while it EXISTS in the list this page is showing.
     The reset above is the cure for the stale day; this is the belt to its
     braces, and it also covers the moment after an arrival when the new date
     list is still in flight. */
  const date = (pinned && available.includes(pinned))
    ? pinned
    : landingDay(available, dates.data?.open_counts || {}, asked)
  /* A DAY BEFORE TODAY IS A RECORD, and a record has one shape. Every match
     on it is over, so there is nothing to filter by phase — and the court view
     is not offered either (owner, 2026-09-20): a finished day is read as a
     chronology of what happened, not as a map of which court it happened on.
     So the Time/Court switch is gone on a past day and the view is Time,
     whatever the reader last chose on a live one. */
  const past = date < today()
  const view = past ? 'time' : viewChoice
  /* SWIPE ANYWHERE TO CHANGE THE DAY. A sideways drag on the page — the
     cards, the empty space, the header — steps one day: left for the next,
     right for the one before, and the strip slides its chip to the centre
     to show it. The pan is axis-locked the way the draw page's scrub is (12pt
     sideways to activate, 8pt vertical to fail), so the list still scrolls
     and pulls to refresh. The strip is outside its subtree (see the JSX),
     so a drag that starts on the strip scrolls the strip and turns no page.
     The decision is made on release — distance or a flick — so a drag that
     comes back to where it started changes nothing. */
  const stepDay = useCallback((delta) => {
    const i = available.indexOf(date)
    const j = i + delta
    if (i >= 0 && j >= 0 && j < available.length) setPinned(available[j])
  }, [available, date])
  const dayPan = useMemo(() => Gesture.Pan()
    .activeOffsetX([-12, 12])
    .failOffsetY([-8, 8])
    /* A SWIPE IS NOT A TAP (swipeGuard): the release at the end of a swipe
       reached the Pressable under the finger as a press and opened the match
       history. From activation until a beat after the gesture settles, the
       page's tap handlers decline. */
    .onStart(() => {
      'worklet'
      scheduleOnRN(beginSwipe)
    })
    .onEnd((ev) => {
      'worklet'
      const delta = swipeStep(ev.translationX, ev.velocityX, SWIPE_PX, SWIPE_VX)
      if (delta) scheduleOnRN(stepDay, delta)
    })
    .onFinalize(() => {
      'worklet'
      scheduleOnRN(endSwipe)
    }), [stepDay])
  /* Every tap the page hands its rows, guarded — the history, the H2H, the
     predictors — so no swipe ever opens anything. */
  const openHist = useMemo(() => unlessSwiping(setHist), [])
  /* The headings' rename sheets go through the same guard as the rest: the
     release at the end of a day swipe lands on whatever is under the finger,
     and a tournament name is 361pt wide (owner, 2026-09-20 — the day changed
     AND the rename sheet opened). */
  const openRenameCourt = useMemo(() => unlessSwiping(setRenaming), [])
  const openRenameEvent = useMemo(() => unlessSwiping(setRenamingEvent), [])
  const openH2H = useMemo(() => unlessSwiping(setH2H), [])
  const openPredictors = useMemo(() => unlessSwiping(setPredictors), [])
  // A long press at the end of a swipe is still the swipe's (swipeGuard).
  const openMenu = useMemo(() => unlessSwiping(setMenuFor), [])
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
  /* ONE LINE, ONE SIZE (owner, 2026-09-21). The pills used to wrap onto a
     second row, which cost a row of the screen and moved the list down as the
     week changed. They now share a text size chosen to make the row fit the
     width it actually has — measured, not guessed, because RN cannot say
     whether a string fits until it has drawn it (measure.js).

     ONE size for all of them rather than each shrunk to its own box: a row
     where "Korea" is set larger than "Hangzhou" reads as a mistake, and these
     are a set of equals. */
  const [pillRoom, setPillRoom] = useState(null)
  const pillLabels = events.map(t => ({ name: t.short || t.name, tier: tierWord(t.categories) }))
  /* NOT MEMOISED, on purpose. `events` is rebuilt every render, so a
     dependency on it memoises nothing, and keying a memo on the words meant
     packing them into a string and parsing them back — which a tournament
     named with the separator in it would break. The solve is a reduce over at
     most a handful of pills, each a short walk through a name's characters, so
     it is cheaper than the bookkeeping.

     It also gives the behaviour for free: change a tournament's short name and
     the row re-solves its shared size on the next render, so a longer name
     shrinks the row to fit instead of overflowing it (owner, 2026-09-21). */
  const pillSize = fitPillSize(pillLabels, {
    avail: pillRoom, family: 'Archivo_700Bold', size: PILL_SIZE,
    tierRatio: PILL_TIER_RATIO, chrome: PILL_CHROME, gap: PILL_GAP, min: 6,
  })
  const toggleEvent = id => {
    const cur = new Set(eventSel ?? events.map(t => t.id))
    if (cur.has(id)) cur.delete(id)
    else cur.add(id)
    setScheduleTournaments(cur.size ? cur : null)
  }
  /* A GENDER BAR on the dense rows (owner, 2026-09-17), on EVERY row (owner,
     2026-09-20). A thin bar at the row's far left in its tour's colour, pink
     or blue, whether or not the day mixes the tours.

     It began as a disambiguator, drawn only where a Slam or a combined event
     put two tours in one list — and that was the narrower rule. The bar says
     what this match IS, and that does not depend on what else happens to be
     on the page; a WTA 250 on a WTA-only day is no less a WTA match. It is
     the same call as the court view's heading, which names its tournament
     even when only one is showing.

     A row with no tour of its own still gets no bar: there is nothing to
     say, and a grey stripe would say something false. */
  const tourBarOf = e => (e.tour ? (e.tour === 'WTA' ? TOUR_BAR.WTA : TOUR_BAR.ATP) : null)
  /* DOUBLES TO FILTER — among the rows the other filters keep, not among every
     row fetched. Filtering to a tournament with no doubles while another event
     on the same day has some left the switch on screen toggling nothing; so
     did a day whose only doubles were finished with Completed off. Same rule
     as the tour chips above, and the same reason: a chip that toggles nothing
     reads as broken.

     `showDoubles` is deliberately NOT part of this — a switch cannot be the
     test of whether to show itself — and nor is the PHASE: a day whose
     doubles are all finished still has doubles, and the switch has to be
     there to say so. */
  const hasDoubles = useMemo(() => all.some(e =>
    e.discipline !== 'singles' && rowInTournaments(e, eventFilter)
  ), [all, eventFilter])
  const venueMode = tzMode === 'venue'
  // The venue's zone for a row, from the day's tournament list.
  const venueTzOf = e => (day.data?.tournaments || []).find(t => t.id === e.tournament_id)?.venue_timezone || undefined
  /* THE SHORT NAME FOR THE BORDER TAG (owner, 2026-09-21). The day payload
     already carries one per tournament — the admin's, or a default taken off
     the name, and never empty — so this needs nothing new from the server.
     Falls back to the full name anyway: a tag with no name at all would be a
     worse answer than a long one. */
  const tournShortOf = e => (day.data?.tournaments || [])
    .find(t => t.id === e.tournament_id)?.short_name || e.tournament_name
  /* The tier stamp for a group's heading. A row carries only a tournament id,
     so the artwork's two fields come from the day payload's tournaments —
     where the OOP link and the venue zone already come from. */
  const stampsOf = rows => stampsFor(
    (day.data?.tournaments || []).find(t => t.id === rows?.[0]?.tournament_id)?.stamps)
  /* What the rename sheet needs about an event: its id, the name as it
     stands (which is already the admin's, if they set one), the short name,
     and the scraped name the override sits on top of. */
  /* THE SHORT NAME, WHERE THE FULL ONE WILL NOT GO. The heading is the first
     place to ask for it (owner, 2026-09-20: "a second box for the short
     version of a tournament's name which we will use in certain places
     moving forward") — with the pencil and the tier stamp on the same line,
     a sponsored name runs past the floor and the backstop starts clipping,
     and this project does not print "…". Uppercased to match the heading it
     may replace. */
  const shortNameOf = rows => {
    const id = rows?.[0]?.tournament_id
    const short = (day.data?.tournaments || []).find(x => x.id === id)?.short_name
    return short ? String(short).toUpperCase() : null
  }
  const eventNaming = (rows, shown) => {
    const id = rows?.[0]?.tournament_id
    const t = (day.data?.tournaments || []).find(x => x.id === id)
    return {
      tournament_id: id,
      current: shown,
      // The one in use: the admin's, or the server's default off the name.
      // The sheet shows it as real text — see rename.jsx.
      short: t?.short_name || '',
      scraped: t?.scraped_name || shown,
    }
  }
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
  /* EVERY RULE BUT THE PHASE. The phase switch counts its segments over this,
     so the numbers in its brackets stay put as the reader moves between them —
     counted over the filtered set they would each shrink to what that segment
     already shows. */
  const beforePhase = useMemo(() => {
    return all.filter(e => {
      if (view === 'time' && e.discipline !== 'singles' && !showDoubles) return false
      // THE TOURNAMENTS THE TAB ASKED ABOUT, in BOTH views: this is an answer
      // the reader gave on the way in and means the same thing either way.
      // (The tour filter that used to sit here went with its chips.)
      if (!rowInTournaments(e, eventFilter)) return false
      return true
    })
  }, [all, view, showDoubles, eventFilter])

  /* THE DAY'S THREE, AND WHICH ONE IS SHOWING. Offered only on a day that is
     still happening, and only in the time view — the court view reproduces the
     whole sheet by design, and a past day is all one phase. A segment with no
     matches is not offered at all, so a quiet morning shows two and a finished
     day shows none. */
  const counts = useMemo(() => phaseCounts(beforePhase), [beforePhase])
  const phaseTabs = useMemo(
    () => (past || view !== 'time' ? [] : PHASES.filter(x => counts[x.key] > 0)),
    [past, view, counts],
  )
  const shownPhase = phaseTabs.length ? effectivePhase(counts, phase) : null

  /* GROUPED BY TOURNAMENT AND ROUND, OR LEFT IN THE DAY'S ORDER.
     A reader looking at results or at matches in progress wants the
     bracket's shape — this event, this round — not the order the courts
     happened to free up. That is the argument that made a past day a
     record, and it holds for today's COMPLETED and LIVE segments too
     (owner, 2026-09-20).
     UPCOMING keeps the running order, because a match still to come is not
     a record and the reader there wants what is on next.
     So `past` stops meaning two things at once — the DAY is past, and the
     LIST is grouped — and everything that meant the second asks this. */
  const grouped = past || shownPhase === 'completed' || shownPhase === 'live'

  const visible = useMemo(
    () => (shownPhase ? beforePhase.filter(e => matchPhase(e) === shownPhase) : beforePhase),
    [beforePhase, shownPhase],
  )

  /* More than one tournament on the page: the mid view names each match's
     (time view, today).

     THE DAY'S ROWS, NOT THE SEGMENT'S (owner, 2026-09-20). Read off `visible`
     this collapsed whenever the Completed/Live/Upcoming switch left a segment
     holding one tournament: today's single upcoming match lost the name that
     the eight completed ones above it carried, on the same day and the same
     page. Whether the page mixes tournaments is a fact about the DAY, and it
     must not change as the reader moves between its segments. */
  const manyTournaments = useMemo(
    () => new Set(beforePhase.map(e => e.tournament_id)).size > 1, [beforePhase])

  const groups = useMemo(() => {
    // Court: one group per court, by tournament when more than one is showing
    // (owner, 2026-09-17) -- courtGroups.js, on its own suite.
    if (view === 'court') return courtGroups(visible)

    // Time: a chronology of the day, the site's rule exactly — see
    // byTimeOfDay in schedule.js (a row with no time at all goes last).
    const chrono = byTimeOfDay(visible)
    /* A PAST DAY IS A RECORD (owner, 2026-09-17): by tournament when more
       than one is showing, singles before doubles, then by round — the
       chronology kept inside each group. Today and the days ahead stay a
       running order. pastGroups.js, on its own suite. */
    if (grouped) {
      /* ALWAYS NAMED, even on a day only one tournament played (owner,
         2026-09-20, for the court view's headings — the same rule, and this
         is the same kind of heading). A heading names its section once; it is
         a per-ROW repeat that has to earn its place, which is what
         manyTournaments decides above. It also carries the event's tier
         stamp, which a day with one tournament should not go without. */
      const byTournament = true
      // "Singles" is said only when there is doubles on the page to tell it
      // from — Doubles off, or a day with none, is rounds alone (owner).
      const mixed = new Set(chrono.map(e => (e.discipline === 'singles' ? 'singles' : 'other'))).size > 1
      // A dual-gender day — a Slam, a combined event — groups by tour too:
      // tournament, then ATP / WTA, then round (owner, 2026-09-17).
      const byTour = new Set(chrono.map(e => e.tour).filter(Boolean)).size > 1
      return groupPastDay(chrono, { byTournament, byTour }).map(g => ({
        key: g.key,
        title: g.first ? g.tournament : null,
        // The round has a line to itself here, so it is spelled out —
        // "Final", not "F" (owner, 2026-09-20). rounds.js::longRound.
        sub: [byTour ? g.tour : null, mixed ? g.discipline : null,
          g.round ? longRound(g.round) : null].filter(Boolean).join(' · '),
        list: g.list,
      }))
    }
    /* Today, in the dense views: a match that has started sits above the
       ones that have not (owner, 2026-09-17); the cards keep the running
       order, where the clock is what each card leads with. */
    return [{ key: 'all', list: dense ? startedFirst(chrono) : chrono }]
  }, [visible, view, grouped, dense])

  const refetch = () => { day.refetch(); dates.refetch() }
  /* ON COURT HERE, not on court anywhere. It counted the whole day's rows, so
     a page pinned to a finished event announced three matches in progress at
     tournaments it was not showing. `visible` is the same set the rows below
     are drawn from, so the number and the list can never disagree. */
  const liveCount = visible.filter(isLive).length

  /* A champion is a whole-screen event, so the row reports up and the
     fanfare covers the screen from here — the site's ChampionFanfare. It
     lives as long as the row's own tier does. */
  const [champion, setChampion] = useState(null)
  useEffect(() => {
    if (!champion) return
    const t = setTimeout(() => setChampion(null), FX_MS.champion)
    return () => clearTimeout(t)
  }, [champion])
  const { width: screenW } = useWindowDimensions()

  return (
    <>
      <Screen onRefresh={refetch} touchAction="pan-y pinch-zoom">
        {/* THE DAYS, as chips; the chosen one's date is written out on the
            line below, where it has always been. */}
        {/* THE HEADER IS THE STRIP: the days on the left, the chosen day's
            date pinned at the far right with the court count under it. The
            arrows went with it — the chips and the swipe are the stepper
            now (owner, 2026-09-17). Rendered even with no days, so a day
            with no sheet still says which day it is. "Yday", "Today" and "Tmrw"
            when the day has a word, else month and day (owner): "Sep 15". */}
        <DayStrip
          days={days} active={date} onPick={setPinned}
          right={(
            <View style={s.today}>
              <Text style={s.todayDate}>{relativeDayWord(date, today()) ?? shortDate(date)}</Text>
              {liveCount > 0 && (
                <Text style={[T.tiny, { color: C.greenLit }]}>{liveCount} on court</Text>
              )}
            </View>
          )}
        />
        {/* THE SWIPE LIVES INSIDE THE SCROLL VIEW, BELOW THE STRIP. Above it —
            an ancestor of the ScrollView — the pan never fired on the phone:
            iOS hands a sideways drag to the scroll view's own recogniser
            before an ancestor RNGH handler can claim it. Inside, it is the
            arrangement RNGH's own Swipeable rows rely on in every list, and
            the strip is simply not in its subtree, so a drag on the strip
            scrolls the strip and turns no page. flexGrow fills the column,
            so the empty space under a short day swipes too. */}
        <GestureDetector gesture={dayPan} touchAction="pan-y">
        <View style={s.swipeBody} collapsable={false}>

        {fromDraw ? (
          <CardLink href={drawReady ? `/draw/${fromDraw}` : undefined} style={[s.back, !drawReady && s.arrowOff]}>
            <Ionicons name="chevron-back" size={14} color={C.greenLit} />
            <Text style={[T.smallMed, { color: C.greenLit }]}>
              {fromRow?.name ? `${fromRow.name} draw` : 'Draw'}
            </Text>
          </CardLink>
        ) : null}

        {/* THE CONTROLS, WIDEST SCOPE FIRST: the day, then Time-or-Court,
            then which tournaments, then the filters that thin the rows
            (owner, 2026-09-14). Each one narrows what the one above it
            selected, so reading down the screen is reading the query.

            FULL WIDTH, SHORTER. The height is what was excessive — a strip
            holding one word per side was as tall as a row of matches. The
            width is not: the switch spans the column so each half is a target
            you can hit without looking, which is the whole argument for a
            segmented control over two links (owner, 2026-09-14).

            The LABEL DROPS ITS LINE HEIGHT. T.smallMed carries leading(18)
            for 13pt text, and on iOS the extra leading lands ABOVE the
            glyphs, so it both padded the strip and pushed the caps off its
            centre. The row centres the text instead. */}
        {/* NOT ON A PAST DAY (owner, 2026-09-20): a finished day is read as a
            chronology, and a switch whose other half nobody wants is a control
            over nothing. */}
        {/* THE DENSITY BUTTON SITS BESIDE THE SWITCH (owner, 2026-09-20) —
            and stays a SEPARATE button: its own pill, its own gap, no shared
            frame. Both answer "how am I looking at this day?", which is why
            they belong on one line, but the switch chooses an arrangement
            and this chooses how much of each match to draw. It was at the
            far end of the filters row below, among controls that thin the
            rows rather than redraw them.

            The row survives a past day, where the switch does not: `marginLeft:
            auto` on the button keeps it at the same right edge with nothing
            to its left. */}
        <View style={s.viewRow}>
          {/* DOUBLES SITS WITH THE VIEW CONTROLS (owner, 2026-09-20), on the
              left of the switch: it decides WHAT the list holds, which is the
              same kind of question as how it is arranged, and it was the last
              thing left in a filters row of its own.

              "DBLS" rather than "Doubles" — beside a segmented control the
              word was wider than either of the switch's halves, and the
              scoreboard's own shorthand is what the rest of this screen
              already speaks. The spoken label stays the word. */}
          {view === 'time' && hasDoubles && (
            <Pressable onPress={() => setShowDoubles(v => !v)} style={[s.chip, showDoubles && s.chipOn]}
                       accessibilityRole="button" accessibilityLabel="Doubles"
                       accessibilityState={{ selected: showDoubles }}>
              <Text style={[s.chipText, showDoubles && { color: '#fff' }]}>DBLS</Text>
            </Pressable>
          )}
          {!past && (
          <View style={[s.tabs, s.tabsGrow]}>
            {['time', 'court'].map(v => (
              <Pressable key={v} onPress={() => setViewChoice(v)}
                         style={[s.tab, view === v && s.tabOn]}
                         accessibilityRole="button" accessibilityState={{ selected: view === v }}>
                <Text style={[s.tabText, view === v && s.tabTextOn]}>
                  {v === 'time' ? 'Time' : 'Court'}
                </Text>
              </Pressable>
            ))}
          </View>
          )}
          {/* THE LIST: one match, one row — time, round, the surnames with
              "vs" or "def.", the score. An icon rather than a word, so it
              reads as a view control rather than a filter.

              Three densities, one button (owner, 2026-09-17): cards, the
              card's two lines with hairlines between matches, one-line rows.
              The glyph says where you are. */}
          <Pressable onPress={() => setDensity(d => (d === 'cards' ? 'mid' : d === 'mid' ? 'list' : 'cards'))}
                     style={[s.chip, s.chipIcon, dense && s.chipOn]}
                     hitSlop={6} accessibilityRole="button" accessibilityLabel="Compact list"
                     accessibilityState={{ selected: dense }} accessibilityValue={{ text: density }}>
            <Ionicons name={density === 'list' ? 'list' : density === 'mid' ? 'reorder-three' : 'reorder-four'} size={19} color={dense ? '#fff' : C.muted} />
          </Pressable>
        </View>

        {/* THE TOURNAMENTS, ON THE PAGE. They were reachable only by pressing
            the Schedule tab a second time, which is a thing you have to be
            told; the filter that decides what the whole screen holds belongs
            where the screen is (owner, 2026-09-14).

            The SAME list the sheet offers — both read useChoosableTournaments
            — so the two controls cannot disagree, and either can undo the
            other. Hidden below two, where there is nothing to choose — and
            hidden entirely while the page is pinned to one event, where the
            boxes would name other tournaments and decide nothing. */}
        {pinnedEvent == null && events.length > 1 && (
          <View style={s.events}
                onLayout={e => setPillRoom(e.nativeEvent.layout.width)}>
            {events.map(t => {
              const on = !eventSel || eventSel.has(t.id)
              // GREYED WHEN IT HAS NOTHING ON THIS DAY (owner, 2026-09-17): the
              // days are every live tournament's, so a box can name an event
              // that is idle today. Still a box — ticking it is harmless.
              const playing = all.some(e => e.tournament_id === t.id)
              /* LIT IN ITS OWN TOUR'S COLOUR — blue ATP, pink WTA (owner,
                 2026-09-21) — the same pair the rows' gender bars use, so one
                 glance down the screen reads as one language. A combined week
                 belongs to neither tour and keeps the neutral green: blending
                 the two is a gradient decision on a small pill and there is no
                 such token to borrow (theme.js TOUR.X). */
              const tint = TOUR_BAR[eventTour(t.genders)]
              const tier = tierWord(t.categories)
              return (
                /* TAP TOGGLES, HOLD ISOLATES — AND HOLDING THE LONE ONE SHOWS
                   EVERYTHING (owner, 2026-09-21). Getting down to one
                   tournament used to mean tapping every other pill off: five
                   taps on a five-event day, one of them easy to miss. A hold
                   says "only this" in one gesture, and holding that same pill
                   again says "all of them", so the gesture is its own undo.
                   The rule is scheduleRows.holdSelection, on its own suite.
                   320ms matches the schedule rows' own hold, so the app asks
                   for a long press at one speed. */
                <Pressable key={t.id} onPress={() => toggleEvent(t.id)}
                           onLongPress={() => setScheduleTournaments(holdSelection(eventSel, t.id))}
                           delayLongPress={320}
                           accessibilityHint={on && eventSel?.size === 1
                             ? 'Hold to show every tournament'
                             : 'Hold to show only this tournament'}
                           style={[s.eventBox,
                                   on && (tint ? { backgroundColor: tint, borderColor: tint }
                                               : s.eventBoxOn),
                                   !playing && s.eventIdle]}
                           accessibilityRole="button"
                           accessibilityState={{ selected: on }}
                           accessibilityLabel={[t.name, tier, playing ? null : 'no matches this day']
                             .filter(Boolean).join(', ')}>
                  {/* THE TIER ABOVE THE NAME (owner, 2026-09-21), centred over
                      it: "250" says what the week is worth, which is the
                      second thing a reader wants after which tournament it
                      is. Drawn only when we know it — an empty line would
                      read as a number that failed to load. Quieter than the
                      name and never the thing you read first. */}
                  {tier ? (
                    <Text style={[s.eventTier, on ? s.eventTierOn : { color: C.faint },
                                  { fontSize: pillSize * PILL_TIER_RATIO }]}
                          numberOfLines={1} ellipsizeMode="clip">
                      {tier}
                    </Text>
                  ) : null}
                  {/* THE PILL IS THE STATE (owner, 2026-09-20): lit when the
                      event is showing, quiet when it is not. A tick inside a
                      box said the same thing twice and cost 22pt of the row
                      that the names needed — which is also why these say the
                      SHORT name. The full name stays the spoken label, so
                      nothing is lost to a screen reader. */}
                  <Text style={[s.eventName, on ? s.eventNameOn : { color: C.muted },
                                { fontSize: pillSize }]}
                        numberOfLines={1} ellipsizeMode="clip">
                    {t.short || t.name}
                  </Text>
                </Pressable>
              )
            })}
          </View>
        )}

        {/* THE ATP / WTA CHIPS ARE GONE (owner, 2026-09-21). They only ever
            appeared on a day that mixed the tours, and the tournament pills
            above now carry their tour in their colour — so the tours are
            already legible where the reader is choosing, and a second control
            saying the same thing in words was the redundant one. Filtering to
            a tour is filtering to its tournaments, which those pills do with
            more precision. The rows keep their gender bars. */}

        {/* ── WHAT IS DONE, WHAT IS ON, WHAT IS COMING ────────────────────
            Directly above the list and all the way across it (owner,
            2026-09-20), because it says what the list IS rather than trimming
            it — which is the difference between this and the chips above.

            Only segments with matches appear, each with its count, so a
            morning before play shows "Upcoming (28)" alone and needs no
            explaining. One segment left is no choice at all and draws
            nothing. */}
        {phaseTabs.length > 1 && (
          <View style={s.phases}>
            {phaseTabs.map(x => {
              const on = x.key === shownPhase
              return (
                <Pressable key={x.key} onPress={() => setPhase(x.key)}
                           style={[s.phase, on && s.phaseOn]}
                           accessibilityRole="button"
                           accessibilityState={{ selected: on }}
                           accessibilityLabel={`${x.label}, ${counts[x.key]} ${counts[x.key] === 1 ? 'match' : 'matches'}`}>
                  <Text style={[s.phaseText, on && s.phaseTextOn]} numberOfLines={1}
                        adjustsFontSizeToFit minimumFontScale={0.75}>
                    {x.label} <Text style={[s.phaseN, on && s.phaseNOn]}>({counts[x.key]})</Text>
                  </Text>
                </Pressable>
              )
            })}
          </View>
        )}

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
            {/* One line each (owner, 2026-09-17). The ticked tournaments have
                nothing on this day — the days are every live tournament's,
                so this is ordinary — or the switches hid what they have. */}
            <Title>{all.some(e => rowInTournaments(e, eventFilter)) ? 'All matches have been filtered out.' : 'No matches to show.'}</Title>
          </Card>
        )}

        {groups.map(({ key, court, title, sub, list }) => (
          <View key={key} style={[s.group, court && !title && s.courtGroup]}>
            {/* Tight on the round beneath it: the heading's own line box plus
                the group's gap read as a hole, so the gap is taken back. */}
            {title ? (
              <View style={[s.tournHeadRow, s.tournHead, (sub || court) && s.tournHeadTight]}>
                {/* The flex slot is what lets FitText measure the room there
                    IS rather than the room the name took — as the cards'
                    titleSlot (u.fitSlot). Without it the stamp is pushed off
                    the right edge by a long name instead of squeezing it. */}
                {/* ADMINS RENAME THE EVENT BY TAPPING ITS NAME (owner,
                    2026-09-20). The name is the button and looks exactly as
                    it did — no pencil, no second colour, no underline: an
                    affordance drawn for the one reader in a thousand who can
                    use it is furniture for everybody else. A reader who is
                    not an admin gets a plain View, so there is nothing to
                    press and nothing announced. */}
                <HeadTap style={s.tournHeadSlot} onPress={isAdmin ? () => openRenameEvent(eventNaming(list, title)) : undefined}
                         label={isAdmin ? `Rename ${title}` : undefined}>
                  <FitText style={(dense ? TOURN_SMALL : TOURN).style} track={(dense ? TOURN_SMALL : TOURN).track} min={9}
                           alt={shortNameOf(list)}>
                    {title.toUpperCase()}
                  </FitText>
                </HeadTap>
                <TournStamps stamps={stampsOf(list)} name={title} small={dense} />
              </View>
            ) : null}
            {/* Tight above and below (owner, 2026-09-17): the list's gap and the
                group's margin stacked to 20pt over the round, and the gap under
                it read as a hole before the card. */}
            {sub ? <Text style={[SUB.style, s.subHead, !title && s.subHeadFirst]}>{sub}</Text> : null}
            {/* A COURT NAME IS ONE LINE, WHATEVER ITS LENGTH — "Quadra Central
                Maria Esther Bueno" wrapped to two (owner, 2026-09-17). The same
                eyebrow, through the measuring fitter: shrunk as far as it must,
                never "…". Uppercased here so the measurement is of the string
                that is drawn. */}
            {/* ROOM FOR THE CLOCK ON THE CARD'S EDGE (owner, 2026-09-21: in
                Court view, "add a bit more space between the court name and
                the first match box, to accommodate for the time sitting in
                the border"). Asked of the FIRST row through miniTags, not
                guessed at from the view or the status: `when` is the thing
                that needs the room, so the room appears exactly when it does
                and nowhere else. A started match prints no clock and the head
                stays flush, which is the "upcoming only" the owner asked
                for. */}
            {court ? (
              <View style={[s.courtHead, title && s.courtHeadUnderName,
                            !!(list.length && miniTags(list[0], {
                              past: grouped, tournament: null, venueMode,
                              venueTz: venueTzOf(list[0]),
                            }).when) && s.courtHeadClock]}>
                {/* ADMINS RENAME A COURT BY TAPPING IT (owner, 2026-09-17 for
                    the sheet, 2026-09-20 for the tap): the name it sets is
                    the court's everywhere the schedule is served, and the
                    sheet's own name stays the key — carried on every row as
                    court_key. */}
                <HeadTap style={s.courtHeadSlot} onPress={isAdmin ? () => openRenameCourt({ tournament_id: list[0].tournament_id, court_key: list[0].court_key || court, current: court }) : undefined}
                         label={isAdmin ? `Rename ${court}` : undefined}>
                  <FitText style={(dense ? COURT_SMALL : COURT).style} track={(dense ? COURT_SMALL : COURT).track} min={9}>
                    {court.toUpperCase()}
                  </FitText>
                </HeadTap>
              </View>
            ) : null}
            {/* A ROW NAMES ITS TOURNAMENT ONLY WHERE NO HEADING DOES: once the
                list is grouped, the heading says it for the whole group, and
                repeating it on every row was the duplication that made
                today's segments read as a flat stream (owner, 2026-09-20). */}
            {density === 'mid'
              ? (
                <MiniRows list={list} tagsOf={e => miniTags(e, { past: grouped, tournament: !grouped && view !== 'court' && manyTournaments ? tournShortOf(e) : null, venueMode, venueTz: venueTzOf(e) })}>
                  {list.map((e, i) => <MatchMini key={e.id} e={e} first={i === 0} alt={i % 2 === 1} tourBar={tourBarOf(e)} past={grouped} tournament={!grouped && view !== 'court' && manyTournaments ? tournShortOf(e) : null} venueMode={venueMode} venueTz={venueTzOf(e)} onHistory={openHist} onH2H={openH2H} onPredictors={openPredictors} onMenu={openMenu} />)}
                </MiniRows>
              )
              : compact
              ? (
                <View style={s.rows}>
                  {list.map((e, i) => <MatchRow key={e.id} e={e} first={i === 0} alt={i % 2 === 1} tourBar={tourBarOf(e)} past={past} {...rowColumns(list, past, screenW - 2 * S.sm - 2 * 8 - 2)} venueMode={venueMode} venueTz={venueTzOf(e)} onHistory={openHist} />)}
                </View>
              )
              : list.map(e => <EntryRow venueMode={venueMode} venueTz={venueTzOf(e)} onH2H={openH2H} onHistory={openHist} onPredictors={openPredictors} onChampion={setChampion} key={e.id} e={e} inCourt={view === 'court'} />)}
          </View>
        ))}
      </View>
      </GestureDetector>
      </Screen>
      {champion && <ChampionFanfare key={champion} width={screenW} />}
      <CourtRenameSheet court={renaming} onClose={() => setRenaming(null)} />
      <TournamentRenameSheet event={renamingEvent} onClose={() => setRenamingEvent(null)} />
      <MatchMenu target={menuFor} onClose={() => setMenuFor(null)}
                 onH2H={setH2H} onPredictors={setPredictors} onHistory={setHist} />
      <H2HSheet visible={!!h2h} onClose={() => setH2H(null)} a={h2h?.a} b={h2h?.b} />
      {/* drawId comes off the ROW, not the page: the schedule mixes the men's
          and women's draws on one day, so there is no single draw to pass. */}
      <PredictorsSheet
        visible={!!predictors} onClose={() => setPredictors(null)}
        drawId={predictors?.draw_id} match={predictors} meId={me?.id} />
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
      if (showing) {
        await hideFromLockScreen(matchId)
        showToast('Removed from the Lock Screen')
      } else {
        await showMatchOnLockScreen(matchId)
        showToast('Now showing on the Lock Screen')
      }
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
               style={[s.h2hChip, s.lockChip, showing && s.lockChipOn, busy && { opacity: 0.6 }]}>
      <Text style={[s.h2hText, s.lockIcon]}>🔒</Text>
    </Pressable>
  )
}

/* THE COLUMNS OF A CARD (owner, 2026-09-17). One left-column width per
   card — every left name right-aligned into it, the verb after it on one x
   — chosen by nameColumns.js: no name under a readable floor where any
   width can manage it, and otherwise as few names shrunk, as little, as
   possible. To the right of the verb each name flows toward its own row's
   score, which keeps its natural width at the row's right edge (a name may
   sit above a longer score on the row below). Measured from font metrics,
   per card, on every render; the optimiser is exact and cheap. */
const NAME_FACE = 'Archivo_500Medium', NAME_SIZE = 13
const VERB_W = 32                                  // "def." at 12pt plus its padding
const FLAG_W = leading(17) + 6                     // FlagSlot plus its margins, per side
const GAPS = 5 + 6 + 4                             // the row's gap, the score's margin, slack
function rowColumns(list, past, innerW) {
  const lead = past ? 0 : 58 + 5 + 30 + 5              // today's clock and round (or the score in their place)
  const rows = list.map(e => {
    const { left, right, score } = matchLine(e)
    const flags = e.discipline === 'singles' ? 2 * FLAG_W : 2 * leading(17) + 12
    const scoreW = past && score ? Math.ceil(textWidth(score, 'Archivo_700Bold', 12) * 1.06) + 2 : 0
    return {
      a: textWidth(left, NAME_FACE, NAME_SIZE),
      b: textWidth(right, NAME_FACE, NAME_SIZE),
      room: innerW - lead - flags - VERB_W - scoreW - GAPS,
    }
  })
  return { leftW: bestLeftColumn(rows) + 1 }
}

/* THE MID DENSITY: the card's own two lines and box score, at 0.8, with a
   hairline between matches and no chrome — as many matches on a screen as
   the box score allows (owner, 2026-09-17). A started match opens its
   history on a tap, as the card does. */
/* A TAG ON THE LINE between matches (owner, 2026-09-17): cut into it by two
   half backgrounds - the row above's over the top half, this row's under the
   bottom - so the zebra stays honest on both sides. The first row's line is
   the card's own edge, which clips, so its tag sits inside. */
function LineTag({ first, alt, style, textStyle, children }) {
  return (
    <View style={[s.miniTag, style]} pointerEvents="none">
      <View style={[s.miniTagHalf, { top: 0, backgroundColor: first ? C.bg : alt ? C.card : C.raised }]} />
      <View style={[s.miniTagHalf, { bottom: 0, backgroundColor: alt ? C.raised : C.card }]} />
      <Text style={[s.rowWhen, textStyle]} numberOfLines={1}
            adjustsFontSizeToFit minimumFontScale={0.8}>{children}</Text>
    </View>
  )
}

/* THE THREE TAGS ON ONE LINE, and EVERY ROUND ON ONE VERTICAL (owner,
   2026-09-20).

   The round sits at the STRIP'S OWN CENTRE, not in the middle of whatever gap
   its neighbours leave. Centring it in the gap was the first cut and it read
   badly for the reason the owner pointed out: the gap's middle moves with the
   tournament name, so Korea Open's R32 and Singapore Open's R32 landed at
   different x on consecutive cards and the column zig-zagged down the page.
   A round is a label on a column; it has to hold still.

   The geometry is three cells: the clock's side, the round, the tournament's
   side, with the two SIDES flexed equally. Two equal siblings around an
   auto-width middle put that middle on the strip's centre line whatever the
   sides contain — so every round in the card aligns, with no measuring and
   nothing to keep in sync.

   It is also why a long tournament name cannot reach the round. The name is
   confined to its own cell, which ends where the round's begins; it shrinks
   inside it rather than growing across. Overlap is not something to avoid
   here, it is unrepresentable.

   MEASURED, not assumed (2026-09-20). The owner asked whether a one- or
   two-digit hour shifts it, which it did under the gap-centred version. Every
   round label on the page now reports the same centre — x=187.5 on a 393pt
   screen, which is the strip's own middle between 10 and 365 — across rows
   clocked "8:00 p.m.", "10:00 p.m." and "12:00 a.m.", across cards headed
   "Korea Open" and "Singapore Open", and across rows with no clock at all.
   One distinct centre in every case, because nothing on either side can reach
   the middle cell. */
/* A HEADING THAT AN ADMIN CAN TAP, and that nobody else can.
 *
 * `onPress` undefined gives a plain View: no press, no button role, nothing
 * announced to a screen reader — the heading is exactly what it was. With a
 * handler it is a Pressable of the same shape, so the layout and the type are
 * untouched either way. The hit slop is the only concession: a heading's line
 * box is around 20pt tall and a tap wants 44 (theme.js TOUCH).
 *
 * The style must keep the fitting slot's flex, or FitText measures the room
 * the TEXT took rather than the room there is — see cards.jsx u.fitSlot.
 */
function HeadTap({ style, onPress, label, children }) {
  if (!onPress) return <View style={style}>{children}</View>
  return (
    <Pressable style={style} onPress={onPress} hitSlop={{ top: 10, bottom: 10, left: 4, right: 12 }}
               accessibilityRole="button" accessibilityLabel={label}>
      {children}
    </Pressable>
  )
}

/* THE EVENT'S TIER STAMP, hard right on the row that names the tournament
   (owner, 2026-09-20) — the same artwork, plate and sizing the dashboard's
   cards carry, so the two surfaces name a tournament the same way. `small`
   follows the heading's own size, exactly as it follows the card's.

   Its own row: the gap between two stamps of a combined week is theirs, not
   the wider gap between the name and them. */
function TournStamps({ stamps, name, small }) {
  if (!stamps?.length) return null
  return (
    <View style={s.tournHeadStamps}>
      {stamps.map(d => (
        <TierBadge key={d.draw_id} tour={d.gender === 'F' ? 'WTA' : 'ATP'}
                   tier={d.category} name={name} small={small} />
      ))}
    </View>
  )
}

/* THE CLOCK AND THE TOURNAMENT, on the card's own top border.
   THE ROUND IS NOT HERE ANY MORE (owner, 2026-09-21): it sits in a pill at the
   top right INSIDE the box, where it labels the match it belongs to instead of
   floating on the rule between two of them. The two flexed sides stay — they
   used to exist to centre the round between them, and now simply pin the clock
   left and the tournament right. */
function LineTags({ first, alt, when, tournament }) {
  if (!when && !tournament) return null
  return (
    <View style={s.miniTagRow} pointerEvents="none">
      <View style={s.miniTagSide}>
        {when ? <LineTag first={first} alt={alt} textStyle={s.miniTagWhen}>{when}</LineTag> : null}
      </View>
      <View style={[s.miniTagSide, s.miniTagSideRight]}>
        {tournament ? (
          <LineTag first={first} alt={alt} textStyle={s.miniTagTourn}>{tournament}</LineTag>
        ) : null}
      </View>
    </View>
  )
}


/* The H2H pair a row can open — singles, both players known to Tennis
   Explorer — in the shape the H2H sheet takes. */
function h2hPairOf(e) {
  const a = (e.players || []).find(p => p.side === 'a'), b = (e.players || []).find(p => p.side === 'b')
  return e.discipline === 'singles' && a?.te_slug && b?.te_slug
    ? { a: { name: a.entry_name || a.name, te_slug: a.te_slug }, b: { name: b.entry_name || b.name, te_slug: b.te_slug } }
    : null
}

/* A CELL'S TWO SIDE BARS (owner, 2026-09-17): on the far left the group —
   who called it, the draw page's own icon — and on the far right "H2H",
   set on its side, each a full-height bar the thumb can find without
   aiming. The bars keep their width on every row so the cells line up; a
   row with nothing to open there (doubles has no H2H, a match with no
   bracket match has no picks) leaves the bar empty. */
/* What a cell's tags say: the clock for an upcoming match (a past day is a
   record: none), the ROUND, and the tournament when the page mixes them.
   
   The round only on a day still to come (owner, 2026-09-20). A past day is
   grouped BY round already — the heading above the cards says it, and saying
   it twice on every card would be noise. */
function miniTags(e, { past, tournament, venueMode, venueTz }) {
  return {
    when: past || hasStarted(e) ? '' : rowWhen(e, venueMode ? venueTz : undefined, venueMode),
    round: past ? '' : matchLine(e).round,
    tournament,
  }
}

/* THE FIRST ROW'S TAGS SIT ON THE CARD'S OWN EDGE (owner, 2026-09-17: "the top
   border should be lower down, matching the rest"). The card clips its
   corners, so a tag straddling its top border cannot live inside it: this
   wrapper draws the first row's tags over the card's edge from outside, and
   the first row keeps the same padding as every other. */
function MiniRows({ list, tagsOf, children }) {
  const tags = list.length ? tagsOf(list[0]) : { when: '', round: '', tournament: null }
  return (
    <View style={s.miniWrap}>
      <LineTags first when={tags.when} tournament={tags.tournament} />
      <View style={[s.rows, s.rowsInWrap]}>{children}</View>
    </View>
  )
}

function MatchMini({ e, first, alt, tourBar, past, tournament, venueMode, venueTz, onHistory, onH2H, onPredictors, onMenu }) {
  const openable = onHistory && ['live', 'completed', 'postponed', 'to_be_completed'].includes(e.status)
  const pair = onH2H ? h2hPairOf(e) : null
  const picks = onPredictors && e.match_id != null
  /* HELD, NOT WORN (owner, 2026-09-20): what this match can open used to be
     a 24pt column of buttons down the right of every row. The row is a thing
     to read; the actions are a thing to ask for. matchMenu.jsx.

     The gesture is armed only when there is something in the menu, so a row
     with no head-to-head, no picks and nothing played does not answer a long
     press with an empty sheet. */
  const menu = onMenu && actionsFor({ pair, picks, openable, finished: e.winner_side != null }).length
    ? () => onMenu({ e, pair, picks, openable, match: matchFromEntry(e) })
    : null
  const Wrap = openable || menu ? Pressable : View
  /* THE START TIME ON THE TOP BORDER, towards the left (owner, 2026-09-17),
     for an upcoming match; a past day is a record: no clock. THE TOURNAMENT
     on the same line, far right, when the page mixes tournaments (owner,
     2026-09-17) - the past day groups by tournament instead, the court view
     heads each tournament's courts. */
  const { when, round } = miniTags(e, { past, tournament, venueMode, venueTz })
  const tagged = Boolean(when || round || tournament)
  return (
    <Wrap style={[s.miniRow, !first && s.miniNext, alt && s.rowAlt]} onPress={openable ? () => onHistory(e) : undefined}
          onLongPress={menu || undefined} delayLongPress={320}
          accessibilityRole={openable || menu ? 'button' : undefined}
          accessibilityHint={menu ? 'Hold for head to head and predictions' : undefined}
          /* The tag is shortened; the SPOKEN name is not. "SaoPaolo" is a tag
             for a reader with 60pt of border to spend, not a name to read out
             (owner's rule on the predictors sheet, applied here). */
          accessibilityLabel={tagged ? [when, round, matchLine(e).names,
                                        tournament ? e.tournament_name : null]
            .filter(Boolean).join(' ') : undefined}>
      {tourBar ? <View style={[s.rowBar, { backgroundColor: tourBar }]} /> : null}
      {/* The first row's tags are drawn by MiniRows, over the card's edge. */}
      {!first ? <LineTags alt={alt} when={when} tournament={tournament} /> : null}
      {/* THE ROUND TRAVELS WITH THE CARD, not beside it: MatchCard puts it on
          the top player's line, after that player's entry chip, so the two
          chips are laid out by one row and cannot drift apart (owner,
          2026-09-21). */}
      {/* THE INDENT IS THE CLOCK'S, so it is spent only where there is a clock
          (owner, 2026-09-21: "Only so the indenting on upcoming / scheduled
          matches! NOT completed matches"). `when` is already blank the moment
          a match starts — see miniTags — so a completed or live row keeps the
          left edge it always had and gives the 62pt back to its names, which
          are the rows most likely to be carrying a score as well. */}
      <View style={[s.miniCard, when && s.miniCardWaiting]}>
        <MatchCard e={e} scale={0.8} round={round}
                   badges={!(past && e.discipline !== 'singles' && !(e.players || []).some(p => p.seed || p.draw_rank != null))} />
      </View>
    </Wrap>
  )
}

/* ONE MATCH, ONE ROW — the compact list. The clock the card would print
   (footTime, shortened: "Started at 8:30 AM" is "8:30 AM" here, "Not before"
   is "NB"), the round, the surnames with "vs" or "def.", the sets on one
   line. The names shrink to stay on the row rather than ellipsise — the
   app's rule for names — and a started match opens its history on a tap,
   as the card does. */
function MatchRow({ e, first, alt, tourBar, past, leftW, venueMode, venueTz, onHistory }) {
  const { round, names, left, right, verb, leftSide, score, decided } = matchLine(e)
  // Singles: each player's flag beside the verb (owner, 2026-09-17); doubles has four and no room.
  const singles = e.discipline === 'singles'
  const live = isLive(e)
  // rowClock, not footTime: the card goes quiet once a match is on or over;
  // this column cannot.
  const clock = rowClock(e, venueMode ? venueTz : undefined, venueMode)
  // JUST THE CLOCK (owner, 2026-09-17): the ladder's phrases — "Started at",
  // "Resumed at", "Not before" — are the card's, and so is the "~" of an
  // estimate; this column keeps the time and nothing else. The estimate is
  // still said, in the accessibility label.
  // UPCOMING MATCHES ONLY (owner, 2026-09-17): once a match is on court or
  // over, the clock slot goes quiet even when there is no score to lead with.
  const when = hasStarted(e) ? '' : rowWhen(e, venueMode ? venueTz : undefined, venueMode)
  const openable = onHistory && ['live', 'completed', 'postponed', 'to_be_completed'].includes(e.status)
  const Wrap = openable ? Pressable : View
  return (
    <Wrap style={[s.row, !first && s.rowNext, alt && s.rowAlt]} onPress={openable ? () => onHistory(e) : undefined}
          accessibilityRole={openable ? 'button' : undefined}
          accessibilityLabel={`${clock.estimated ? 'about ' : ''}${when}${clock.displaced ? ` (${clock.displaced})` : ''} ${round} ${names} ${score}`.trim()}>
      {tourBar ? <View style={[s.rowBar, { backgroundColor: tourBar }]} /> : null}
      {/* Measured fitting (FitText), never "…": the names shrink to the room
          the score leaves them, and the clock to its column. */}
      {/* A PAST DAY IS A RECORD: the round is the group's heading and the
          clock is history, so neither takes a column (owner, 2026-09-17). */}
      {/* TODAY, ONCE A MATCH HAS A SCORE (live or over), the score takes the
          clock's and the round's columns (owner, 2026-09-17): the row's first
          thing is the thing that changes. Still to play: clock and round. */}
      {!past && score ? (
        <View style={s.rowLeadSlot}><FitText style={[s.rowScore, s.rowScoreLead, live && s.rowScoreLive]} min={9}>{score}</FitText></View>
      ) : !past ? (
        <>
          <View style={s.rowWhenSlot}><FitText style={s.rowWhen} min={9}>{when}</FitText></View>
          <View style={s.rowRoundSlot}><FitText style={s.rowRound} min={8}>{round}</FitText></View>
        </>
      ) : null}
      {/* THE PLAYERS' FIELD (owner, 2026-09-17): each name centred in its own
          half, "def." or "vs" between them; the score on a line of its own
          beneath, left, in the light green. */}
      <View style={s.rowPlayers}>
        <View style={s.rowNamesLine}>
          {/* Both names hug the verb (owner, 2026-09-17): the first flush right
              against it, the second flush left — the halves stay equal, so the
              verb stays at the field's centre. */}
          <View style={[s.rowLeft, leftW ? { width: leftW } : null]}>
            <FitText style={[s.rowNames, decided && s.rowNamesDone]} min={10} align="right" wrapAtFloor>{left}</FitText>
          </View>
          {/* The flag slots stay even without a flag, so the verb sits on
              one x down a card that mixes singles and doubles. */}
          <View style={s.rowFlag}>{singles ? <FlagSlot codes={sideFlags(e.players, leftSide)} /> : <View style={s.rowFlagSpace} />}</View>
          <Text style={s.rowVerb}>{verb}</Text>
          <View style={s.rowFlag}>{singles ? <FlagSlot codes={sideFlags(e.players, leftSide === 'a' ? 'b' : 'a')} /> : <View style={s.rowFlagSpace} />}</View>
          <FitText style={[s.rowNames, decided && s.rowNamesDone]} min={10} wrapAtFloor>{right}</FitText>
        </View>
      </View>
      {/* A past day: the score on the names' own line, at the row's right
          (owner, 2026-09-17) — the columns it would have shared the row with
          are gone there, so the width is spare. */}
      {past && !!score && <Text style={[s.rowScore, s.rowScoreRight, live && s.rowScoreLive]} numberOfLines={1}>{score}</Text>}
    </Wrap>
  )
}

function EntryRow({ e, venueMode, venueTz, onH2H, onHistory, onPredictors, onChampion, inCourt }) {
  /* The biggest thing that just happened to this match, or null — the
     site's escalating tiers, marking the CARD rather than a digit: a set
     belongs to the match. The arrival argument covers a result already in
     by the time this row first rendered, which is the normal phone case. */
  const marks = scoreMarks(e)
  const fx = useScoreEvent(marks, arrivalTier(e, marks))
  useEffect(() => {
    if (fx === 'champion') onChampion?.(e.id)
  }, [fx, e.id, onChampion])
  const live = isLive(e)
  const suspended = isSuspended(e)
  const done = e.status === 'completed'
  const a = (e.players || []).find(p => p.side === 'a'), b = (e.players || []).find(p => p.side === 'b')
  const h2hPair = e.discipline === 'singles' && a?.te_slug && b?.te_slug
    ? { a: { name: a.entry_name || a.name, te_slug: a.te_slug }, b: { name: b.entry_name || b.name, te_slug: b.te_slug } }
    : null
  const postponed = e.status === 'postponed'
  const carried = e.status === 'to_be_completed'
  /* The site's bottom-left line, through its own rule — see footTime, which is
     pages/Schedule.jsx's expression ported whole. It reads differently by
     status and by view, and every one of those readings is deliberate there:
     "Started at 8:30 AM" once a match is on court, the sheet's wording in
     court view, the clock in time view. */
  const when = footTime(e, venueMode ? venueTz : undefined, venueMode, inCourt)

  /* A started match answers a tap with its history — the same sheet, slider
     and card the draw page opens, because the two surfaces describe the same
     match. Scheduled rows stay inert: nothing to show, and a dead tap reading
     as a broken page is the draw page's own documented lesson. */
  const openable = onHistory && ['live', 'completed', 'postponed', 'to_be_completed'].includes(e.status)
  const Wrap = openable ? Pressable : View
  return (
    <View style={s.edge}>
    <TierFx fx={fx} radius={14}>
    <Wrap style={[s.entry, live && s.entryLive]} onPress={openable ? () => onHistory(e) : undefined}>
      <View style={s.entryTop}>
        {/* The tour, named. A combined day lists the men's and women's US Open
            as the same "US Open · R128" and nothing else separated them. */}
        <TourBadge gender={e.gender} tour={e.tour} discipline={e.discipline} />
        <Text style={[T.tiny, { color: C.faint, flex: 1 }]} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.7}>
          {[e.tournament_name, e.round_label, e.discipline !== 'singles' ? 'Doubles' : null]
            .filter(Boolean).join(' · ')}
        </Text>
        <Text style={[T.tiny, {
          // The site's badge colours: amber for play that stopped, blue for a
          // match carried to a later day, green for one on court.
          color: suspended || postponed ? C.warn : carried ? C.info
            : live ? C.greenLit : done ? C.faint : C.muted,
        }]}>
          {whenLabel(e)}
        </Text>
      </View>

      <MatchCard e={e} />

      {/* Court on its own line, the time UNDER it — the site's own stacking.
          They shared a line while the time was a bare clock; the site's phrase
          ("Not before 11:00 AM", "Followed by ~6:00 PM") is too long to sit
          after a stadium name without shrinking both to nothing.

          The site's split, exactly: STATUS top-right (and nothing there at all
          until a match has started), the TIME bottom-left. */}
      {((!inCourt && e.court) || when.text || h2hPair || e.match_id != null) && (
        <View style={s.footLine}>
          <View style={{ flex: 1 }}>
            {/* Grouped under its court already, a row need not repeat it. */}
            {!inCourt && e.court ? (
              <Text style={s.footCourt} numberOfLines={1}
                    adjustsFontSizeToFit minimumFontScale={0.7}>{e.court}</Text>
            ) : null}
            {when.text ? (
              /* The time carries the card, so it is the bright line: the site
                 sets it a size up and bold against a muted court, and this is
                 the same reading in the app's palette. An ESTIMATE stays faded
                 and italic, exactly as the site fades a chained guess — it must
                 never read with the authority of a printed time. */
              /* Faded and italic when the time is a GUESS of ours rather than
                 one the tournament printed — it must never read with the same
                 authority. The tilde says so too; this says it twice, quietly. */
              <Text style={[s.footTime, when.estimated && s.footTimeEst]} numberOfLines={1}
                    adjustsFontSizeToFit minimumFontScale={0.7}
                    accessibilityLabel={when.displaced
                      ? `${when.text}, ${when.displaced}` : undefined}>{when.text}</Text>
            ) : null}
          </View>
          {e.match_id != null && (live || done) && (
            <LockPill matchId={e.match_id} live={live} />
          )}
          {/* WHO CALLED IT — the draw page's own affordance, in the draw
              page's own icon, so one feature is not two shapes. Only where
              there is a bracket match to have picks on: doubles and qualifying
              carry none. */}
          {e.match_id != null && (
            <Pressable onPress={() => onPredictors(matchFromEntry(e))} hitSlop={8}
                       style={[s.h2hChip, s.iconChip]}
                       accessibilityLabel={e.winner_side != null
                         ? 'Who called it' : 'Who’s still in it'}>
              {/* Sized and coloured to sit level with "H2H" beside it: same green,
                  and big enough to read as a peer of that word rather than a
                  faint mark in a box. */}
              <Ionicons name="people" size={16} color={C.greenLit} />
            </Pressable>
          )}
          {h2hPair && (
            <Pressable onPress={() => onH2H(h2hPair)} hitSlop={8} style={s.h2hChip}>
              <Text style={s.h2hText}>H2H</Text>
            </Pressable>
          )}
        </View>
      )}
    </Wrap>
    </TierFx>
    </View>
  )
}

/* The strip's slot: month and day only — "Sep 15" (owner, 2026-09-17). The
   chip already says which day of the event it is, and the weekday was the
   width that pushed a Slam's chips off the bar. */
function shortDate(iso) {
  const d = new Date(iso + 'T12:00:00Z')
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

// The court header's type: the eyebrow, for the fitter — and the small
// eyebrow (15 against 21, 30% down) over the compact list (owner, 2026-09-17).
const COURT = eyebrowType()
const COURT_SMALL = eyebrowType({ small: true })
// A past day's sub-heading — "Singles · R16" — the small eyebrow, fainter.
const SUB = eyebrowType({ small: true, color: C.faint })
// A past day's tournament heading: a size up on the court's, in the brand's
// clay so it reads as the section and not another court (owner, 2026-09-17).
const TOURN = eyebrowType({ size: 23, color: C.clayLight })
const TOURN_SMALL = eyebrowType({ size: 18, color: C.clayLight })

/* THE TOUR PAIR, used in the two places this screen names a tour by colour:
   every row's gender bar, and the tournament pills (owner, 2026-09-21). One
   pair, so a pink pill and the pink bars beneath it are the same pink. It
   outlived the ATP/WTA chips it was written for. */
const TOUR_BAR = { ATP: '#2563eb', WTA: '#db2777' }

/* THE TOURNAMENT PILLS' GEOMETRY, in one place. fitPillSize solves for a text
   size using these numbers, and the stylesheet draws with them — so they are
   constants rather than two copies that can drift by a point and overflow the
   row the solver promised would fit.
   PILL_CHROME is the horizontal padding AND the border, both sides. */
/* THE CLOCK'S OWN COLUMN on the mini view's border strip (owner, 2026-09-21:
   "Both player rows need to be indented so the times are on the far left on
   their own"). The clock STAYS on the top border — the owner's call when asked
   — and both player rows indent past it, so it stands alone at the left
   instead of sitting directly over the first seed badge.

   MEASURED, not eyeballed. The strip starts at left:10, a LineTag pads 4
   either side, and s.rowWhen is Archivo 500 at 11pt, so:

       "11:30"     ends at 46.1pt      "11:30 PM"  ends at 65.0pt
       "12:00"     ends at 46.4pt      "12:00 AM"  ends at 65.6pt

   IT CLEARS THE TIME, NOT THE MERIDIEM (owner, 2026-09-21: "don't indent it
   so much"). 70 cleared the whole tag with 4pt to spare and read as a gutter.
   The rule instead is to clear the DIGITS — the part that IS the time — and
   let the smaller "AM"/"PM" sit above the badge's left edge.

   48 obeyed that rule to the letter and still read tight, because it left the
   badge 1.6pt past "12:00": a hairline, not a gap. 54 is the digits' end
   rounded up plus S.sm, the same 8pt the rest of this screen puts between two
   things that are not part of each other — "a tiny bit" more (owner), and
   still 11pt short of the meridiem, so the rule holds.

   Nothing can collide either way: a tag is drawn at top:-9 and is 16 tall, so
   it straddles the border inside the row's 6pt of top padding and never
   reaches the player lines. That is also why the ladder's long forms ("NB
   3:30 PM") need no allowance of their own. */
const MINI_CLOCK_COL = 54

const PILL_SIZE = 13          // the size a roomy row keeps; never exceeded
const PILL_TIER_RATIO = 0.8   // the tier line, relative to the name
/* NO AIR EITHER SIDE (owner, 2026-09-21: "show text edge to edge of each box -
   no margin"). It was 14, which spent 150pt of a 358pt row on padding and
   forced the names down until they truncated. The box is now exactly as wide
   as the wider of its two lines. */
const PILL_PAD = 0
const PILL_GAP = 6
const PILL_CHROME = PILL_PAD * 2 + 2   // + the 1pt border either side

const s = StyleSheet.create({
  /* FAR LESS AIR AROUND A COURT NAME (owner, 2026-09-17): the group's
     margin above it is given back and then some, and the gap beneath it is
     taken back to half — the name sits on its card, not between two holes. */
  /* THE COURT NAME BELONGS TO THE HEADING, NOT TO THE CARD (owner,
     2026-09-20). It sat 4pt under the tournament name and 4pt above the
     first match, which put it exactly between the two and left it reading as
     the card's label. Now it is tight under the name it qualifies and the
     card is 12pt clear of it — measured, not eyeballed: 4/4 became 0/12. */
  courtHead: {
    flexDirection: 'row', alignItems: 'center', gap: S.sm,
    /* FLUSH TO THE CARD BENEATH IT, the same -S.sm a past day's round line
       carries (subHead): the court is the heading's last line and the matches
       start immediately under it. It sat +S.xs, which put 12pt of hole there
       against the round's 0 (owner, 2026-09-20). */
    marginTop: -S.xs, marginBottom: -S.sm,
  },
  /* A LITTLE ROOM FOR THE CLOCK, not a gap (owner, 2026-09-21: "You made the
     space to big. I said just a little bit"). A border tag is drawn at top:-9
     and is 16 tall, so 9pt of it stands above the card's edge, into the -S.sm
     this head pulls the card up by. Clearing all 9 of that — -8 to +4 — was
     the first try and read as a hole.

     ONE S.xs STEP instead: -8 to -4. The tag no longer sits on the court
     name, it sits in the slack under it — the name is uppercase through an
     eyebrow face, so the descender space below its caps is empty and is
     exactly what the tag's last few points can use. */
  courtHeadClock: { marginBottom: -S.xs },
  /* UNDER A TOURNAMENT'S NAME the court is that name's second line, and the
     row above has already pulled 10pt up for it (tournHeadTight) — so this
     drops its own pull, or the two would stack to -14 and run the lines
     together. The measured result is the past day's exactly: -5.5pt between
     the boxes, 3pt between the ink.

     A court with no name above it — the second court of the same event —
     keeps courtHead's own spacing, which is the block it has always had. */
  courtHeadUnderName: { marginTop: 0 },
  /* A COURT GROUP RIDES CLOSER TO THE ONE ABOVE IT — but only when it opens
     with a court name. A group that opens with a TOURNAMENT name is the start
     of a new event and takes the full gap, which is what makes the air above
     a name identical on both pages: 44.5pt from the card above it, where this
     pull had left today's at 32.5 (owner, 2026-09-20). The whole difference
     was this one line: -4 here against the group's own +8. */
  courtGroup: { marginTop: -S.xs },
  /* AIR BEFORE A TOURNAMENT (owner, 2026-09-20): 17pt from the controls
     above it was not enough to read as a new section. Only where a name is
     actually drawn — a second court of the same event carries no title, so
     its group stays tight against the first. */
  tournHead: { marginTop: S.sm, marginBottom: -(S.sm - 2) },
  /* THE NAME SITS DOWN ON ITS SECOND LINE (owner, 2026-09-20) — the round on
     a past day, the court on today's, whichever follows it. That line is the
     name's second line, not a label of its own, and 4.5pt of box gap reads
     as more than that on the phone: iOS puts a line's whole leading ABOVE
     its glyphs (feedback_ios_lineheight_sinks_caps), so the small eyebrow's
     6pt of leading all landed between the two.

     Ten points come out of the gap below: measured on one heading, 13pt of
     white between the two lines' ink became 3pt, which is the leading of a
     single block rather than a gap between two.

     The margin ABOVE is the section break, and it is deliberately modest
     (owner, 2026-09-20: reduce it, first name included). 8pt here plus the
     group's own 8 and the column's 12 comes to 30.5 between one tournament
     and the next — half again the 20 that separates two groups of the SAME
     event, which is what makes a new name read as a new section without
     leaving a hole.

     The fixed points are safe under Dynamic Type: both line boxes grow with
     the text while these do not, so the gap can only open up from here,
     never close. And the upper line is uppercase — no descenders to meet the
     lower line's caps.

     Only where a round follows: the court view's heading is already tight
     against the court name, and pulling this one further would run the two
     together. */
  tournHeadTight: { marginTop: S.sm, marginBottom: -(S.sm - 2) - 10 },
  // The name and the event's stamp share the line, the stamp hard right.
  tournHeadRow: { flexDirection: 'row', alignItems: 'center', gap: S.sm },
  // As the cards' titleSlot (u.fitSlot): the flex is what makes onLayout
  // report the room the name MAY use, so a long name shrinks to fit beside
  // the stamp instead of pushing it off the edge.
  tournHeadSlot: { flex: 1, minWidth: 0, flexDirection: 'row', alignItems: 'center' },
  // The court's name fills its row the same way, so tapping anywhere along
  // the line opens the sheet rather than only the glyphs themselves.
  courtHeadSlot: { flex: 1, minWidth: 0, flexDirection: 'row', alignItems: 'center' },
  tournHeadStamps: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  subHead: { marginBottom: -S.sm },                // flush to the card beneath; the line box's own descent is the air (owner, 2026-09-17)
  subHeadFirst: { marginTop: -(S.sm + 2) },        // 10pt from the card above, not 20
  // The scroll body's own gap and growth, restated: the wrapper took its children.
  swipeBody: { flexGrow: 1, gap: S.md },
  arrowOff: { opacity: 0.3 },
  /* The date in the strip's right slot: bold, no lineHeight (the slot
     centres it; lineHeight sinks caps on iOS), the count tucked under. */
  today: { alignItems: 'flex-end' },
  todayDate: { fontFamily: 'Archivo_700Bold', fontSize: 14, color: C.ink },

  back: { flexDirection: 'row', alignItems: 'center', gap: 2, alignSelf: 'flex-start', paddingVertical: 4 },
  chip: { borderRadius: R.pill, borderWidth: 1, borderColor: C.border, backgroundColor: C.card, paddingHorizontal: 10, paddingVertical: 5 },
  chipOn: { backgroundColor: C.green, borderColor: C.green },
  chipText: { ...T.tiny, color: C.muted, fontFamily: 'Archivo_700Bold' },
  // The list button: an icon in a chip, pushed to the row's far right.
  // The Completed chip's height exactly — its text line plus the chip's
  // padding and border — with the glyph a size up to fill it (owner).
  chipIcon: { marginLeft: 'auto', paddingHorizontal: 10, paddingVertical: 0, height: T.tiny.lineHeight + 5 * 2 + 2, justifyContent: 'center' },
  /* The compact list: a card of hairline-ruled rows. The clock and the round
     are fixed columns so the names line up down the page; the score keeps
     its width and the names give. No lineHeight on the row's text — the row
     is a fixed height and iOS sinks caps under a lineHeight. */
  /* EVERY POINT OF WIDTH (owner, 2026-09-17): the cards run to S.sm from
     the glass rather than the page's S.lg — the text inside still lands on
     the page's own margin — and the round sits close on the names. */
  edge: { marginHorizontal: -(S.lg - S.sm) },
  // The card's edge is the same line as the dividers inside it (owner, 2026-09-17).
  rows: { borderRadius: R.md, borderWidth: 2, borderColor: C.borderLit, backgroundColor: C.card, overflow: 'hidden', marginHorizontal: -(S.lg - S.sm) },
  row: { flexDirection: 'row', alignItems: 'center', gap: 5, paddingHorizontal: 8, paddingVertical: 5, minHeight: leading(34) },
  rowNext: { borderTopWidth: 1, borderTopColor: C.border },
  // A touch tighter than the tag's full 8 below the line: the glyphs stop short
  // of it (owner, 2026-09-17). Back to 6 now the round shares the top player's
  // line instead of sitting in a band of its own above the card — with nothing
  // between the border and the names, this padding is the clearance again.
  miniRow: { paddingHorizontal: 0, paddingTop: 6, paddingBottom: 5 },
  // The wrapper carries the card's side margin so the first row's tags can sit on its edge.
  /* EDGE TO EDGE (owner, 2026-09-18): the mid view's card is rows across the
     whole screen — the page's own padding taken back, no corners, no side
     lines; the top and bottom lines stay, the same weight as the dividers. */
  miniWrap: { marginHorizontal: -S.lg },
  rowsInWrap: { marginHorizontal: 0, borderRadius: 0, borderLeftWidth: 0, borderRightWidth: 0 },
  // The cell: [group bar][card][H2H bar], the bars full height.
  // Room for a tab on either side: the tour bar, the tab, a hair.
  miniCard: { paddingLeft: 8, paddingRight: 27 },
  /* INDENTED PAST THE CLOCK, on a match still waiting for one (owner,
     2026-09-21). 8 put the seed badge almost against the tour bar; 16 still
     sat it directly under the time on the border. Both player rows now start
     clear of the clock's column — see MINI_CLOCK_COL for the arithmetic. */
  miniCardWaiting: { paddingLeft: MINI_CLOCK_COL },
  /* THE DRAW VIEW'S SIDE TABS, run top to bottom (owner, 2026-09-17): the
     bracket's chip — 24 wide, 1px green-500 on the card fill, radius 4 —
     stretched to the row's height, the word on its side, the icon upright. */
  /* TO THE CARD'S SIDE EDGES (owner, 2026-09-17): the tab's outer edge is
     the card's own, so its only line is the inside one; the dividers above
     and below are its ends. The tour bar rides over its outer 3pt. */
  // 16 tall, centred on the 2px line above: 8 above it, 8 below.
  /* THE STRIP THE THREE TAGS SHARE. Its ends are where the single left and
     right tags used to be anchored (10 and 28), so nothing moved; the round
     centres in what they leave. */
  miniTagRow: {
    position: 'absolute', top: -9, left: 10, right: 28,
    flexDirection: 'row', alignItems: 'center', zIndex: 1,
  },
  /* The two sides, flexed EQUALLY so the round between them lands on the
     strip's centre line — that equality is the whole mechanism. minWidth 0 so
     a long tournament name shrinks inside its cell instead of widening it. */
  miniTagSide: { flex: 1, minWidth: 0, flexDirection: 'row', alignItems: 'center' },
  miniTagSideRight: { justifyContent: 'flex-end' },
  miniTag: { height: 16, paddingHorizontal: 4, justifyContent: 'center', flexShrink: 1 },
  /* GOLD, BOTH ENDS OF THE STRIP (owner, 2026-09-21 — the tournament first,
     then "Put the time in the same gold colour").

     I had argued the other way when the tournament went gold: that the strip
     says two different kinds of thing, when the match is and which event it
     is, and that one colour for both read as a single run of furniture. The
     owner's call is the better one, and the reason is what the strip sits ON:
     the tags are the only ink on a rule that runs the width of the card, so
     what they need to be told apart from is the RULE, not each other — their
     two ends do that on their own. One gold pair reads as the card's caption;
     a gold word beside a grey number read as one of them being an
     afterthought.

     Overridden here rather than in s.rowWhen, which the list view's own clock
     column also uses and which is not on a border at all.

     Short names also stop the longest — "Dubai Tennis Championships" — from
     shrinking to fit the half-strip they get. */
  miniTagWhen: { color: C.gold },
  miniTagTourn: { flexShrink: 1, color: C.gold },
  miniTagHalf: { position: 'absolute', left: 0, right: 0, height: 8 },
  // A clear rule between matches (owner, 2026-09-17): two lines of box score
  // per match need a firmer division than the list's hairline.
  miniNext: { borderTopWidth: 2, borderTopColor: C.borderLit },
  // Zebra rows, and the tour bar in the row's own left padding.
  rowAlt: { backgroundColor: C.raised },
  rowBar: { position: 'absolute', left: 0, top: 0, bottom: 0, width: 3, zIndex: 2 },
  rowWhenSlot: { width: 58, flexDirection: 'row' },
  // The clock's and the round's columns together, for a score in their place.
  rowLeadSlot: { width: 58 + 5 + 30, flexDirection: 'row' },
  rowScoreLead: { textAlign: 'left', marginTop: 0 },
  rowWhen: { fontFamily: 'Archivo_500Medium', fontSize: 11, color: C.muted, fontVariant: ['tabular-nums'] },
  rowRoundSlot: { width: 30, flexDirection: 'row' },   // "R128" at 11pt bold is ~28; FitText shrinks it at larger text sizes
  rowRound: { fontFamily: 'Archivo_700Bold', fontSize: 11, color: C.faint },
  rowPlayers: { flex: 1, minWidth: 0 },
  rowNamesLine: { flexDirection: 'row', alignItems: 'center' },
  rowNames: { fontFamily: 'Archivo_500Medium', fontSize: 13, color: C.ink },   // FitText supplies the flex slot; each side is one
  rowNamesDone: { color: C.inkBody },
  rowVerb: { fontFamily: 'Archivo_500Medium', fontSize: 12, color: C.muted, paddingHorizontal: 4 },
  rowFlag: { marginHorizontal: 3 },
  rowFlagSpace: { width: leading(17) },
  // The measured left column: the name sits against the verb, right-aligned.
  rowLeft: { flexDirection: 'row', justifyContent: 'flex-end', minWidth: 0 },
  // The second line: the sets, centred under the verb (the halves are equal,
  // so the field's centre is the verb's), in a darker green — lit when live.
  rowScore: { fontFamily: 'Archivo_700Bold', fontSize: 12, color: C.greenMid, marginTop: 1, textAlign: 'center', fontVariant: ['tabular-nums'] },
  rowScoreLive: { color: C.greenLit },
  rowScoreRight: { flexShrink: 0, marginTop: 0, marginLeft: 6, textAlign: 'right' },
  /* flex-end, not center. The left side is TWO lines — court above time — so
     centring left the buttons floating on the seam between them, level with
     neither. Bottom-aligned they sit on the time, which is the line they are
     read alongside. In court view, where the court name is dropped and only
     the time remains, the two alignments agree anyway. */
  footLine: { flexDirection: 'row', alignItems: 'flex-end', gap: 8 },
  /* The court sits QUIETLY above its time. Both lines carry a tightened
     leading so they read as one block rather than two stray lines — through
     leading(), never a fixed number, so they still grow with Dynamic Type. */
  footCourt: { ...T.tiny, color: C.faint, lineHeight: leading(13) },
  /* Pulled up against the court. The line boxes cannot close the gap on their
     own — a lineHeight under about 1.2x the font size starts clipping
     descenders — so the last of it comes off as a negative margin. Through
     leading() like the rest, so it scales with Dynamic Type instead of
     becoming a bigger and bigger bite as the type grows. */
  footTime: { ...T.smallMed, color: C.greenBright, fontFamily: 'Archivo_700Bold',
              lineHeight: leading(16), marginTop: leading(-3) },
  footTimeEst: { color: C.muted, fontStyle: 'italic' },
  /* THE CHIP, and every chip on this row is this chip. An explicit height
     rather than padding around whatever is inside: "H2H" is text, the Lock
     Screen switch is an emoji in a Text, and the predictors button is an
     Ionicons component that shares none of the text metrics — so sizing by
     content made three buttons of three heights sitting in a row. Height plus
     centring makes the content irrelevant, which is the only version that
     stays true when the next one is added.

     Through leading(), so the box grows with Dynamic Type like the text it
     sits beside. */
  h2hChip: {
    borderRadius: 4, borderWidth: 1, borderColor: C.borderOn,
    paddingHorizontal: 7, height: leading(20),
    alignItems: 'center', justifyContent: 'center',
  },
  // Icon-only chips: a touch more room either side, nothing else. Height is
  // never overridden — that is the point of it living on h2hChip.
  iconChip: { paddingHorizontal: 8 },
  h2hText: { fontFamily: 'Archivo_700Bold', fontSize: 10, lineHeight: leading(14), letterSpacing: 0.5, color: C.greenLit },
  // Icon only, the same height as H2H; lit green while the match is showing.
  lockChip: { paddingHorizontal: 6 },
  lockChipOn: { backgroundColor: C.greenLit, borderColor: C.greenLit },
  lockIcon: { fontSize: 11 },
  tabs: {
    flexDirection: 'row', gap: S.xs, backgroundColor: C.sunken,
    borderRadius: R.md, padding: 2,
  },
  // The switch and the density button on one line, with a gap between them
  // wide enough that they read as two controls rather than one.
  viewRow: { flexDirection: 'row', alignItems: 'center', gap: S.sm },
  // The switch still takes the width the button leaves it.
  tabsGrow: { flex: 1 },
  /* THE DAY'S THREE, across the whole list. The Time/Court control's anatomy
     exactly — a sunken strip, every segment bordered so nothing moves as the
     selection does, the chosen one lit on deep green — because it is the same
     kind of control and a second visual language for it would only ask the
     reader to learn one. It sits tighter to the list beneath it than the strip
     above does: it belongs to the rows, not to the filters. */
  phases: {
    flexDirection: 'row', gap: S.xs, backgroundColor: C.sunken,
    borderRadius: R.md, padding: 2, marginTop: S.xs,
  },
  phase: {
    flex: 1, alignItems: 'center', justifyContent: 'center', paddingVertical: 5,
    borderRadius: R.sm, borderWidth: 1, borderColor: 'transparent',
  },
  phaseOn: { backgroundColor: C.greenDeep, borderColor: C.greenLit },
  phaseText: { fontFamily: 'Archivo_500Medium', fontSize: 13, color: C.muted },
  phaseTextOn: { fontFamily: 'Archivo_700Bold', color: C.ink },
  /* The count is the quieter half of the label: it qualifies the word rather
     than competing with it. */
  phaseN: { fontFamily: 'Archivo_400Regular', color: C.faint },
  phaseNOn: { color: C.greenLit },
  /* Every half carries a border so the box does not change size when it
     moves; only the chosen one's shows. */
  tab: {
    flex: 1, alignItems: 'center', justifyContent: 'center', paddingVertical: 4, borderRadius: R.sm,
    borderWidth: 1, borderColor: 'transparent',
  },
  // No lineHeight — see the note at the control. The Pressable centres it.
  tabText: { fontFamily: 'Archivo_500Medium', fontSize: 13, color: C.muted },
  tabTextOn: { fontFamily: 'Archivo_700Bold', color: C.ink },
  /* THE CHOSEN HALF IS BOXED. A fill one step lighter than the strip was
     the only mark, and on the phone the two halves read as the same
     shade (owner, 2026-09-17): now a lit border on a deep-green fill, and
     the label in bold ink — the same lit-on-deep pair as the draw page's
     round pill, so it says "chosen" in the app's own words. */
  tabOn: { backgroundColor: C.greenDeep, borderColor: C.greenLit },
  /* The tournament filter. A wrapping row, because two names can be longer
     than a phone and a horizontal scroller hides its own overflow. */
  /* ONE LINE, NOT A WRAPPING BLOCK (owner, 2026-09-21): the size is solved
     to make the row fit, so wrapping would only ever hide a solver bug. */
  events: { flexDirection: 'row', flexWrap: 'nowrap', alignItems: 'stretch', gap: PILL_GAP },
  eventBox: {
    /* A COLUMN NOW: the tier sits above the name (owner, 2026-09-21). */
    flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
    /* ONLY JUST ROUNDED (owner, 2026-09-21). At R.pill these read as buttons
       and, two lines tall, as lozenges; R.xs keeps a corner you notice only
       if you look for it, and lets them read as labels. */
    borderRadius: R.xs, borderWidth: 1, borderColor: C.border,
    backgroundColor: C.card,
    /* NO lineHeight ON EITHER LINE, and almost no vertical padding (owner,
       2026-09-21: "make the pill boxes way less tall reduce all spaces both
       above and below all text").

       The tallness was a lineHeight of 1.2x on each line, and on iOS RN adds
       everything a lineHeight gives beyond the font's natural line ABOVE the
       glyphs rather than around them — so it paid for the height twice: once
       in the box and once as a gap over each word, which also sank both lines
       off centre (feedback_ios_lineheight_sinks_caps). Dropping it lets
       Archivo's own line box set the height, which centres its capitals to a
       tenth of a point on its own, and is the SAFEST thing under Dynamic Type
       besides: fontSize scales with the reader's text setting and there is no
       fixed line box left for the glyphs to outgrow
       (feedback_dynamic_type_lineheight). */
    paddingHorizontal: PILL_PAD, paddingVertical: 1,
    /* flexShrink STAYS, as the last guard against a row wider than the phone:
       the solver is what keeps the text whole, and if it is ever wrong it is
       better to squeeze the boxes than to push the last one off the screen.
       The Texts clip rather than ellipsize, so a squeeze can never print "…"
       (feedback_name_shortening_ladder — this project does not print it). */
    flexShrink: 1,
  },
  // Greyed when the tournament has nothing on the day. This line once sat
  // INSIDE eventBox - a nested key no style reads - so nothing greyed.
  eventIdle: { opacity: 0.4 },
  // Lit, the same green the Doubles chip lights with — these are siblings in
  // the same stack of controls and a second green would read as a second
  // meaning.
  eventBoxOn: { backgroundColor: C.green, borderColor: C.green },
  eventNameOn: { color: '#fff' },
  /* fontSize and lineHeight are set at render from the solved size, so they
     are deliberately absent here — T.tiny's would silently win otherwise. */
  eventName: { color: C.ink, fontFamily: 'Archivo_700Bold', textAlign: 'center', flexShrink: 1 },
  // The tier, centred over the name and quieter than it: it says what the
  // week is worth, which nobody reads before knowing which week it is.
  /* NO letterSpacing. It was 0.4, which adds a trailing gap after the last
     digit that fitPillSize does not model — about a point per pill, which is
     exactly the slack the solver keeps for kerning. Spending it twice is how
     the row overflows again. */
  eventTier: { fontFamily: 'Archivo_700Bold', color: C.muted, textAlign: 'center',
               flexShrink: 1 },
  eventTierOn: { color: '#ffffffcc' },

  // Rows breathe: the gap is what separates one match from the next, and at
  // S.xs the cards read as a single ruled block rather than a stack of cards.
  group: { gap: S.sm, marginTop: S.sm },
  entry: {
    /* borderLit, the brightest of the three: against C.card these rows sit on
       a page barely lighter than they are, and both dimmer tokens left each
       card's edge to be inferred from the gap between them rather than seen. */
    backgroundColor: C.card, borderRadius: R.md, borderWidth: 1, borderColor: C.borderLit,
    padding: S.md, gap: 3,
  },
  entryLive: { borderColor: C.green },
  entryTop: { flexDirection: 'row', alignItems: 'center', gap: S.sm },
})
