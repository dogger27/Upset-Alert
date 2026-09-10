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
import { getPredictors } from './api'
import { nameForms } from './names'
import { shortRound } from './rounds'
import { useApi } from './useApi'
import { C, R, S, T } from './theme'
import { leading } from './fontScale'
import { Loading } from './ui'

export function PredictorsSheet({ visible, onClose, drawId, match, meId }) {
  const key = visible && match ? `predictors:${drawId}:${match.id}` : null
  const q = useApi(key, () => getPredictors(drawId, match.id))
  const d = q.data

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

  const fieldSize = (d?.correct?.length || 0) + (d?.incorrect?.length || 0)

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

        {q.loading && !d ? <Loading /> : null}
        {q.error ? <Text style={s.err}>Couldn’t load predictions.</Text> : null}

        {d ? (
          <ScrollView style={s.list} contentContainerStyle={{ paddingBottom: S.lg }}>
            {/* BOTH, always, empty or not. A missing heading reads as a
                loading gap or a bug, where "Right (0)" is a fact about the
                match — and a strong one: every pick in the draw has already
                gone out. Holding both positions between matches also lets the
                eye learn where to look.

                Right and wrong even before a result: the server puts a pick
                whose player has already lost into `incorrect`, and that pick
                is not provisionally wrong, it is wrong. */}
            {/* Both sections share one denominator — everyone who picked this
                match — so the percentages across the whole sheet add to 100. */}
            {/* NOBODY IS RIGHT YET while a match is undecided — "Maybe", in
                gold, until there is a winner to be right about. `pending` is
                the server's own "no winner", so this covers a match not yet
                started and one on court alike; only a finished match earns
                the green "Right". The site's popup has always drawn a gold
                "?" here rather than its green check, for the same reason. */}
            <Group label={d.pending ? 'Maybe' : 'Right'}
                   tone={d.pending ? C.warn : C.greenLit}
                   people={d.correct} meId={meId}
                   fieldSize={fieldSize} fallback={d.pending ? '' : shortP(winner)} />
            <Group label="Wrong" tone={C.bad} people={d.incorrect} meId={meId}
                   fieldSize={fieldSize} />
          </ScrollView>
        ) : null}

        <Pressable onPress={onClose} style={s.close} hitSlop={8}>
          <Text style={s.closeText}>Close</Text>
        </Pressable>
      </View>
    </Modal>
  )
}

/* One PLAYER and everyone who backed them, collapsed until asked.
 *
 * A flat list of names repeated the same pick twenty-nine times and made the
 * reader count to learn the only thing the screen is for: how the field
 * split. The pick is the heading now and the names are behind it.
 *
 * FEWEST FIRST. The lopsided side is never the news — on a screen called
 * Upset Alert the three people who went the other way are — and putting the
 * long list last also keeps the short ones above the fold.
 */
/* `isMine`, not `mine`: the chip loop below declares its own per-PERSON
   `mine`, and two different meanings of one word in one function is how a
   later edit ends up highlighting every chip in your bucket. */
/* "A. Zverev", the initials-and-surname rung of the ladder, falling back to
   the full name when a name has no rung to drop to. Shared by the match-up
   line and the bucket rows so one player cannot appear as two. */
const shortP = (n) => (n ? (nameForms(n)[1] || nameForms(n)[0]) : '')

function PickBucket({ picked, people, tone, meId, isMine, fieldSize, fallback }) {
  const [open, setOpen] = useState(false)
  /* Every row names the player it is about, both columns alike: "A. Zverev
     (28)" over "A. Tabilo (1)" is a scoreline you can read in one glance.

     A FINISHED match sends no pick name for the people who got it right — the
     server omits it on purpose, since a correct pick can only be the winner
     (routers/tournaments.py: "a correct pick is the winner, already in the
     title"). `fallback` supplies that name back rather than leaving the row
     unlabelled, and it is only ever passed for the right column of a decided
     match, where the winner IS what all of them picked.

     "No pick" is left for where it is TRUE: anyone with no pick fails
     `pid == winner_id`, lands in Wrong, and gets no fallback. */
  const label = shortP(picked) || fallback || 'No pick'
  const count = `${people.length} ${people.length === 1 ? 'person' : 'people'}`
  return (
    <View style={s.bucket}>
      <Pressable onPress={() => setOpen(o => !o)} hitSlop={6}
                 accessibilityRole="button"
                 accessibilityState={{ expanded: open }}
                 accessibilityLabel={[label, count].filter(Boolean).join(', ')}
                 style={s.bucketHead}>
        {/* SHARE OF THE WHOLE FIELD, not of this section: "86%" means 86% of
            everyone who picked this match, which is the comparison worth
            making. Against the section it would read 100% for the only group
            in it and say nothing at all.

            Fixed width and right-aligned so the chevrons and names below line
            up whether the number is 3% or 86%. */}
        <Text style={[s.pct, { color: tone }]} numberOfLines={1}
              adjustsFontSizeToFit minimumFontScale={0.8}>
          {fieldSize ? `${Math.round((100 * people.length) / fieldSize)}%` : ''}
        </Text>
        <Ionicons name={open ? 'chevron-down' : 'chevron-forward'}
                  size={14} color={tone} style={s.chev} />
        <Text style={s.bucketName} numberOfLines={1}>{label}</Text>
        <Text style={[s.bucketCount, { color: tone }]}>({people.length})</Text>
        {/* YOUR pick, named without opening anything. Auto-expanding this row
            was the wrong way to answer "which one is mine": it dumped a list
            of other people's names to say one thing about you, and on a busy
            match that was the longest row on the screen. The mark says it
            while the row stays shut. */}
        {isMine ? (
          <Text style={s.mineMark}
                accessibilityLabel="You predicted this player to win">🤞</Text>
        ) : null}
      </Pressable>
      {open ? (
        <View style={s.chips}>
          {people.map(p => {
            const mine = meId != null && p.id === meId
            return (
              <View key={p.id} style={[s.chip, mine && { borderColor: C.clay }]}>
                <Text style={[s.chipText, mine && { color: C.clay }]} numberOfLines={1}>
                  {p.username}
                </Text>
              </View>
            )
          })}
        </View>
      ) : null}
    </View>
  )
}

function Group({ label, tone, people, meId, fieldSize, fallback }) {
  /* Bucketed by pick, fewest backers first. Ties keep the order the server
     sent, which is already by weight of support. */
  const buckets = useMemo(() => {
    const by = new Map()
    for (const p of people || []) {
      const key = p.picked || ''
      if (!by.has(key)) by.set(key, [])
      by.get(key).push(p)
    }
    return [...by.entries()]
      .map(([picked, list]) => ({ picked, list }))
      .sort((a, b) => a.list.length - b.list.length)
  }, [people])

  return (
    <View style={s.group}>
      <Text style={[s.groupLabel, { color: tone }]}>
        {label} ({(people || []).length})
      </Text>
      {!people?.length ? <Text style={s.none}>No one.</Text> : null}
      <View>
        {buckets.map(b => (
          <PickBucket
            key={b.picked || '_none'} picked={b.picked} people={b.list}
            tone={tone} meId={meId} fieldSize={fieldSize} fallback={fallback}
            isMine={meId != null && b.list.some(p => p.id === meId)}
          />
        ))}
      </View>
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
  list: { marginTop: S.md },
  group: { marginBottom: S.md },
  groupLabel: { ...T.smallMed, marginBottom: S.xs },
  /* A pick and its backers. The header is a touch target, so it takes the
     full width and a real row height rather than hugging its text. */
  // Indented to 20 like the chips, so an empty section sits exactly where a
  // full one's names would — the eye reads it as the section's content rather
  // than as another heading.
  none: { ...T.tiny, color: C.faint, paddingVertical: 4, paddingLeft: 20 },
  bucket: { marginBottom: S.xs },
  bucketHead: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    paddingVertical: 7, paddingHorizontal: 2,
  },
  // Tabular so the digits sit in columns down the sheet.
  // Held off the sheet's edge rather than flush against it. Still fixed-width
  // and right-aligned, so the indent moves the whole column and the chevrons
  // and names behind it stay in line.
  /* leading(), not a bare 38: the GLYPHS grow with the reader's text size but
     a hard-coded width does not, so "100%" — the widest this ever gets — ran
     out of column and wrapped the "%" onto its own line. The column now grows
     by the same factor the text does. Same reason the chevron's box scales:
     an icon font scales too, and a fixed box clips it. */
  pct: { ...T.smallMed, width: leading(38), marginLeft: 10, textAlign: 'right',
         fontVariant: ['tabular-nums'] },
  chev: { width: leading(14), textAlign: 'center' },
  // The name takes the space and the count sits tight against it, so the
  // count never drifts to the far edge on a short name.
  // The pick, as a heading. Plain: the treatment belongs to the MATCH-UP line
  // above, and giving it to both would leave neither looking like the subject.
  bucketName: { ...T.smallMed, color: C.ink, flexShrink: 1 },
  bucketCount: { ...T.smallMed, opacity: 0.75 },
  // The same 🤞 the score cards use for a pick, at the same size.
  mineMark: { fontSize: 14, lineHeight: leading(18), marginLeft: 2 },
  // Indented under their heading, so an open bucket reads as belonging to it.
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6,
           paddingLeft: 20, paddingBottom: S.xs },
  chip: {
    backgroundColor: C.raised, borderRadius: R.sm, borderWidth: 1, borderColor: C.border,
    paddingHorizontal: 9, paddingVertical: 4, maxWidth: '100%',
  },
  chipText: { ...T.tiny, color: C.inkBody },
  err: { ...T.small, color: C.bad, textAlign: 'center', paddingVertical: S.md },
  /* A ruled footer: a hairline across the sheet above "Close", and less
     height than the button used to take on its own. */
  close: {
    alignSelf: 'stretch', alignItems: 'center', marginHorizontal: -S.md, marginTop: S.sm,
    paddingVertical: S.xs, borderTopWidth: 1, borderColor: C.borderOn,
  },
  closeText: { ...T.smallMed, color: C.clay },
})
