/*
 * The site's bracket, one round at a time.
 *
 * Ported from frontend/src/components/CombinedView.jsx and CombinedView.css —
 * the anatomy and the numbers, not an impression of them. Every measurement
 * and colour here has a line in one of those two files.
 *
 * WHAT A MATCH GROUP IS, because it is not what it looks like. The outline
 * holds one match of the round on screen, but the two boxes inside are NOT
 * that match's players from the data. Each is the winner of one FEEDER match
 * AS YOU PREDICTED — your pick, falling back to the real winner — coloured by
 * whether that pick came off: green if it did, red if it did not (or your
 * player was already knocked out), with the real winner's name printed across
 * the top border of a red box. So the colours on the R16 screen are your R32
 * picks being graded, and your R16 pick is the box you will find on the QF
 * screen. The bracket is the record of your picks, not a list of matches.
 * The one thing said about THIS match's pick is the 🤞 after the name you
 * chose, and the 🔔 in the gap when that choice is the lower-ranked player.
 *
 * THE GAP BETWEEN THE BOXES BELONGS TO THE MATCH. The status pill rides the
 * outline's top border; the expected start, the running score or the final
 * score sits centred in the gap, keeping clear of the bell's corner when
 * there is a bell. The site moves a finished score to the next round's box;
 * here it stays in the gap, so a green tick beside the winner's name says who
 * won — with no next column on screen, something has to. The tick goes on
 * whichever name IS the winner, including the real-winner note above a wrong
 * pick, since the box under it holds someone who was never in the match.
 *
 * One column, full width. The site stacks its phone labels on two lines
 * because its compact column is 107pt wide; this one is three times that,
 * so the ETA and the live score take one line each.
 */
import { useMemo, useState } from 'react'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { FONT_SCALE, leading } from './fontScale.js'
import { textWidth } from './measure.js'
import { expectedStartLabel } from './dates'
import { scoreLine, setCount } from './score'
import { matchStarted } from './scoreHistory'
import { EntryChip, PosBadge } from './cards'
import { C, PICK } from './theme'

/* ── Tokens, from the site's DARK theme (frontend/src/index.css) ─────────── */
const N = { 950: '#f2f6f4', 400: '#6f817a', 300: '#3f524b', 200: '#2b3a35', 150: '#212e29', 100: '#18241f' }
const ETA = { text: '#a5b4fc', bg: '#1e1b4b' }                 // --eta-text / --eta-bg
const LIVE = { text: C.info, bg: '#14243d', line: C.atp }      // --info / --atp-tint / --atp-500
const STOP = { text: '#e0a340', bg: '#2a2010' }                // --warning / --warning-tint
const DANGER_STRONG = '#ffb0a8'
const CHIP = { line: '#40916c', text: '#5fbf8f' }              // --green-500 / --brand-text
const CONNECTOR = '#47876a'                                    // --connector-line
/* The site's point pill falls through to its LIGHT fallbacks in dark mode
   (dark green on a faint green tint) — a bug there, not a design to copy.
   Same tint, legible ink. */
const POINT = { bg: 'rgba(123,168,31,0.28)', fg: C.greenBright }
const POINT_TB = { bg: 'rgba(234,88,12,0.28)', fg: '#f0b478' }

/* ── Geometry (CombinedView: BOX_H, the outline's pads, the chips) ───────── */
const BOX_H = 32
const GAP_H = 30          // one line of ETA or score, and the bell's height
const PAD = 12            // outline overhang 8 + slot inset 4, on every side
const PILL_H = 16
/* The pill BEFORE rotation. The site's is 34×18 around 12.5px type; this one
   is a size up and SCALES with the type — at a fixed 34 the text filled it
   end to end on a phone with larger text. */
const CHIP_W = 40
const CHIP_H = 20
const CONN_RUN = 12       // border → the vertical bar
const CONN_STUB = 10      // the bar → off to the next round
const BELL_CORNER = 42    // .cv-eta--bell / .cv-live-score--bell: right: 42px
const NAME_FONT = 13      // 0.8rem
const NAME_FAMILY = 'Archivo_700Bold'
const PICK_PX = 24        // room the 🤞 takes after a name
/* The real-winner note's fill, in unscaled points (see realWinner below).
   Cap height is Archivo's 686/1000 at 11pt; where the caps start is the
   phone's, not the table's. */
const NOTE_CAP_H = 7.55
const NOTE_CAP_TOP = 3.7
const NOTE_PAD = 1
const NOTE_BOX_H = (NOTE_CAP_H + 2 * NOTE_PAD) * FONT_SCALE
const TICK_PX = 22        // and the winner's ✓, with its leading space
export const CONNECTOR_W = 2 + CONN_RUN + CONN_STUB   // beyond the outline's outer edge
/* How far the chips poke past the outline's outer edge — SCALED, because the
   chip's short side is leading(18): on a phone with larger text the pill is
   ~23pt across, and a fixed 8 here had RoundScrub's clip slicing its left
   third off. Rounded up, with the border's point of slack left in. */
export const CHIP_OVERHANG = Math.ceil(leading(CHIP_H) / 2)

/* ── The model ───────────────────────────────────────────────────────────────
   Everything a group needs that is about the DRAW rather than the match:
   who fed whom, whose pick stands where, who has already lost. Built once
   per fetch, not per row — resolve() walks the whole bracket. */
export function buildBracket(matches, entries, picks) {
  const byRound = new Map()
  for (const m of matches) {
    if (!byRound.has(m.round_number)) byRound.set(m.round_number, [])
    byRound.get(m.round_number).push(m)
  }
  const rounds = [...byRound.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([n, list]) => [n, [...list].sort((a, b) => (a.match_number ?? 0) - (b.match_number ?? 0))])

  const byKey = new Map()
  for (const m of matches) byKey.set(`${m.round_number}:${m.match_number}`, m)

  const playerById = {}
  for (const e of entries || []) playerById[e.id] = e
  // A match's own player objects fill any gap — same shape, DrawEntryOut.
  for (const m of matches) for (const p of [m.player1, m.player2, m.winner]) {
    if (p && !playerById[p.id]) playerById[p.id] = p
  }

  // Round each player was actually knocked out in. A pick of them as the
  // winner of that round or any later one is dead, and shown wrong now rather
  // than waiting for the picked match to be played.
  const lossRound = {}
  for (const m of matches) {
    const wid = m.winner?.id
    if (wid == null || m.is_bye) continue
    const loserId = m.player1?.id === wid ? m.player2?.id : m.player1?.id
    if (loserId != null) lossRound[loserId] = m.round_number
  }

  // Unplaced qualifier slots numbered by bracket position, as the site does.
  const qualifierNums = {}
  Object.values(playerById)
    .filter(p => p.entry_type === 'Q' && !p.name)
    .sort((a, b) => (a.bracket_position ?? 0) - (b.bracket_position ?? 0))
    .forEach((p, i) => { qualifierNums[p.id] = i + 1 })

  // A shortened form that two players in this draw would share is never
  // used for either — telling them apart matters more than the pixels.
  const nameCounts = {}
  for (const p of Object.values(playerById)) {
    if (!p.name) continue
    const parts = p.name.trim().split(/\s+/)
    for (const f of new Set([lastNameOf(p.name), parts[parts.length - 1]])) {
      nameCounts[f] = (nameCounts[f] || 0) + 1
    }
  }

  const resolved = resolveCombinedPlayers(matches, picks, byKey)
  return { rounds, byKey, playerById, picks, resolved, lossRound, qualifierNums, nameCounts }
}

/* Each match's two feeder players the way the boxes show them: R1 straight
   from the draw; R2+ the PICKED winner of each feeder, falling back to the
   real one. A pick only counts when the picked player is one of that match's
   own resolved feeders — an orphaned pick must not cascade a player into
   rounds their bracket path never reaches. (CombinedView.resolveCombinedPlayers) */
function resolveCombinedPlayers(matches, picks, byKey) {
  const resolved = {}
  function getAdvancer(m) {
    if (!m) return null
    if (m.is_bye) return m.player1?.id ?? null
    const r = resolved[m.id]
    const pick = picks?.get(m.id) ?? null
    const pickValid = pick != null && r != null && (pick === r.p1 || pick === r.p2)
    return (pickValid ? pick : null) ?? m.winner?.id ?? null
  }
  function resolve(m) {
    if (resolved[m.id]) return resolved[m.id]
    let p1 = m.round_number === 1 ? (m.player1?.id ?? null) : null
    let p2 = m.round_number === 1 ? (m.player2?.id ?? null) : null
    if (m.round_number > 1) {
      const f1 = byKey.get(`${m.round_number - 1}:${m.match_number * 2 - 1}`)
      const f2 = byKey.get(`${m.round_number - 1}:${m.match_number * 2}`)
      if (f1) resolve(f1)
      if (f2) resolve(f2)
      p1 = f1 ? getAdvancer(f1) : null
      p2 = f2 ? getAdvancer(f2) : null
    }
    resolved[m.id] = { p1, p2 }
    return resolved[m.id]
  }
  for (const m of matches) resolve(m)
  return resolved
}

/* THE SITE'S NAME LADDER, not the app's. names.js initialises every given
   name ("F. D. Acosta"), which is right for a schedule row and wrong beside
   the site's bracket, which prints "F. DÍAZ ACOSTA" for the same man: it
   treats everything after the first token as the surname, tries that
   reading first, and keeps the bare final word for when it does not fit.
   The two ladders are different answers to "where does the surname start",
   and a bracket the reader has already seen on the site must give the
   site's. (CombinedView.nameForms / abbrevName / lastNameOf) */
function nameForms(full) {
  const parts = full.trim().split(/\s+/)
  if (parts.length === 1) return [full]
  const rest = parts.slice(1).join(' ')
  return [full, `${parts[0][0]}. ${rest}`, rest, parts[parts.length - 1]]
}

/* "L. Darderi" — the real winner's note over a wrong box. (abbrevName) */
function abbrevName(full) {
  if (!full) return ''
  return nameForms(full)[1] ?? full
}

function lastNameOf(full) {
  const parts = full.trim().split(/\s+/)
  return parts.length > 1 ? parts.slice(1).join(' ') : parts[0]
}

/* ── The two boxes ──────────────────────────────────────────────────────────
   R1 (entrantBox): the draw as drawn. Which line of a bye match the player
   takes is not in the data — ATP 7.16/7.18 put a bye'd seed on the OUTER
   line, so odd-numbered match = player on top, even = bye on top. Display
   only; bracket_position is untouched. */
function entrantBox(m, side, B) {
  const playerSlot = m.is_bye && m.match_number % 2 === 0 ? 1 : 0
  const pid = m.is_bye
    ? (side === playerSlot ? m.player1?.id ?? null : null)
    : ((side === 0 ? m.player1?.id : m.player2?.id) ?? null)
  return {
    player: pid != null ? B.playerById[pid] ?? null : null, playerId: pid, realId: pid,
    isBye: m.is_bye && side !== playerSlot, correct: false, wrong: false, realName: null,
  }
}

/* R2+ (winnerBox): the feeder's winner as you predicted, graded. */
function feederBox(m, side, B) {
  const f = B.byKey.get(`${m.round_number - 1}:${m.match_number * 2 - 1 + side}`)
  if (!f) return { player: null, playerId: null, realId: null, isBye: false, correct: false, wrong: false, realName: null }
  const realId = f.winner?.id ?? (f.is_bye ? f.player1?.id ?? null : null)
  const pickId = B.picks?.get(f.id) ?? null
  const displayId = pickId ?? realId
  const correct = pickId != null && realId != null && pickId === realId
  const dead = pickId != null && B.lossRound[pickId] != null && B.lossRound[pickId] <= f.round_number
  const wrong = pickId != null && ((realId != null && pickId !== realId) || dead)
  const realPlayer = realId != null ? B.playerById[realId] : null
  return {
    player: displayId != null ? B.playerById[displayId] ?? null : null, playerId: displayId,
    realId, isBye: false, correct, wrong,
    realName: wrong && realPlayer ? abbrevName(realPlayer.name) : null,
  }
}

/* The box's name: UPPERCASE, starting from the initial form ("A. ZVEREV"),
   stepping to the surname, then shrinking — never cut. Measured from the
   font's own metrics against the width the row actually gave it, exactly as
   PlayerName does; this differs from it only in where the ladder starts and
   in the collision rule. (slotName) */
function BoxName({ player, B, won, picked }) {
  const unnamedQ = player?.entry_type === 'Q' && !player?.name
  const forms = useMemo(() => {
    if (!player) return ['TBD']
    if (unnamedQ) {
      const n = B.qualifierNums[player.id]
      return [`Qualifier${n != null ? ` ${n}` : ''}`.toUpperCase()]
    }
    const all = nameForms(player.name)
    const start = all.length > 1 ? 1 : 0
    const chain = []
    for (let i = start; i < all.length; i++) {
      const f = all[i]
      if (i > start && (f === chain[chain.length - 1] || B.nameCounts[f] > 1)) continue
      chain.push(f)
    }
    return chain.map(f => f.toUpperCase())
  }, [player, unnamedQ, B])
  const [avail, setAvail] = useState(null)

  let text = forms[0]
  let fontSize = NAME_FONT
  if (avail != null) {
    const room = avail - 1 - (picked ? PICK_PX : 0) - (won ? TICK_PX : 0)
    const fits = forms.find(f => textWidth(f, NAME_FAMILY, NAME_FONT) <= room)
    if (fits) text = fits
    else {
      text = forms[forms.length - 1]
      fontSize = Math.max(6, (NAME_FONT * room) / textWidth(text, NAME_FAMILY, NAME_FONT))
    }
  }
  const muted = unnamedQ
  return (
    <View style={s.nameSlot} onLayout={e => setAvail(e.nativeEvent.layout.width)}>
      <Text style={[s.name, muted && s.nameMuted, fontSize !== NAME_FONT && { fontSize }]}
            numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.3}>
        {text}
      </Text>
      {won && <Text style={s.tick} accessibilityLabel="Won"> ✓</Text>}
      {picked && (
        <Text style={s.pick} accessibilityLabel="You predicted this player to win">🤞</Text>
      )}
    </View>
  )
}

/* The site's ball, in Views: a green disc with a dark rim and two white
   seams — arcs of larger circles clipped to the disc. */
function TennisBall() {
  return (
    <View style={s.ball}>
      <View style={[s.seam, { left: -13, top: -13 }]} />
      <View style={[s.seam, { left: 3, top: 3 }]} />
      <View style={s.ballRim} />
    </View>
  )
}

function PlayerBox({ box, serving, picked, won, noteWon, drawRanks, B }) {
  const p = box.player
  const tone = box.isBye ? s.boxBye
    : box.correct ? s.boxCorrect
    : box.wrong ? s.boxWrong
    : !p ? s.boxTbd : null
  return (
    <View>
      <View style={[s.box, tone]}>
        {box.isBye ? (
          <Text style={[s.name, s.nameMuted, { marginLeft: 6 }]}>BYE</Text>
        ) : (
          <>
            {p && (
              <View style={s.badge}>
                <PosBadge seed={p.seed} drawRank={drawRanks?.[p.id]} />
              </View>
            )}
            <BoxName player={p} B={B} won={won} picked={picked} />
            {serving && <TennisBall />}
            {p && <EntryChip entryType={p.entry_type} />}
          </>
        )}
      </View>
      {/* Painted after the box so it sits on the border; its fill masks the
          border segment under the letters, as the site's does. */}
      {/* A row, not one Text with a nested span: a leading space inside a
          nested Text is at the platform's mercy, and the tick sat hard
          against the name on the phone. The gap here is the same air the
          box's own tick gets. */}
      {box.realName && (
        <View style={s.realWinner}>
          <Text style={s.realWinnerText} numberOfLines={1}>{box.realName.toUpperCase()}</Text>
          {noteWon && <Text style={[s.realWinnerText, s.noteTick]} accessibilityLabel="Won">✓</Text>}
        </View>
      )}
    </View>
  )
}

/* A pill on the outline's border, rotated to read upwards. `side` picks the
   border. The layout box is the unrotated 34×18; the transform turns it in
   place, so the centre stays where the layout put it — on the border line. */
function Chip({ side, onPress, label, children }) {
  return (
    <View style={[s.chipWrap, side === 'left' ? { left: -(leading(CHIP_W) / 2) - 1 } : { right: -(leading(CHIP_W) / 2) - 1 }]}
          pointerEvents="box-none">
      <Pressable onPress={onPress} hitSlop={10} style={s.chip} accessibilityRole="button"
                 accessibilityLabel={label}>
        {children}
      </Pressable>
    </View>
  )
}

/* The elbow out of the pair: a run from each box's centre, the bar joining
   them, and a stub towards the round these two feed. (Connectors) */
function Connector() {
  const y1 = PAD + leading(BOX_H) / 2
  const y2 = PAD + leading(BOX_H) + leading(GAP_H) + leading(BOX_H) / 2
  const w = 1.5
  return (
    <View style={s.conn} pointerEvents="none">
      <View style={[s.connLine, { left: 0, top: y1 - w / 2, width: CONN_RUN + w / 2, height: w }]} />
      <View style={[s.connLine, { left: 0, top: y2 - w / 2, width: CONN_RUN + w / 2, height: w }]} />
      <View style={[s.connLine, { left: CONN_RUN - w / 2, top: y1 - w / 2, width: w, height: y2 - y1 + w }]} />
      <View style={[s.connLine, { left: CONN_RUN, top: (y1 + y2) / 2 - w / 2, width: CONN_STUB, height: w }]} />
    </View>
  )
}

/* The running score, the site's way: the snapshot's games when it is fresh
   (so the point beside them describes the same instant), else the feed's.
   Steps its type down as sets accumulate, since the gap has height to spare
   and no width to spare. */
function LiveScore({ m, suspended, bell }) {
  const games = m.live_point?.games ?? null
  const sets = games ? [games[0], games[1]] : m.live_scores
  const line = scoreLine(sets, ', ')
  if (!line) return null
  const n = setCount(sets)
  const fontSize = n >= 5 ? 14 : n === 4 ? 15 : 17
  const pts = m.live_point?.point ?? null
  const showPts = !!pts && pts.some(v => v != null)
  const tb = !!m.live_point?.tiebreak
  return (
    <View style={[s.gapLine, bell && s.gapLineBell]} pointerEvents="none">
      <Text style={[s.live, suspended && s.liveStopped, { fontSize }]} numberOfLines={1}>{line}</Text>
      {showPts && (
        <View style={[s.point, tb && s.pointTb, suspended && { opacity: 0.55 }]}>
          <Text style={[s.pointText, tb && s.pointTbText]}>{`${pts[0] ?? '0'}-${pts[1] ?? '0'}`}</Text>
        </View>
      )}
    </View>
  )
}

export function MatchGroup({ m, roundIdx, B, drawRanks, zone, onH2H, onPredictors, onShowScore }) {
  const top = roundIdx === 0 ? entrantBox(m, 0, B) : feederBox(m, 0, B)
  const bot = roundIdx === 0 ? entrantBox(m, 1, B) : feederBox(m, 1, B)

  const decided = !!m.winner
  const live = !decided && !m.is_bye && !!(m.live_scores || m.live_point)
  const suspended = live && m.live_scores?.[4] === 'suspended'
  const winnerId = m.winner?.id ?? null

  /* THIS match's pick: the 🤞, and the bell when it is the lower-ranked of
     the two resolved feeders. Both stay put after the result — a pick is a
     record, not a live control. */
  const pickId = B.picks?.get(m.id) ?? null
  const { p1: rA, p2: rB } = B.resolved[m.id] || {}
  const rankA = rA != null ? drawRanks?.[rA] : null
  const rankB = rB != null ? drawRanks?.[rB] : null
  const bell = pickId != null && rankA != null && rankB != null
    && pickId !== (rankA <= rankB ? rA : rB)

  // live_scores[2] is 1 or 2 for p1/p2 — the top and bottom line.
  const serving = live ? (m.live_scores?.[2] ?? m.live_point?.serving ?? null) : null

  /* H2H compares who REALLY meets, the cascade only until that is known
     (resolveRealFirst). Both matched to a Tennis Explorer profile, or no
     button: the endpoint has nothing to say about a player it never matched. */
  const hA = m.player1 ?? (rA != null ? B.playerById[rA] : null)
  const hB = m.player2 ?? (rB != null ? B.playerById[rB] : null)
  const canH2H = !!(hA?.name && hB?.name && hA.te_slug && hB.te_slug)

  const pill = live ? (suspended ? 'SUSPENDED' : 'IN PROGRESS')
    : (!decided && !m.is_bye && m.expected_start_at ? 'SCHEDULED' : null)
  const pillTone = pill === 'SCHEDULED' ? s.pillScheduled : pill === 'SUSPENDED' ? s.pillSuspended : s.pillLive

  let gap = null
  if (live) {
    gap = <LiveScore m={m} suspended={suspended} bell={bell} />
  } else if (decided && !m.is_bye) {
    const line = scoreLine(m.scores, ', ')
    if (line) gap = (
      <View style={[s.gapLine, bell && s.gapLineBell]} pointerEvents="none">
        <Text style={s.finalScore} numberOfLines={1}>{line}</Text>
      </View>
    )
  } else if (!m.is_bye && m.expected_start_at) {
    const label = expectedStartLabel(m.expected_start_at, m.expected_source, zone)
    if (label) gap = (
      <View style={[s.gapLine, bell && s.gapLineBell]} pointerEvents="none">
        <Text style={s.eta} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.7}>{label}</Text>
      </View>
    )
  }

  /* WHO WON, once decided: a tick beside the winner's name wherever that name
     is. In the box when the box shows them; on the real-winner note when the
     box holds a wrong pick and the person who actually won this match is the
     one named above it. Both names stay white — a dimmed loser read as a
     fault, and dimmed BOTH of them whenever neither box held the winner. */
  const wonBy = box => decided && box.playerId != null && box.playerId === winnerId
  const noteWonBy = box => decided && !!box.realName && box.realId === winnerId
    && box.playerId !== winnerId

  // A started match answers a tap with its score and history — its pick is
  // locked by then, so the tap is free to mean "show me".
  const openable = !!onShowScore && matchStarted(m)
  const Wrap = openable ? Pressable : View

  return (
    <Wrap style={s.outline} onPress={openable ? () => onShowScore(m) : undefined}>
      {pill && (
        <View style={s.pillWrap} pointerEvents="none">
          <View style={[s.pill, pillTone]}>
            <Text style={[s.pillText, { color: pillTone.borderColor }]}>{pill}</Text>
          </View>
        </View>
      )}
      <PlayerBox box={top} B={B} drawRanks={drawRanks}
                 serving={serving === 1} picked={pickId != null && pickId === top.playerId}
                 won={wonBy(top)} noteWon={noteWonBy(top)} />
      <View style={s.gap}>
        {gap}
        {bell && <Text style={s.bell} accessibilityLabel="Upset pick">🔔</Text>}
      </View>
      <PlayerBox box={bot} B={B} drawRanks={drawRanks}
                 serving={serving === 2} picked={pickId != null && pickId === bot.playerId}
                 won={wonBy(bot)} noteWon={noteWonBy(bot)} />
      {/* The predictors chip on the LEFT border, on every real match —
          decided, it says who called it; not yet, whose pick still stands. */}
      {!m.is_bye && onPredictors && (
        <Chip side="left" onPress={() => onPredictors(m)}
              label={decided ? 'Who called it' : 'Who’s still in it'}>
          <Ionicons name="people" size={16} color={CHIP.text} style={s.chipIcon} />
        </Chip>
      )}
      {canH2H && onH2H && (
        <Chip side="right" label={`Head-to-head: ${hA.name} vs ${hB.name}`}
              onPress={() => onH2H({ a: { name: hA.name, te_slug: hA.te_slug },
                                     b: { name: hB.name, te_slug: hB.te_slug } })}>
          <Text style={s.chipText}>H2H</Text>
        </Chip>
      )}
      <Connector />
    </Wrap>
  )
}

const s = StyleSheet.create({
  /* .cv-match-outline: 2px n-300, radius 10, n-150 fill. */
  outline: {
    borderWidth: 2, borderColor: N[300], borderRadius: 10, backgroundColor: N[150],
    paddingVertical: PAD, paddingHorizontal: PAD,
  },
  /* .in-progress-badge: centred on the outline's top border. top is measured
     from inside the border, so -1 puts the pill's centre on the border's own
     centre line. */
  pillWrap: {
    position: 'absolute', left: 0, right: 0, top: -(leading(PILL_H) / 2) - 1,
    alignItems: 'center', zIndex: 3,
  },
  pill: {
    height: leading(PILL_H), borderRadius: 999, borderWidth: 1,
    paddingHorizontal: 8, justifyContent: 'center',
  },
  /* NO lineHeight ON ANY SINGLE-LINE TEXT IN THIS FILE — see the note on
     realWinnerText below. Every one of these sits in a container that
     centres it, and on iOS a lineHeight only ever sinks the glyphs. */
  pillText: { fontFamily: 'Archivo_700Bold', fontSize: 9.5, letterSpacing: 0.8 },
  pillScheduled: { backgroundColor: ETA.bg, borderColor: ETA.text },
  pillLive: { backgroundColor: LIVE.bg, borderColor: LIVE.line },
  pillSuspended: { backgroundColor: STOP.bg, borderColor: STOP.text },

  /* .cv-box: 32 tall, radius 5, 1px n-400 on n-200, padding 0 8px 0 3px. */
  box: {
    height: leading(BOX_H), borderRadius: 5, borderWidth: 1, borderColor: N[400],
    backgroundColor: N[200], flexDirection: 'row', alignItems: 'center',
    paddingLeft: 3, paddingRight: 8,
  },
  boxCorrect: { backgroundColor: PICK.correct.bg, borderColor: PICK.correct.border },
  boxWrong: { backgroundColor: PICK.wrong.bg, borderColor: PICK.wrong.border },
  boxTbd: { borderColor: PICK.needs.border },
  boxBye: { backgroundColor: N[100], borderStyle: 'dashed' },
  // .cv-scroll--compact .cv-badges { margin-right: 6px }
  badge: { marginRight: 6 },
  nameSlot: { flex: 1, minWidth: 0, flexDirection: 'row', alignItems: 'center', gap: 4 },
  name: { fontFamily: NAME_FAMILY, fontSize: NAME_FONT, color: N[950], flexShrink: 1 },
  nameMuted: { fontFamily: 'Archivo_500Medium', fontStyle: 'italic', color: C.muted },
  pick: { fontSize: 14 },
  // The winner's tick, in the pick-correct green the box already uses.
  tick: { fontFamily: 'Archivo_700Bold', fontSize: 14, color: PICK.correct.border },
  noteTick: { color: PICK.correct.border },
  /* .cv-real-winner: 11px, centred on the box's top border, the wrong fill
     behind it. */
  /* NO lineHeight ON THIS TEXT. On iOS, whatever a lineHeight adds beyond
     the font's own line goes ABOVE the glyphs, so a 15pt line put the caps
     on the floor of the strip with the air all over them — and a 13pt line
     did the same from the other side. Archivo's natural line is 1.088em
     (ascender 878, descender 210) with a 686 cap height, which leaves
     0.19em above the caps and 0.21em below: centred to a tenth of a point
     on its own. The strip is a hair taller than that line and the row's
     alignItems does the rest. It still straddles the border: top is half
     its own height. */
  /* THE FILL HUGS THE CAPITALS, not the line box. A Text paints its
     background over its whole line (12pt for 11pt Archivo), and that strip
     ran down over the seed badge. So the fill is the container's, sized to
     the cap height plus a point each side, and the text is pulled up inside
     it by a negative margin so its capitals land in the fill; the rest of
     the line box hangs outside, invisibly.

     NOTE_CAP_TOP IS CALIBRATED FROM THE PHONE (2026-09-08), not from the
     metrics: with no lineHeight, iOS draws the caps 3.7pt below the top of
     the text's box, where the font tables say 2.1 — and the harness draws
     what the tables say. The box sits 4pt above the border line and 5.6pt
     inside it, which is where the site's own note sits and clear of the
     badge, whose top is 7pt in. */
  realWinner: {
    position: 'absolute', left: 7, top: -4 * FONT_SCALE,
    height: NOTE_BOX_H, paddingHorizontal: 1.5 * FONT_SCALE, gap: 7,
    flexDirection: 'row', alignItems: 'flex-start',
    backgroundColor: PICK.wrong.bg, zIndex: 2,
  },
  realWinnerText: {
    fontFamily: 'Archivo_700Bold', fontSize: 11, color: DANGER_STRONG,
    marginTop: -(NOTE_CAP_TOP - NOTE_PAD) * FONT_SCALE,
  },

  gap: { height: leading(GAP_H), justifyContent: 'center' },
  gapLine: {
    position: 'absolute', left: 0, right: 0, top: 0, bottom: 0,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 7,
  },
  gapLineBell: { right: BELL_CORNER },
  // .cv-eta--roomy: bold, eta-text, tabular.
  eta: { fontFamily: 'Archivo_700Bold', fontSize: 15, color: ETA.text, fontVariant: ['tabular-nums'] },
  // .cv-live-score: 1.05rem 700 --info.
  live: { fontFamily: 'Archivo_700Bold', fontSize: 17, color: LIVE.text, fontVariant: ['tabular-nums'] },
  liveStopped: { color: STOP.text },
  // .cv-score: 0.92rem 600 text-muted.
  finalScore: { fontFamily: 'Archivo_700Bold', fontSize: 15, color: C.muted, fontVariant: ['tabular-nums'] },
  point: { paddingHorizontal: 6, paddingVertical: 1, borderRadius: 5, backgroundColor: POINT.bg },
  pointTb: { backgroundColor: POINT_TB.bg },
  pointText: { fontFamily: 'Archivo_700Bold', fontSize: 15, color: POINT.fg, fontVariant: ['tabular-nums'] },
  pointTbText: { color: POINT_TB.fg },
  /* .cv-bell: 1.5rem, in the gap's right corner, free to overlap the boxes. */
  bell: { position: 'absolute', right: 8, fontSize: 22, zIndex: 3 },

  /* .cv-h2h / .cv-group: 34×18 turned -90°, 1px green-500 on the card fill,
     centred on the outline's border at the pair's midpoint. */
  chipWrap: { position: 'absolute', top: 0, bottom: 0, justifyContent: 'center', zIndex: 4 },
  chip: {
    width: leading(CHIP_W), height: leading(CHIP_H), borderRadius: 4, borderWidth: 1,
    borderColor: CHIP.line, backgroundColor: C.card,
    alignItems: 'center', justifyContent: 'center', transform: [{ rotate: '-90deg' }],
  },
  /* A GEOMETRIC SHIFT, measured off the phone (2026-09-08). Inside the
     rotated pill iOS draws the word ~2pt (at the phone's 1.3 text scale)
     toward the pill's TOP end — the LEFT on screen — and padding on the
     text did not move it at all, so the correction is a translate, which
     nothing can ignore. +y here is the pill's own "down", which the -90°
     rotation turns into screen right. */
  chipText: {
    fontFamily: 'Archivo_700Bold', fontSize: 12, letterSpacing: 0.25, color: CHIP.text,
    transform: [{ translateY: 1.6 * FONT_SCALE }],
  },
  // Undo the pill's rotation so the glyph stands upright.
  chipIcon: { transform: [{ rotate: '90deg' }] },

  conn: { position: 'absolute', top: 0, bottom: 0, right: -CONNECTOR_W, width: CONN_RUN + CONN_STUB, zIndex: 0 },
  connLine: { position: 'absolute', backgroundColor: CONNECTOR },

  // TennisBall: 16px, #7ba81f, rim #1b4332, white seams.
  ball: { width: 16, height: 16, borderRadius: 8, backgroundColor: '#7ba81f', overflow: 'hidden', marginLeft: 4 },
  seam: { position: 'absolute', width: 26, height: 26, borderRadius: 13, borderWidth: 2, borderColor: '#fff' },
  ballRim: { position: 'absolute', left: 0, top: 0, width: 16, height: 16, borderRadius: 8, borderWidth: 2, borderColor: '#1b4332' },
})
