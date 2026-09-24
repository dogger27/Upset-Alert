/*
 * Who called this match right — or, before it is decided, whose pick is still
 * standing and whose has already gone out.
 *
 * Offered on every real match. Undecided (`pending`), the server puts anyone
 * whose pick has not lost yet in `correct`, the rest in `incorrect`, names the
 * pick on both, and orders each by how many backed that player.
 *
 * USERNAMES, NOT display_name. display_name on this project is very often the
 * person's real name — it is what the standings deliberately hide behind a
 * league's show_real_name flag — and this endpoint returns BOTH fields with no
 * such flag attached. Rendering display_name here would quietly publish real
 * names to every member of every league, from a screen nobody thinks of as a
 * roster.
 */

import { useMemo, useState } from 'react'
import { Ionicons } from '@expo/vector-icons'
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native'
import { getLeagues, getPredictors } from './api'
import { nameForms } from './names'
import { predictorsMessage } from './lock'
import { shortRound } from './rounds'
import { useApi } from './useApi'
import { C, S, T } from './theme'
import { leading } from './fontScale'
import { Loading } from './ui'

export function PredictorsSheet({ visible, onClose, drawId, match, meId, leagueId: initialLeagueId = null }) {
  const winner = match?.winner?.name
  const pending = !match?.winner
  // Names only once the ACTUAL players are known; the round and status pills
  // below are always there.
  const known = !!(match?.player1?.name && match?.player2?.name)
  /* WHO IS PLAYING, as the line the sheet is about. Built as pieces rather
     than one string so the underline lands on the names and not on the "vs."
     joining them. */
  /* The one this match was won against. Both callers hand us the site's match
     shape (player1/player2/winner), so the loser is simply the side the winner
     is not. */
  const loser = !pending && known
    ? (match.winner?.name === match.player1?.name ? match.player2?.name : match.player1?.name)
    : null
  /* A finished match names BOTH players — "A. Michelsen def. T. Etcheverry" —
     the way the site's PredictorsPopup already did. The winner alone answered
     "who won" while leaving "won what?" hanging, which is the more useful half
     on a sheet about who predicted this match. 'winner' remains for the case
     where a result exists but a player's name does not. */
  const sub = pending ? (known ? 'players' : null) : winner ? (loser ? 'result' : 'winner') : null
  const live = pending && !!(match?.live_scores || match?.live_point)
  const status = !pending ? 'Completed' : !known ? 'TBD' : live ? 'In Progress' : 'Upcoming'
  const statusStyle = !pending ? s.pillDone : !known ? s.pillTbd : live ? s.pillLive : s.pillUpcoming


  return (
    <Modal visible={!!visible} animationType="slide" transparent onRequestClose={onClose}>
      <Pressable style={s.scrim} onPress={onClose} />
      <View style={s.sheet}>
        <View style={s.grabber} />
        {/* Title left, state right, on one line. The round travels with the
            status because the two are one thought — which match, and where it
            has got to — and splitting them would leave a lone "—" stranded
            mid-sheet. */}
        <View style={s.head}>
          <Text style={s.title} numberOfLines={1}>Who got it right?</Text>
          <View style={s.meta}>
            {/* R32, never "Round of 32". The two callers disagree about this
                field — the schedule hands over `round_label`, already compact,
                while the draw screen hands over Draw.round_name()'s long form
                — so the pill compacts whatever it gets. shortRound is a no-op
                on a label that is already short. */}
            <View style={[s.pill, s.pillRound]}><Text style={[s.pillText, s.pillRoundText]}>{shortRound(match?.round_name) || '—'}</Text></View>
            <View style={[s.pill, statusStyle]}><Text style={[s.pillText, statusStyle]}>{status}</Text></View>
          </View>
        </View>
        {sub ? (
          <Text style={s.sub} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.75}>
            {sub === 'players' ? (
              <>
                <Text style={s.subName}>{shortP(match.player1.name)}</Text>
                <Text> vs. </Text>
                <Text style={s.subName}>{shortP(match.player2.name)}</Text>
              </>
            ) : sub === 'result' ? (
              <>
                <Text style={s.subName}>{shortP(winner)}</Text>
                <Text> def. </Text>
                <Text style={s.subLoser}>{shortP(loser)}</Text>
              </>
            ) : (
              <>
                <Text style={s.subName}>{shortP(winner)}</Text>
                <Text> won</Text>
              </>
            )}
          </Text>
        ) : null}

        <PredictorsBody active={!!visible} drawId={drawId} match={match} meId={meId}
                        initialLeagueId={initialLeagueId} />

        <Pressable onPress={onClose} style={s.close} hitSlop={8}>
          <Text style={s.closeText}>Close</Text>
        </Pressable>
      </View>
    </Modal>
  )
}

/* THE PICKS THEMSELVES — scope pill, split bar and the two columns — apart
   from the sheet's chrome, so the match sheet's Prediction tab shows exactly
   this and the two can never drift (owner, 2026-09-24). `scroll` off when the
   host already scrolls: a ScrollView in a ScrollView fights for the finger. */
export function PredictorsBody({ active = true, drawId, match, meId, initialLeagueId = null, scroll = true }) {
  /* WHOSE PICKS: everyone in the draw (Global) or one of the reader's own
     leagues. The site scopes this to the league its draw page has selected;
     here the sheet carries a scope pill of its own, and the reader can move
     it. null is Global. */
  const [leagueId, setLeagueId] = useState(initialLeagueId)
  const [choosing, setChoosing] = useState(false)
  const key = active && match ? `predictors:${drawId}:${match.id}:${leagueId ?? 'global'}` : null
  const q = useApi(key, () => getPredictors(drawId, match.id, leagueId))
  const d = q.data
  /* The reader's leagues, for the chooser: only the ones they belong to.
     getLeagues lists public leagues too, and a stranger's league is not a
     group of theirs. */
  const leagues = useApi(active ? 'leagues' : null, getLeagues)
  const mine = useMemo(() => (leagues.data || []).filter(l => (l.members || []).some(m => m.id === meId)), [leagues.data, meId])
  /* THE PEOPLE THE READER KNOWS — everyone in their own leagues — who come
     first when Global has to leave names out. */
  const friends = useMemo(() => {
    const ids = new Set()
    for (const l of mine) for (const m of l.members || []) if (m.id !== meId) ids.add(m.id)
    return ids
  }, [mine, meId])
  const scopeName = leagueId == null ? 'Global' : (d?.league_name ?? mine.find(l => l.id === leagueId)?.name ?? 'League')

  const fieldSize = (d?.correct?.length || 0) + (d?.incorrect?.length || 0)
  /* WITHHELD IS NOT EMPTY, and the difference is the whole sheet. Under
     match-by-match locking the server returns both columns empty with
     `hidden` set, because picks stay editable through round one and a
     visible bracket is a bracket to copy. Rendering the columns then says
     "No one." about a match the whole field predicted — which is what it
     did on a completed Singapore first-rounder six people had picked, one
     of them correctly (owner, 2026-09-21). lock.js owns the sentence, so
     this explanation and the standings' cannot drift apart. */
  const withheld = predictorsMessage(d)

  const Wrap = scroll ? ScrollView : View
  return (
    <>
        {/* THE SCOPE PILL: which group these picks are from. Square-cornered,
            unlike the round/status pills above, so it reads as a control and
            not a label; a tap opens the reader's leagues beneath it. */}
        <View style={s.scopeRow}>
          <Pressable onPress={() => setChoosing(c => !c)} style={({ pressed }) => [s.scope, pressed && s.scopeDown]}
                     accessibilityRole="button" accessibilityLabel={`Picks from ${scopeName}. Change group`}>
            <Text style={s.scopeText} numberOfLines={1}>{scopeName}</Text>
            <Ionicons name={choosing ? 'chevron-up' : 'chevron-down'} size={14} color={C.muted} />
          </Pressable>
        </View>
        {choosing ? (
          <View style={s.chooser}>
            {[{ id: null, name: 'Global' }, ...mine].map(l => {
              const on = (l.id ?? null) === (leagueId ?? null)
              return (
                <Pressable key={l.id ?? 'global'} onPress={() => { setLeagueId(l.id ?? null); setChoosing(false) }}
                           style={({ pressed }) => [s.choice, on && s.choiceOn, pressed && s.scopeDown]}
                           accessibilityRole="button" accessibilityState={{ selected: on }}>
                  <Text style={[s.choiceText, on && s.choiceTextOn]} numberOfLines={1}>{l.name}</Text>
                  {on ? <Ionicons name="checkmark" size={16} color={C.greenBright} /> : null}
                </Pressable>
              )
            })}
          </View>
        ) : null}

        {q.loading && !d ? <Loading /> : null}
        {q.error ? <Text style={s.err}>Couldn’t load predictions.</Text> : null}

        {withheld ? <Text style={s.withheld}>{withheld}</Text> : d ? (
          <Wrap style={s.list} {...(scroll ? { contentContainerStyle: { paddingBottom: S.lg } } : {})}>
            {/* TWO COLUMNS, ONE SPLIT (owner, 2026-09-24): right — or "Maybe",
                in gold, until there is a winner to be right about — on the
                left, wrong on the right, each listing its people. The bar
                above them is the split of the whole field, and the key to the
                columns under it. BOTH columns always, empty or not: "Wrong 0"
                is a fact about the match, not a gap.

                A pick whose player has already lost is in `incorrect` even
                before a result: it is not provisionally wrong, it is wrong. */}
            <SplitRail left={d.correct?.length || 0} right={d.incorrect?.length || 0}
                       leftTone={d.pending ? C.warn : C.greenLit} />
            <View style={s.columns}>
              <Column label={d.pending ? 'Maybe' : 'Right'} tone={d.pending ? C.warn : C.greenLit}
                      people={d.correct} fieldSize={fieldSize} meId={meId} friends={friends}
                      cap={leagueId == null ? GLOBAL_CAP : null}
                      showPicks={d.pending} />
              <View style={s.columnRule} />
              <Column label="Wrong" tone={C.bad}
                      people={d.incorrect} fieldSize={fieldSize} meId={meId} friends={friends}
                      cap={leagueId == null ? GLOBAL_CAP : null}
                      showPicks />
            </View>
          </Wrap>
        ) : null}

    </>
  )
}

/* "A. Zverev", the initials-and-surname rung of the ladder, falling back to
   the full name when a name has no rung to drop to. Shared by the match-up
   line and the bucket rows so one player cannot appear as two. */
const shortP = (n) => (n ? (nameForms(n)[1] || nameForms(n)[0]) : '')

/* GLOBAL NAMES AT MOST THIS MANY A COLUMN (owner, 2026-09-24). A league is
   a group of people who know each other and is always shown whole; the
   whole field is not, and a column of two hundred usernames answers nothing. */
const GLOBAL_CAP = 10

/* The field's split as one bar: each side's share of everyone who picked this
   match, in its column's colour, the left segment over the left column. */
function SplitRail({ left, right, leftTone }) {
  const total = left + right
  if (!total) return null
  return (
    <View style={s.rail} accessibilityLabel={`${left} of ${total} on the left, ${right} on the right`}>
      {left > 0 && <View style={{ flex: left, backgroundColor: leftTone }} />}
      {left > 0 && right > 0 && <View style={s.railGap} />}
      {right > 0 && <View style={{ flex: right, backgroundColor: C.bad }} />}
    </View>
  )
}

/* ONE COLUMN: its heading, then its people.
 *
 * WHO IS SHOWN WHEN NOT EVERYONE CAN BE (`cap`, Global only): you first, then
 * people from your own leagues, then the rest in the server's order (weight of
 * support). "+N more" under the list opens the rest.
 *
 * Grouped by WHO THEY PICKED when that is not already obvious (`showPicks`):
 * the wrong column, and both columns before a result. Groups run fewest
 * backers first — on Upset Alert the three who went the other way are the
 * news — and each says its full count even when only some of it is shown. */
function Column({ label, tone, people, fieldSize, meId, friends, cap, showPicks }) {
  const [all, setAll] = useState(false)
  const list = useMemo(() => people || [], [people])
  const pct = fieldSize ? Math.round((100 * list.length) / fieldSize) : 0

  const { groups, hidden } = useMemo(() => {
    const rank = p => (meId != null && p.id === meId ? 0 : friends.has(p.id) ? 1 : 2)
    const ordered = list.map((p, i) => ({ p, i })).sort((a, b) => rank(a.p) - rank(b.p) || a.i - b.i).map(x => x.p)
    const shown = new Set((cap && !all ? ordered.slice(0, cap) : ordered).map(p => p.id))
    const by = new Map()
    for (const p of ordered) {
      const k = showPicks ? (p.picked || '') : ''
      if (!by.has(k)) by.set(k, { picked: k, total: 0, people: [] })
      const g = by.get(k)
      g.total += 1
      if (shown.has(p.id)) g.people.push(p)
    }
    const gs = [...by.values()].filter(g => g.people.length).sort((a, b) => a.total - b.total)
    return { groups: gs, hidden: list.length - shown.size }
  }, [list, meId, friends, cap, all, showPicks])

  return (
    <View style={s.column}>
      <Text style={[s.colLabel, { color: tone }]}>{label}</Text>
      <Text style={s.colCount}>
        <Text style={[s.colCountNum, { color: tone }]}>{list.length}</Text>
        {fieldSize ? `  ${pct}%` : ''}
      </Text>
      {!list.length ? <Text style={s.none}>No one</Text> : null}
      {groups.map(g => (
        <View key={g.picked || '_'} style={s.pickGroup}>
          {showPicks ? (
            <Text style={s.pickHead}>
              {g.picked ? shortP(g.picked) : 'No pick'}
              <Text style={s.pickHeadCount}>{`  ${g.total}`}</Text>
            </Text>
          ) : null}
          {g.people.map(p => {
            const me = meId != null && p.id === meId
            return (
              <Text key={p.id} style={[s.person, me && s.personMe]}>
                {p.username}{me ? ' 🤞' : ''}
              </Text>
            )
          })}
        </View>
      ))}
      {hidden > 0 ? (
        <Pressable onPress={() => setAll(true)} hitSlop={6} accessibilityRole="button"
                   accessibilityLabel={`Show ${hidden} more`}>
          <Text style={[s.more, { color: tone }]}>+{hidden} more</Text>
        </Pressable>
      ) : null}
    </View>
  )
}

const s = StyleSheet.create({
  scrim: { flex: 1, backgroundColor: '#000a' },
  sheet: {
    backgroundColor: C.card, borderTopLeftRadius: 18, borderTopRightRadius: 18,
    borderTopWidth: 1, borderColor: C.border,
    paddingHorizontal: S.md, paddingTop: S.sm, paddingBottom: S.md,
    maxHeight: '72%',
  },
  grabber: {
    width: 36, height: 4, borderRadius: 2, backgroundColor: C.border,
    alignSelf: 'center', marginBottom: S.sm,
  },
  head: { flexDirection: 'row', alignItems: 'center', gap: S.sm },
  // flexShrink, not flex: the title yields to the pills on a narrow screen
  // rather than pushing them off the edge.
  title: { ...T.h2, color: C.ink, flexShrink: 1 },
  // Centred across the sheet, on the owner's call — the match-up is the one
  // line here that belongs to the whole screen rather than to the title above
  // it, and centring is what says so.
  sub: { ...T.small, color: C.muted, marginTop: 4, textAlign: 'center' },
  /* THE TWO PLAYERS, in the brand's clay. This line names the match the whole
     sheet is about and was reading as a caption; size, weight and the one warm
     colour on the palette carry it now.

     Still built from separate pieces even without an underline to place: the
     colour lands on the names and the "vs." between them stays muted, which is
     what keeps the two players reading as two things. */
  /* The beaten player, same size and weight so the line reads as one pairing,
     but muted so the winner still wins the eye — the site's .pp-loser. */
  subLoser: {
    fontFamily: 'Archivo_700Bold', fontSize: 17, lineHeight: leading(23),
    color: C.muted,
  },
  subName: {
    fontFamily: 'Archivo_700Bold', fontSize: 17, lineHeight: leading(23),
    color: C.clay,
  },
  meta: { flexDirection: 'row', alignItems: 'center', gap: 6, marginLeft: 'auto' },
  // The draw's SCHEDULED chip, one per state. `color` on the pill style is
  // read by the Text, borderColor/backgroundColor by the View.
  pill: { borderRadius: 4, borderWidth: 1, paddingHorizontal: 6, paddingVertical: 1 },
  pillText: { fontFamily: 'Archivo_700Bold', fontSize: 9, lineHeight: leading(13), letterSpacing: 0.5 },
  pillRound: { borderColor: C.border, backgroundColor: C.raised },
  pillRoundText: { color: C.inkBody },
  pillLive: { borderColor: C.greenLit, backgroundColor: C.raised, color: C.greenLit },
  pillUpcoming: { borderColor: '#3b4c8a', backgroundColor: '#182140', color: '#9db4ff' },
  pillDone: { borderColor: C.border, backgroundColor: C.raised, color: C.muted },
  pillTbd: { borderColor: C.border, borderStyle: 'dashed', backgroundColor: 'transparent', color: C.muted },
  list: { marginTop: S.sm },
  /* The split: thin, full width, square-ended segments with a hairline of
     the sheet between them. */
  rail: { flexDirection: 'row', height: 6, borderRadius: 3, overflow: 'hidden', marginBottom: S.md },
  railGap: { width: 2, backgroundColor: C.card },
  columns: { flexDirection: 'row', alignItems: 'flex-start' },
  column: { flex: 1, minWidth: 0, gap: 2 },
  columnRule: { width: 1, alignSelf: 'stretch', backgroundColor: C.border, marginHorizontal: S.md },
  colLabel: { ...T.h2, lineHeight: leading(22) },
  colCount: { ...T.small, color: C.faint, marginBottom: S.sm, fontVariant: ['tabular-nums'] },
  colCountNum: { fontFamily: 'Archivo_700Bold' },
  pickGroup: { marginBottom: S.sm, gap: 2 },
  pickHead: { ...T.tiny, color: C.muted, fontFamily: 'Archivo_700Bold', marginBottom: 2 },
  pickHeadCount: { color: C.faint, fontFamily: 'Archivo_500Medium' },
  person: { ...T.small, color: C.inkBody },
  personMe: { color: C.clay, fontFamily: 'Archivo_700Bold' },
  more: { ...T.small, fontFamily: 'Archivo_700Bold', paddingVertical: 4 },
  /* A pick and its backers. The header is a touch target, so it takes the
     full width and a real row height rather than hugging its text. */
  // Indented to 20 like the chips, so an empty section sits exactly where a
  // full one's names would — the eye reads it as the section's content rather
  // than as another heading.
  none: { ...T.small, color: C.faint },
  /* Centred and roomy, unlike `none`'s indented aside: this replaces the
     whole answer rather than qualifying one column of it. */
  withheld: { ...T.small, color: C.muted, textAlign: 'center',
              paddingVertical: S.lg, paddingHorizontal: S.md,
              lineHeight: leading(T.small.fontSize * 1.45) },
  // Tabular so the digits sit in columns down the sheet.
  // Held off the sheet's edge rather than flush against it. Still fixed-width
  // and right-aligned, so the indent moves the whole column and the chevrons
  // and names behind it stay in line.
  /* leading(), not a bare 38: the GLYPHS grow with the reader's text size but
     a hard-coded width does not, so "100%" — the widest this ever gets — ran
     out of column and wrapped the "%" onto its own line. The column now grows
     by the same factor the text does. Same reason the chevron's box scales:
     an icon font scales too, and a fixed box clips it. */
  // The name takes the space and the count sits tight against it, so the
  // count never drifts to the far edge on a short name.
  // The pick, as a heading. Plain: the treatment belongs to the MATCH-UP line
  // above, and giving it to both would leave neither looking like the subject.
  // The same 🤞 the score cards use for a pick, at the same size.
  // Indented under their heading, so an open bucket reads as belonging to it.
  err: { ...T.small, color: C.bad, textAlign: 'center', paddingVertical: S.md },
  scopeRow: { flexDirection: 'row', marginTop: S.sm, marginBottom: S.xs },
  scope: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    paddingVertical: 4, paddingHorizontal: 10, borderRadius: 3,
    borderWidth: 1, borderColor: C.borderLit, backgroundColor: C.raised,
  },
  scopeDown: { borderColor: C.greenBright },
  scopeText: { ...T.smallMed, color: C.ink },
  chooser: {
    borderWidth: 1, borderColor: C.borderOn, borderRadius: 3, backgroundColor: C.raised,
    marginBottom: S.sm, overflow: 'hidden',
  },
  choice: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingVertical: 10, paddingHorizontal: 12, borderTopWidth: 1, borderColor: C.border,
  },
  choiceOn: { backgroundColor: C.card },
  choiceText: { ...T.body, color: C.ink },
  choiceTextOn: { fontFamily: 'Archivo_700Bold', color: C.greenBright },
  /* A ruled footer: a hairline across the sheet above "Close", and less
     height than the button used to take on its own. */
  close: {
    alignSelf: 'stretch', alignItems: 'center', marginHorizontal: -S.md, marginTop: S.sm,
    paddingVertical: S.xs, borderTopWidth: 1, borderColor: C.borderOn,
  },
  closeText: { ...T.smallMed, color: C.clay },
})
