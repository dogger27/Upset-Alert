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
import { useContext, useMemo, useState } from 'react'
import { Animated, Pressable, StyleSheet, Text, View } from 'react-native'
import Reanimated, { useAnimatedStyle } from 'react-native-reanimated'
import { Ionicons } from '@expo/vector-icons'
import { Bump, NeonRing, useStandoutShake } from './fx'
import { useFlashOnChange } from './scoreFx'
import { FONT_SCALE, leading } from './fontScale.js'
import { textWidth } from './measure.js'
import { expectedStartLabel } from './dates'
import { scoreLine, setCount } from './score'
import { matchStarted } from './scoreHistory'
import { EntryChip, PosBadge } from './cards'
import { C, PICK, S } from './theme'
import { ScrubContext } from './scrubContext'
import { boxOffset } from './scrubGeometry'

/* ── Tokens, from the site's DARK theme (frontend/src/index.css) ─────────── */
const N = { 950: '#f2f6f4', 400: '#6f817a', 300: '#3f524b', 200: '#2b3a35', 150: '#212e29', 100: '#18241f' }
const ETA = { text: '#a5b4fc', bg: '#1e1b4b' }                 // --eta-text / --eta-bg
/* The live pill's edge and word, and the running score in the gap, are ONE
   blue — the site's --atp-text, light enough to read on the tint. The pill
   used --atp-500 for its edge and word, a saturated mid blue that sat dark
   on the dark fill and did not match the score under it. */
const LIVE = { text: '#8fb6ff', bg: '#14243d', line: '#8fb6ff' }
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
/* SCALED DOWN FROM THE SITE'S 32/30/12 by about 0.85 (owner, 2026-09-08):
   four matches have to fit a screen at the phone's larger text size, and
   at the site's numbers three and a bit did. The type comes down a point
   or two with the boxes, so nothing is squeezed into a box that shrank
   around it. */
const BOX_H = 28
const GAP_H = 24          // one line of ETA or score, and the bell's height
const PAD = 8             // inside the outline, sides and bottom
/* More at the top than the bottom: the status pill straddles the top
   border and its lower half reaches ~11pt inside at the phone's text size,
   which at 8 ran over the top box's own border. */
const PAD_TOP = 12
const PILL_H = 15
/* The pill BEFORE rotation. The site's is 34×18 around 12.5px type; this one
   is a size up and SCALES with the type — at a fixed 34 the text filled it
   end to end on a phone with larger text. */
const CHIP_W = 40
const CHIP_H = 24         // the on-screen WIDTH of the rotated pill; 24 at the owner's ask
/* The feeder runs go PAST the H2H pill before the bar joins them — the pill
   is centred on the border and reaches ~17pt beyond it at the phone's text
   size, and a bar at 12 was hidden behind it. The stub then runs on to the
   screen's edge: the column is padded only as far as the bar, and the
   stub overflows into the strip's extra width (the screen padding the draw
   reclaims for it) until the glass cuts it. */
const CONN_RUN = 24       // border → the vertical bar, clear of the pill
/* The bar → the edge of the glass, and NO FURTHER. The column's right
   padding is CONNECTOR_W plus the screen's S.lg, so this is what remains
   past the bar; a few points of slack for rounding. At 120 the stub ran on
   into the NEXT round's column, under its predictors chip, and showed there
   as a third line out of the middle of every match (owner, 2026-09-08). */
const CONN_STUB = S.lg + 8
const BELL_CORNER = 42    // .cv-eta--bell / .cv-live-score--bell: right: 42px
const NAME_FONT = 12      // the site's 0.8rem, a point down with the box
const NAME_FAMILY = 'Archivo_700Bold'
const PICK_PX = 24        // room the 🤞 takes after a name
/* The real-winner note's fill, in unscaled points (see realWinner below).
   Cap height is Archivo's 686/1000 at 11pt; where the caps start is the
   phone's, not the table's. */
const NOTE_FONT = 10
const NOTE_CAP_H = 6.86            // 686/1000 at 10pt
const NOTE_PAD = 1
/* Where the text sits inside its fill, MEASURED OFF THE PHONE at 10pt
   (2026-09-08): the caps landed ~2.9pt above the border the fill is centred
   on, so the text is pushed down by that. The border is meant to pass
   through the middle of the letters. */
const NOTE_TEXT_SHIFT = 0.5
const NOTE_BOX_H = (NOTE_CAP_H + 2 * NOTE_PAD) * FONT_SCALE
/* How far the note stands up into the gap above the lower box (its top is
   4pt above the box's edge), plus a little air — what the gap's content
   gives up when there is a note. */
const NOTE_RISE = 3 * FONT_SCALE     // 6 sat the text hard under the upper box (owner, 2026-09-08)
const TICK_PX = 22        // and the winner's ✓, with its leading space
export const CONNECTOR_W = 2 + CONN_RUN + 3   // room reserved beyond the outline: up to the bar
/* A group's height, borders included, for anyone laying groups out before
   they have measured one — the round scrub's first frame. Every group is
   this tall: the pill and the real-winner note are absolute, the gap is a
   fixed line, and a bye fills the same box. Measured groups override it. */
export const GROUP_H = 2 * 2 + PAD_TOP + PAD + 2 * leading(BOX_H) + leading(GAP_H)
/* How far the chips poke past the outline's outer edge — SCALED, because the
   chip's short side is leading(18): on a phone with larger text the pill is
   ~23pt across, and a fixed 8 here had RoundScrub's clip slicing its left
   third off. Rounded up, with the border's point of slack left in. */
export const CHIP_OVERHANG = Math.ceil(leading(CHIP_H) / 2)
/* The line each box ARRIVED on: from the round before, in at the box's own
   centre and off the left edge of the glass — the site's connector run into
   a box (owner, 2026-09-08). Exactly the column's left padding (CHIP_OVERHANG
   plus the screen's S.lg) and a little slack, so it reaches the glass and
   not the previous round's column. Not on the first round, whose boxes came
   from the draw, not from a match. */
const CONN_IN = CHIP_OVERHANG + S.lg + 4

/* ── The group's box, in pieces, so a scrub can stretch it by TRANSFORM ──
   As the next round is pulled in, each of its groups starts tall enough
   that its two player boxes sit exactly on the centres of the two groups
   feeding it — the feed lines run straight into the boxes — and contracts
   to its settled height as it arrives; leaving to the left, a group's two
   boxes close together as it condenses toward the one box it becomes
   (owner, 2026-09-08). Changing a View's height every frame is a layout,
   so the outline is three views instead: a TOP CAP (top border, corners,
   sides) that slides up with the top box, a BOTTOM CAP that slides down with
   the bottom box, and a short MIDDLE with only side borders that is scaled
   in Y to bridge them — a scaled rectangle with no corners distorts nothing.
   Each cap is half the settled height, so at rest they meet in the middle
   over the bridge. The chips and the gap's content stay on the centre line. */
const BW = 2                                   // the outline's border
const BOX_PX = leading(BOX_H)
const GAP_PX = leading(GAP_H)
export const BOX_PITCH = BOX_PX + GAP_PX       // settled distance between the two boxes' centres
const CAP_H = Math.ceil(GROUP_H / 2)
const MID_H = 24
const LINE_W = 1.5
const Y_TOP = PAD_TOP + BOX_PX / 2             // the top box's centre, inside the cap's border
const Y_BOT = PAD + BOX_PX / 2                 // the bottom box's centre, up from the bottom cap's border
const BAR_LEN = BOX_PITCH + LINE_W

/** How far each half of a group has moved from where it sits settled, read
    off the scrub this group is riding (0 when there is none). */
function halfShift(sc) {
  'worklet'
  if (!sc.pos) return 0
  return boxOffset(sc.pos.value - sc.ri, sc.geo.value.G, sc.e) - sc.e
}

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
   seams. The site's SVG draws each seam as an arc of RADIUS HALF THE BALL
   centred on a corner — top-left and bottom-right — so each curves through
   its own quadrant. Here each seam is a circle of that radius, centred on
   the corner and clipped by the disc; the first cut used far bigger
   circles and the arcs came out as one straight stripe. */
function TennisBall() {
  return (
    <View style={s.ball}>
      <View style={[s.seam, { left: -BALL / 2, top: -BALL / 2 }]} />
      <View style={[s.seam, { left: BALL / 2, top: BALL / 2 }]} />
      <View style={s.ballRim} />
    </View>
  )
}
const BALL = 16

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
   place, so the centre stays where the layout put it — on the border line,
   BW/2 in from the group's outer edge. */
function Chip({ side, onPress, label, standout = false, children }) {
  // The site's .cv-group--standout: the shake around the whole rotated
  // pill, the neon ring inside it so it turns with it.
  const shake = useStandoutShake(standout)
  return (
    <View style={[s.chipWrap, side === 'left' ? { left: -(leading(CHIP_W) / 2) + BW / 2 } : { right: -(leading(CHIP_W) / 2) + BW / 2 }]}
          pointerEvents="box-none">
      <Animated.View style={standout ? { transform: shake, zIndex: 5 } : null}>
        <Pressable onPress={onPress} hitSlop={10} style={s.chip} accessibilityRole="button"
                   accessibilityLabel={label}>
          {children}
          <NeonRing on={standout} radius={4} />
        </Pressable>
      </Animated.View>
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
  const pts = m.live_point?.point ?? null
  const showPts = !!pts && pts.some(v => v != null)
  const label = showPts ? `${pts[0] ?? '0'}-${pts[1] ?? '0'}` : ''
  // The site's bump on the number that moves: hooks before any early return.
  const flash = useFlashOnChange(label)
  if (!line) return null
  const n = setCount(sets)
  const fontSize = n >= 5 ? 12 : n === 4 ? 13 : 15
  const tb = !!m.live_point?.tiebreak
  return (
    <View style={[s.gapLine, bell && s.gapLineBell]} pointerEvents="none">
      <Text style={[s.live, suspended && s.liveStopped, { fontSize }]} numberOfLines={1}>{line}</Text>
      {showPts && (
        <Bump on={flash && label !== ''}>
          <View style={[s.point, tb && s.pointTb, suspended && { opacity: 0.55 }]}>
            <Text style={[s.pointText, tb && s.pointTbText]}>{label}</Text>
          </View>
        </Bump>
      )}
    </View>
  )
}

export function MatchGroup({ m, roundIdx, B, drawRanks, zone, onH2H, onPredictors, onShowScore, standout = false }) {
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

  /* The scrub's stretch, if any: the caps slide apart or together with the
     boxes, the middle and the connector's bar scale to keep the outline and
     the elbow continuous. Four transforms; nothing here lays out per frame. */
  const sc = useContext(ScrubContext)
  const capTopStyle = useAnimatedStyle(() => ({ transform: [{ translateY: -halfShift(sc) }] }), [sc])
  const capBotStyle = useAnimatedStyle(() => ({ transform: [{ translateY: halfShift(sc) }] }), [sc])
  const midStyle = useAnimatedStyle(() => ({
    transform: [{ scaleY: Math.max(0.01, (MID_H + 2 * halfShift(sc)) / MID_H) }],
  }), [sc])
  const barStyle = useAnimatedStyle(() => ({
    transform: [{ scaleY: Math.max(0.01, (BAR_LEN + 2 * halfShift(sc)) / BAR_LEN) }],
  }), [sc])
  const done = decided && !m.is_bye

  return (
    <Wrap style={s.group} onPress={openable ? () => onShowScore(m) : undefined}>
      <Reanimated.View style={[s.mid, done && s.capDone, midStyle]} pointerEvents="none" />
      <Reanimated.View style={[s.cap, s.capTop, done && s.capDone, capTopStyle]}>
        {pill && (
          <View style={s.pillWrap} pointerEvents="none">
            <View style={[s.pill, pillTone]}>
              <Text style={[s.pillText, { color: pillTone.borderColor }]}>{pill}</Text>
            </View>
          </View>
        )}
        <View style={s.boxTop}>
          <PlayerBox box={top} B={B} drawRanks={drawRanks}
                     serving={serving === 1} picked={pickId != null && pickId === top.playerId}
                     won={wonBy(top)} noteWon={noteWonBy(top)} />
        </View>
        {/* The elbow's run out of this box, and the line it arrived on. */}
        <View style={[s.line, s.runTop]} pointerEvents="none" />
        {roundIdx > 0 && <View style={[s.line, s.inTop]} pointerEvents="none" />}
      </Reanimated.View>
      <Reanimated.View style={[s.cap, s.capBot, done && s.capDone, capBotStyle]}>
        <View style={s.boxBot}>
          <PlayerBox box={bot} B={B} drawRanks={drawRanks}
                     serving={serving === 2} picked={pickId != null && pickId === bot.playerId}
                     won={wonBy(bot)} noteWon={noteWonBy(bot)} />
        </View>
        <View style={[s.line, s.runBot]} pointerEvents="none" />
        {roundIdx > 0 && <View style={[s.line, s.inBot]} pointerEvents="none" />}
      </Reanimated.View>
      {/* THE NOTE TAKES ITS SHARE OF THE GAP. When the lower box carries a
          real-winner note, that note stands up into the gap, and anything
          centred on the gap's full height sat on top of it. The site's
          gapMid subtracts the note before centring; so does this — the
          content centres in what is left above the note, air included. */}
      <View style={s.gap} pointerEvents="none">
        <View style={[s.gapInner, bot.realName && { bottom: NOTE_RISE }]}>
          {gap}
          {bell && <Text style={s.bell} accessibilityLabel="Upset pick">🔔</Text>}
        </View>
      </View>
      {/* The bar joining the two runs, and the stub towards the next round. */}
      <Reanimated.View style={[s.line, s.bar, barStyle]} pointerEvents="none" />
      <View style={[s.line, s.stub]} pointerEvents="none" />
      {/* The predictors chip on the LEFT border, on every real match —
          decided, it says who called it; not yet, whose pick still stands. */}
      {!m.is_bye && onPredictors && (
        <Chip side="left" onPress={() => onPredictors(m)} standout={decided && standout}
              label={decided && standout ? `Standout pick: you called ${m.winner?.name}, which most of the field missed`
                     : decided ? 'Who called it' : 'Who’s still in it'}>
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
    </Wrap>
  )
}

const s = StyleSheet.create({
  /* .cv-match-outline: 2px n-300, radius 10, n-100 while the match is still
     to play — drawn as the three pieces described at BW above. The group
     itself is only the settled size; everything in it is placed absolutely. */
  group: { height: GROUP_H },
  cap: {
    position: 'absolute', left: 0, right: 0, height: CAP_H,
    borderLeftWidth: BW, borderRightWidth: BW, borderColor: N[300], backgroundColor: N[100],
    zIndex: 1,
  },
  capTop: { top: 0, borderTopWidth: BW, borderTopLeftRadius: 10, borderTopRightRadius: 10 },
  capBot: { bottom: 0, height: GROUP_H - CAP_H, borderBottomWidth: BW, borderBottomLeftRadius: 10, borderBottomRightRadius: 10 },
  mid: {
    position: 'absolute', left: 0, right: 0, top: CAP_H - MID_H / 2, height: MID_H,
    borderLeftWidth: BW, borderRightWidth: BW, borderColor: N[300], backgroundColor: N[100],
  },
  /* A finished match: a cool slate inside, a step brighter than the warm
     fill of a match still to play, and a teal edge — back at a member's
     suggestion, as an accent now that the fill carries the difference. The
     site's --match-done-fill / --match-done-line, dark. */
  capDone: { backgroundColor: '#263842', borderColor: '#2ec4b6' },
  // The boxes, inside their caps' borders, where the padding used to put them.
  boxTop: { position: 'absolute', top: PAD_TOP, left: PAD, right: PAD },
  boxBot: { position: 'absolute', bottom: PAD, left: PAD, right: PAD },
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
  pillText: { fontFamily: 'Archivo_700Bold', fontSize: 9, letterSpacing: 0.8 },
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
  pick: { fontSize: 13 },
  // The winner's tick, in the pick-correct green the box already uses.
  tick: { fontFamily: 'Archivo_700Bold', fontSize: 13, color: PICK.correct.border },
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
     the cap height plus a point each side and CENTRED ON THE BORDER LINE,
     and the text is placed inside it by NOTE_TEXT_SHIFT — a number measured
     off the phone, because iOS does not put the capitals where the font
     tables say and the harness draws what the tables say. The border is
     meant to pass through the middle of the letters. The fill's lower half
     stops short of the seed badge, whose top is 5pt in. */
  realWinner: {
    position: 'absolute', left: 7, top: -NOTE_BOX_H / 2,
    height: NOTE_BOX_H, paddingHorizontal: 1.5 * FONT_SCALE, gap: 7,
    flexDirection: 'row', alignItems: 'flex-start',
    // Above the status pill (3): where the two meet, the name wins.
    backgroundColor: PICK.wrong.bg, zIndex: 4,
  },
  /* AN EXPLICIT HEIGHT, TALLER THAN THE FILL. Without it Yoga measures the
     text against the fill's own height (cap height plus two points), the
     glyph frame comes out shorter than the line, and iOS clips the bottoms
     of the letters at the fill's edge. The frame paints nothing, so a tall
     one costs nothing; only the fill behind it is tight. */
  realWinnerText: {
    fontFamily: 'Archivo_700Bold', fontSize: NOTE_FONT, color: DANGER_STRONG,
    height: NOTE_FONT * 1.4 * FONT_SCALE,
    marginTop: NOTE_TEXT_SHIFT * FONT_SCALE,
  },

  // Between the two boxes, on the centre line, above the caps.
  gap: {
    position: 'absolute', left: BW + PAD, right: BW + PAD, top: BW + PAD_TOP + BOX_PX, height: GAP_PX,
    zIndex: 2,
  },
  // The part of the gap the content centres in: all of it, less the note.
  gapInner: { position: 'absolute', left: 0, right: 0, top: 0, bottom: 0, justifyContent: 'center' },
  gapLine: {
    position: 'absolute', left: 0, right: 0, top: 0, bottom: 0,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 7,
  },
  gapLineBell: { right: BELL_CORNER },
  // .cv-eta--roomy: bold, eta-text, tabular.
  eta: { fontFamily: 'Archivo_700Bold', fontSize: 13, color: ETA.text, fontVariant: ['tabular-nums'] },
  // .cv-live-score: 1.05rem 700 --info.
  live: { fontFamily: 'Archivo_700Bold', fontSize: 15, color: LIVE.text, fontVariant: ['tabular-nums'] },
  liveStopped: { color: STOP.text },
  // .cv-score: 0.92rem 600 text-muted.
  finalScore: { fontFamily: 'Archivo_700Bold', fontSize: 13, color: C.muted, fontVariant: ['tabular-nums'] },
  point: { paddingHorizontal: 6, paddingVertical: 1, borderRadius: 5, backgroundColor: POINT.bg },
  pointTb: { backgroundColor: POINT_TB.bg },
  pointText: { fontFamily: 'Archivo_700Bold', fontSize: 13, color: POINT.fg, fontVariant: ['tabular-nums'] },
  pointTbText: { color: POINT_TB.fg },
  /* .cv-bell: 1.5rem, in the gap's right corner, free to overlap the boxes. */
  bell: { position: 'absolute', right: 8, fontSize: 19, zIndex: 3 },

  /* .cv-h2h / .cv-group: 34×18 turned -90°, 1px green-500 on the card fill,
     centred on the outline's border at the pair's midpoint. */
  chipWrap: { position: 'absolute', top: BW + PAD_TOP - PAD, bottom: BW, justifyContent: 'center', zIndex: 4 },
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
    /* 0.7, down from 1.6: that moved the word past centre by about as much
       as it had been short — the shift lands at roughly twice its size
       on screen. Measured, not derived. */
    transform: [{ translateY: 0.4 * FONT_SCALE }],
  },
  // Undo the pill's rotation so the glyph stands upright.
  chipIcon: { transform: [{ rotate: '90deg' }] },

  /* The connector, in pieces that travel with the caps: a run out of each
     box (inside its cap, so it rides with the box), the bar between them
     (scaled with the stretch), the stub off the right edge on the centre
     line, and the lines the boxes arrived on, to the left. The runs and
     arrival lines are placed inside a cap's border box; the bar and stub in
     the group's. */
  line: { position: 'absolute', backgroundColor: CONNECTOR },
  runTop: { top: Y_TOP - LINE_W / 2, right: -(BW + CONN_RUN + LINE_W / 2), width: CONN_RUN + LINE_W / 2, height: LINE_W },
  runBot: { bottom: Y_BOT - LINE_W / 2, right: -(BW + CONN_RUN + LINE_W / 2), width: CONN_RUN + LINE_W / 2, height: LINE_W },
  inTop: { top: Y_TOP - LINE_W / 2, left: -(BW + CONN_IN), width: CONN_IN, height: LINE_W },
  inBot: { bottom: Y_BOT - LINE_W / 2, left: -(BW + CONN_IN), width: CONN_IN, height: LINE_W },
  bar: { top: BW + PAD_TOP + BOX_PX / 2 - LINE_W / 2, right: -(CONN_RUN + LINE_W / 2), width: LINE_W, height: BAR_LEN },
  stub: { top: BW + PAD_TOP + BOX_PX + GAP_PX / 2 - LINE_W / 2, right: -(CONN_RUN + CONN_STUB), width: CONN_STUB, height: LINE_W },

  // TennisBall: 16px, #7ba81f, rim #1b4332, white seams.
  ball: { width: BALL, height: BALL, borderRadius: BALL / 2, backgroundColor: '#7ba81f', overflow: 'hidden', marginLeft: 4 },
  seam: { position: 'absolute', width: BALL, height: BALL, borderRadius: BALL / 2, borderWidth: 1.5, borderColor: '#fff' },
  ballRim: { position: 'absolute', left: 0, top: 0, width: BALL, height: BALL, borderRadius: BALL / 2, borderWidth: 1.5, borderColor: '#1b4332' },
})
