/**
 * CombinedView — traditional single-player-per-box bracket that combines the
 * user's PICKS with the LIVE result.
 *
 * Columns (0..N for an N-round draw):
 *   col 0  = every entrant of round 1, one box each (the draw). No result/colour.
 *   col c  = the winner of each round-c match, as the user PREDICTED:
 *              • box shows the user's picked winner (falls back to the real
 *                winner if the user made no pick)
 *              • actual score shown beneath the box
 *              • green if the pick was right, red if wrong
 *              • when wrong, the REAL winner's name is shown above the box
 *   col N  = the champion.
 *
 * Windowed like BracketView: only `windowSize` columns render, starting at
 * `windowStart` (the parent's dot pager controls both).
 */
import { Fragment, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import H2HPanel from './H2HPanel'
import PredictorsPopup from './PredictorsPopup'
import { buildH2HSequence, buildMatchIndex, h2hNeighbours, resolveRealFirst } from '../utils/h2hSequence'
import useFlashOnChange from '../hooks/useFlashOnChange'
import './CombinedView.css'
import { parseSet, scoreNodes, liveScoreNodes, expectedStartLabel } from '../utils/score'
import { useAuth } from '../store/auth'

// Upset bell with the same hover tooltip as BracketView's (portal-rendered,
// "Upset Alert!" pill) — pulled into its own component so each bell instance
// tracks its own hover state and bounding-rect-derived tooltip position.
/* The live point on the draw, in its own component so it can hold the flash
   hook — see hooks/useFlashOnChange.js.
   The pill and not the line around it: .cv-live-score is centred with
   transform: translateY(-50%), and an animation that sets transform would
   REPLACE that and drop the score half its own height down the gap. The pill
   has no transform of its own, so it is the safe thing to move. It is also the
   right thing: the games beside it change every few minutes and this changes
   every few seconds. */
function LivePoint({ pts, tiebreak }) {
  const label = `${pts[0] ?? '0'}-${pts[1] ?? '0'}`
  const flash = useFlashOnChange(label)
  return (
    <span className={`cv-live-point${tiebreak ? ' cv-live-point--tb' : ''}${flash ? ' cv-score--bump' : ''}`}
          title={tiebreak ? 'Tiebreak points' : 'Current game'}>
      {label}
    </span>
  )
}

function UpsetBell({ style }) {
  const ref = useRef(null)
  const [tipPos, setTipPos] = useState(null)
  return (
    <>
      <span
        ref={ref}
        className="cv-bell"
        style={style}
        onMouseEnter={() => {
          const r = ref.current?.getBoundingClientRect()
          if (r) setTipPos({ x: r.left + r.width / 2, y: r.top })
        }}
        onMouseLeave={() => setTipPos(null)}
      >
        🔔
      </span>
      {tipPos && createPortal(
        <span className="upset-tooltip" style={{ position: 'fixed', left: tipPos.x, top: tipPos.y - 8, transform: 'translate(-50%, -100%)' }}>
          <span className="upset-tooltip-dot" />
          <span className="upset-tooltip-text">
            <span className="upset-tooltip-upset">Upset </span>
            <span className="upset-tooltip-alert">Alert</span>
            <span className="upset-tooltip-exclaim">!</span>
          </span>
        </span>,
        document.body
      )}
    </>
  )
}

// Two-person glyph for the predictors chip. Counter-rotated in CSS, since the
// chip it sits in is rotated -90deg to match the H2H pill's footprint.
function GroupIcon() {
  return (
    <svg className="cv-group-icon" viewBox="0 0 20 20" aria-hidden="true">
      <circle cx="7.6" cy="6.4" r="3.1" />
      <path d="M1.6 16.4c0-3.1 2.7-5.2 6-5.2s6 2.1 6 5.2z" />
      <circle cx="15" cy="7.4" r="2.4" opacity="0.75" />
      <path d="M13.1 12.1c.6-.2 1.2-.3 1.9-.3 2.6 0 4.6 1.6 4.6 4h-4.9c0-1.5-.6-2.8-1.6-3.7z" opacity="0.75" />
    </svg>
  )
}

// IOC 3-letter → ISO 2-letter for flag classes (mirror of BracketView)
const IOC_TO_ISO2 = {
  AUS:'AU', USA:'US', GBR:'GB', FRA:'FR', GER:'DE', ESP:'ES', ITA:'IT',
  RUS:'RU', CAN:'CA', JPN:'JP', CHN:'CN', KOR:'KR', ARG:'AR', BRA:'BR',
  SUI:'CH', AUT:'AT', BEL:'BE', NED:'NL', DEN:'DK', NOR:'NO', SWE:'SE',
  FIN:'FI', POL:'PL', CZE:'CZ', SVK:'SK', HUN:'HU', ROU:'RO', BUL:'BG',
  SRB:'RS', CRO:'HR', SLO:'SI', BIH:'BA', MKD:'MK', GRE:'GR', TUR:'TR',
  POR:'PT', GEO:'GE', KAZ:'KZ', UKR:'UA', BLR:'BY', LAT:'LV', LTU:'LT',
  EST:'EE', ISR:'IL', RSA:'ZA', EGY:'EG', MAR:'MA', TUN:'TN', NGR:'NG',
  CHI:'CL', COL:'CO', PER:'PE', URU:'UY', VEN:'VE', ECU:'EC', BOL:'BO',
  PAR:'PY', MEX:'MX', IND:'IN', PAK:'PK', THA:'TH', VIE:'VN', INA:'ID',
  MAS:'MY', PHI:'PH', TPE:'TW', HKG:'HK', NZL:'NZ', BAH:'BS', DOM:'DO',
  HAI:'HT', PUR:'PR', TTO:'TT', JAM:'JM', BAR:'BB', GUA:'GT', CRC:'CR',
  MON:'MC', LUX:'LU', ISL:'IS', IRL:'IE', CYP:'CY', MLT:'MT',
}
function nationalityIso2(nat) {
  if (!nat) return null
  return IOC_TO_ISO2[nat.toUpperCase()] ?? (nat.length === 2 ? nat.toUpperCase() : null)
}

// Inferred seed/rank: seeds keep their seed number; unseeded ranked after the
// highest seed by world ranking (same rule as BracketView.computeDrawRanks).
function computeDrawRanks(players) {
  const ranks = {}
  const seeded = players.filter(p => p.seed != null)
  for (const p of seeded) ranks[p.id] = p.seed
  const unseeded = players
    .filter(p => p.seed == null)
    .sort((a, b) => {
      if (a.ranking != null && b.ranking != null) return a.ranking - b.ranking
      if (a.ranking != null) return -1
      if (b.ranking != null) return 1
      return (a.bracket_position ?? 0) - (b.bracket_position ?? 0)
    })
  const offset = seeded.reduce((max, p) => Math.max(max, p.seed), 0)
  unseeded.forEach((p, i) => { ranks[p.id] = offset + i + 1 })
  return ranks
}

// Resolve each match's two feeder player ids the same way winnerBox displays
// them: R1 comes straight from the draw; R2+ cascades the PICKED winner of
// each feeder (falling back to the real winner once known). Raw match.player1/
// player2 for R2+ only get populated once the actual bracket result is in, so
// reading them directly (as BracketView's live mode does) hides H2H/upset-bell
// for Open draws where only picks are available.
function resolveCombinedPlayers(matches, picks) {
  const byKey = {}
  for (const m of matches) byKey[`${m.round_number}:${m.match_number}`] = m
  const resolved = {}

  function getAdvancer(m) {
    if (!m) return null
    if (m.is_bye) return m.player1?.id ?? null
    // A pick only counts if the picked player is one of this match's resolved
    // feeders. Orphaned picks (e.g. a downstream pick of a player displaced by
    // a later upstream re-pick, or legacy phantom picks) must not cascade a
    // player into rounds their own bracket path never reaches.
    const r = resolved[m.id]
    const pick = picks?.[m.id]
    const pickValid = pick != null && r != null && (pick === r.p1 || pick === r.p2)
    return (pickValid ? pick : null) ?? m.winner?.id ?? null
  }

  function resolve(m) {
    if (resolved[m.id]) return resolved[m.id]
    let p1id = m.round_number === 1 ? (m.player1?.id ?? null) : null
    let p2id = m.round_number === 1 ? (m.player2?.id ?? null) : null
    if (m.round_number > 1) {
      const f1 = byKey[`${m.round_number - 1}:${m.match_number * 2 - 1}`]
      const f2 = byKey[`${m.round_number - 1}:${m.match_number * 2}`]
      if (f1) resolve(f1)
      if (f2) resolve(f2)
      p1id = f1 ? getAdvancer(f1) : null
      p2id = f2 ? getAdvancer(f2) : null
    }
    resolved[m.id] = { p1: p1id, p2: p2id }
    return resolved[m.id]
  }

  for (const m of matches) resolve(m)
  return resolved
}

function abbrevName(full) {
  if (!full) return ''
  const parts = full.trim().split(/\s+/)
  if (parts.length === 1) return parts[0]
  return `${parts[0][0]}. ${parts.slice(1).join(' ')}`
}

// A match is live while ESPN is feeding scores for it and no winner has been
// recorded yet — the same test the In Progress badge uses.
const isLiveMatch = (m) => m?.live_scores != null && m.winner == null

const BOX_H = 32
const SLOT = 58          // fallback slot (missing feeders only)
const PAIR_SLOT = 130    // vertical slot per MATCH (pair) in the base column
const PAIR_OFF = 24      // half the centre-to-centre gap of a match's two opponents
// Extra half-gap opened between the two opponents of an IN-PROGRESS match, so
// the running score fits between them. 4 (not more): the pair's grouping
// outline grows by 2*LIVE_SPREAD, and PAIR_SLOT only has ~10px of slack over
// the outline's normal height — at 4 two adjacent live pairs still clear each
// other, at 6 their outlines overlap.
const LIVE_SPREAD = 4
// Reverted the previous 214 (a 25% cut off the ~184px name allotment) back to
// 260 — the narrower width was truncating too many player names.
export const COL_W = 260
// Compact (phone) mode drops the flag AND shrinks further still — the name
// allotment there should be smaller yet, not just re-inherit the 75% cut.
// Narrower than COL_W (was 168, briefly 140) now that compact mode shows
// last-name-only (see lastNameOf below) instead of "F. Last" — widened by
// ~2 characters (140 -> 158) after it came out a bit too tight.
export const COMPACT_COL_W = 158
// Length of the horizontal feeder runs between columns: half goes to the stubs
// out of the two feeding boxes, half to the stub into the box they feed.
// Down from 64, where a two-column compact view came to 2*158 + 64 + 17 = 397px
// and overflowed a 390px phone by just enough to leave the whole draw draggable
// sideways. 44 measures 377 — still inside the screen, with more of the
// connector visible than the 32 this was briefly set to.
export const COL_GAP = 44

/* Rounds slide left by exactly one column-and-gap as --t runs 0 -> 1, which is
   the horizontal half of a scrub. Shared by the labels and the body so the
   round headings travel with the boxes they name. --step is set alongside --t
   on the container, because the column width differs between compact and full. */
// How long the release takes to land on a round. Long enough to read as
// deceleration, short enough that a decisive flick still feels immediate.
const SETTLE_MS = 220

/* Where a y sits in a column's centres, as a FRACTIONAL box index, and the
   inverse. The index is what survives a round expanding — the spacing changes,
   "three and a bit boxes down" does not — so it is the coordinate the finger
   anchor is held in.
   Module scope because both are used during render, and a const declared
   inside the component below its own use is a temporal dead zone, not an
   undefined. */
function fracIndex(arr, y) {
  if (!arr || arr.length === 0) return 0
  if (y <= arr[0]) return 0
  for (let i = 0; i < arr.length - 1; i++) {
    if (y <= arr[i + 1]) return i + (y - arr[i]) / (arr[i + 1] - arr[i] || 1)
  }
  return arr.length - 1
}

function atIndex(arr, idx) {
  if (!arr || arr.length === 0) return 0
  const lo = Math.max(0, Math.min(arr.length - 1, Math.floor(idx)))
  const hi = Math.min(arr.length - 1, lo + 1)
  return arr[lo] + (arr[hi] - arr[lo]) * (idx - lo)
}

const SCRUB_SHIFT = {
  // --tdir and --tbase carry the direction, because the two are not mirror
  // images. Forward starts flush and slides one column LEFT: (t)·-1.
  // Backward renders an extra column on the LEFT, so it starts already shifted
  // off by one and slides back to flush: (t-1)·+1.
  transform: 'translateX(calc((var(--t, 0) * var(--tdir, -1) + var(--tbase, 0)) * var(--step, 0px)))',
  willChange: 'transform',
}
export const H2H_X = 8          // H2H chip's x within the gap — centred on the match box's right border
const BELL_OFFSET = 34   // distance (px) the bell sits left of the H2H chip's centre
// Left padding when there's no nav gutter: H2H_X (the chip's centre, 8px past
// the column edge) + half its rotated visual width (9px), rounded up.
const GROUP_CHIP_GUTTER = 20

function Flag({ nat }) {
  const iso2 = nationalityIso2(nat)
  if (!iso2) return <span className="cv-flag cv-flag--empty" />
  return <span className={`fi fi-${iso2.toLowerCase()} cv-flag`} title={nat} />
}

// Mirrors BracketView's TennisBall icon for visual consistency between views.
function TennisBall() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" style={{ display: 'block', flexShrink: 0 }}>
      <circle cx="12" cy="12" r="11" fill="#7ba81f" />
      <g fill="none" stroke="#fff" strokeWidth="2">
        <path d="M12 1A12.04 12.04 0 0 1 1 12" />
        <path d="M12 23A12.04 12.04 0 0 1 23 12" />
      </g>
      <circle cx="12" cy="12" r="11" fill="none" stroke="#1b4332" strokeWidth="2" />
    </svg>
  )
}

function SeedBadge({ player, drawRanks }) {
  if (!player) return null
  const rank = player.seed != null ? player.seed : drawRanks?.[player.id]
  if (rank == null) return null
  return (
    <span className={`pos-badge ${player.seed != null ? 'seeded' : 'unseeded'}`}
      title={player.ranking != null ? `Rank: ${player.ranking}` : undefined}>{rank}</span>
  )
}

function EntryBadge({ player }) {
  if (!player?.entry_type) return null
  return <span className={`pos-badge entry entry-${player.entry_type.toLowerCase()} cv-entry`}>{player.entry_type}</span>
}

// Straight-elbow connectors between two columns of box centres.
function Connectors({ leftCenters, rightCenters, totalH }) {
  const lines = []
  const x1 = 0, xMid = COL_GAP / 2, x2 = COL_GAP
  for (let ri = 0; ri < rightCenters.length; ri++) {
    const r = rightCenters[ri]
    const f1 = leftCenters[ri * 2], f2 = leftCenters[ri * 2 + 1]
    const pts = [f1, f2, r].filter(v => v != null)
    const yMin = Math.min(...pts), yMax = Math.max(...pts)
    if (f1 != null) lines.push(<line key={`a${ri}`} x1={x1} y1={f1} x2={xMid} y2={f1} />)
    if (f2 != null) lines.push(<line key={`b${ri}`} x1={x1} y1={f2} x2={xMid} y2={f2} />)
    if (yMax > yMin) lines.push(<line key={`v${ri}`} x1={xMid} y1={yMin} x2={xMid} y2={yMax} />)
    lines.push(<line key={`r${ri}`} x1={xMid} y1={r} x2={x2} y2={r} />)
  }
  return (
    <svg className="cv-conn" width={COL_GAP} height={totalH} style={{ flexShrink: 0 }}>
      <g stroke="var(--connector-line)" strokeWidth="1.5" fill="none">{lines}</g>
    </svg>
  )
}

// compact: phone-width mode — country flags are dropped to buy name space.
// zoom:    scales the whole rendered draw (layout included, via CSS zoom) so
//          the parent can shrink it until the target number of rounds fits.
export default function CombinedView({ tournament, matches, players, picks, onPick, locked = true, windowStart = 0, windowSize = 4, labelsHidden = false, insetLeft = 0, compact = false, zoom = 1, scrubRef = null, leagueId = null, lockedMatchIds = new Set(), predictionsHidden = false }) {
  /* Which clock upcoming times are shown in. The account's choice where there
     is one; otherwise the reader's own, which needs no explanation when they
     have never expressed a preference. undefined means "this device". */
  const tzUser = useAuth(s => s.user)
  const scheduleZone = tzUser?.schedule_tz === 'venue'
    ? (tournament?.venue_timezone || undefined)
    : undefined
  const [h2h, setH2H] = useState(null)
  // Completed match whose predictors popup is open (the group chip's target).
  const [predictorsMatch, setPredictorsMatch] = useState(null)
  // Hovering any box of a player highlights ALL that player's boxes across
  // the bracket (ported from BracketView's hoveredPlayerId behaviour).
  const [hoveredPlayerId, setHoveredPlayerId] = useState(null)

  /* Keep the picked player on screen when the window moves.
     Paging changes which rounds are drawn but not how far down the bracket you
     are, and a player's box sits at a DIFFERENT height in the next round —
     roughly twice as far down, since each round halves the field over the same
     span. So scrubbing forward from a highlighted name routinely left it above
     or below the fold, and the blue path you were following disappeared at the
     moment you asked to follow it.

     Compact only. On a phone the highlight comes from a tap and stays put, so
     it is a deliberate "follow this player". On a desktop it comes from the
     mouse merely being over a box, and scrolling the bracket because the
     pointer happened to be resting somewhere would be startling.

     Scrolls the CONTAINER rather than calling scrollIntoView, which walks up
     and scrolls every ancestor it can — including the page behind a bracket
     that is supposed to scroll inside its own box. */
  const scrollRef = useRef(null)
  // 0 = idle, +1 = pulling deeper rounds in, -1 = going back. The DIRECTION has
  // to reach the layout, not just the commit: interpolating toward start+1
  // whichever way the finger went is what made a backward drag animate forward
  // and then snap.
  const [scrubDir, setScrubDir] = useState(0)
  const scrubbing = scrubDir !== 0
  const scrub = useRef(null)
  const lastWindow = useRef(windowStart)
  useEffect(() => {
    const moved = lastWindow.current !== windowStart
    lastWindow.current = windowStart
    if (!moved || !compact || hoveredPlayerId == null) return
    const box = scrollRef.current
    if (!box) return
    // After the new columns have been laid out — their heights are what the
    // target position is measured against.
    const raf = requestAnimationFrame(() => {
      const el = box.querySelector(`[data-player-id="${hoveredPlayerId}"]`)
      if (!el) return
      const outer = box.getBoundingClientRect()
      const inner = el.getBoundingClientRect()
      box.scrollTo({
        top: Math.max(0, box.scrollTop + (inner.top - outer.top)
                         - (outer.height - inner.height) / 2),
        behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
          ? 'auto' : 'smooth',
      })
    })
    return () => cancelAnimationFrame(raf)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [windowStart])
  const colW = compact ? COMPACT_COL_W : COL_W

  const playerById = Object.fromEntries(players.map(p => [p.id, p]))
  const drawRanks = computeDrawRanks(players)

  // Number unplaced Q slots by bracket position: Qualifier 1, Qualifier 2, …
  // (mirror of BracketView so the Combined view labels them identically)
  const qualifierNums = {}
  players
    .filter(p => p.entry_type === 'Q' && !p.name)
    .sort((a, b) => a.bracket_position - b.bracket_position)
    .forEach((p, i) => { qualifierNums[p.id] = i + 1 })

  // Compact (phone) mode: last name only, EXCEPT for players who share a last
  // name with someone else in this draw — those keep the "F. Last" format so
  // they stay distinguishable. lastNameOf mirrors abbrevName's "everything
  // after the first token" so two-word surnames (e.g. "Carreño Busta") stay
  // together, matching how the app already defines "last name" elsewhere.
  const lastNameOf = (full) => {
    const parts = full.trim().split(/\s+/)
    return parts.length > 1 ? parts.slice(1).join(' ') : parts[0]
  }
  // Two players in a draw can share a surname, and a shortened name that no
  // longer tells them apart is worse than a long one. Counted for BOTH of the
  // surname forms the ladder below can fall back to.
  const nameCounts = {}
  for (const pl of players) {
    if (!pl.name) continue
    const parts = pl.name.trim().split(/\s+/)
    for (const form of new Set([lastNameOf(pl.name), parts[parts.length - 1]])) {
      nameCounts[form] = (nameCounts[form] || 0) + 1
    }
  }

  /* How much room a name has, in the px the draw is laid out in — the zoom
     magnifies the result but does not change it.
     Every term is a constant of the layout, not something read back off the
     page: the box is the column less the slot's 4px insets, its own 3+8
     padding and its 1px borders, and each badge either renders at a fixed
     width or does not render at all. Nothing is measured, so nothing can feed
     back into what it measured. */
  const NAME_BOX = (compact ? COMPACT_COL_W : COL_W) - 21
  /* 0.68, measured off a rendered draw rather than guessed: "ETCHEVERRY" is ten
     characters and occupies 86px of a 158px column at 12.8px, which is 0.67em
     each. The first pass used 0.63, and that was optimistic in BOTH directions
     at once — it let through a rung that did not fit, then computed a shrink
     too small to save it, so a name that should have stepped down twice
     ellipsised instead. Every name here is uppercased by .cv-name, so one
     figure covers the page. */
  const CH_EM = 0.68
  const BOX_FONT = 12.8    // .cv-box sets 0.8rem
  const nameBudget = (p, serving) => {
    let w = NAME_BOX
    if (p?.seed != null || drawRanks?.[p?.id] != null) w -= compact ? 32 : 26
    if (!compact) w -= 33                      // the flag, which renders even when empty
    if (p?.entry_type) w -= 32
    if (serving) w -= 20
    return w
  }

  /* Full name, first initial, surname, surname's final word. Two forms of
     surname because the app treats everything after the first token as one —
     right for "Carreño Busta", wrong for "Tomás Martín Etcheverry", and there
     is no way to tell them apart from the string. So the longer reading is
     tried first and the shorter one is there for when it does not fit. */
  const nameForms = (full) => {
    const parts = full.trim().split(/\s+/)
    if (parts.length === 1) return [full]
    const rest = parts.slice(1).join(' ')
    return [full, `${parts[0][0]}. ${rest}`, rest, parts[parts.length - 1]]
  }

  const isUnnamedQ = (p) => p?.entry_type === 'Q' && !p.name
  /* Each rung is used only because the one above it does not fit, and a rung
     that would collide with another player in the draw is skipped — telling
     two people apart matters more than saving a few pixels.
     THE SURNAME IS NEVER CUT. When even the shortest rung is too wide the type
     comes down to meet it, which is the last thing to give and the only one
     that costs no information. An ellipsis costs the end of the name, which is
     the part that identifies the player. */
  const slotName = (p, serving) => {
    if (!p) return { text: 'TBD', scale: 1 }
    if (isUnnamedQ(p)) {
      const n = qualifierNums[p.id]
      return { text: `Qualifier${n != null ? ` ${n}` : ''}`, scale: 1 }
    }
    const forms = nameForms(p.name)
    /* Everything starts at the initial form, phone included. A phone used to
       start a rung lower, on the bare surname, because there was no way to find
       out whether the initial would fit — so it was never offered. The ladder
       can answer that now, and an initial is worth having wherever there is
       room: it is what tells two Zverevs apart on sight.
       Where it does not fit, the rung below is the bare surname — exactly what
       a phone showed before — so this only ever ADDS a first initial, it never
       takes a surname away.
       The case for two players sharing a surname needs no special handling any
       more either: the surname rungs are skipped when they collide, which
       leaves the initial form standing on its own. */
    const start = forms.length === 1 ? 0 : 1
    const chain = []
    for (let i = start; i < forms.length; i++) {
      const t = forms[i]
      if (i > start && (t === chain[chain.length - 1] || nameCounts[t] > 1)) continue
      chain.push(t)
    }
    const budget = nameBudget(p, serving)
    const width = (t) => t.length * CH_EM * BOX_FONT
    for (const t of chain) if (width(t) <= budget) return { text: t, scale: 1 }
    const text = chain[chain.length - 1]
    return { text, scale: Math.max(0.55, budget / width(text)) }
  }

  // Rounds (arrays of matches, sorted by match_number)
  const byRound = {}
  for (const m of matches) (byRound[m.round_number] ||= []).push(m)
  const roundNums = Object.keys(byRound).map(Number).sort((a, b) => a - b)
  const R = roundNums.map(rn => [...byRound[rn]].sort((a, b) => a.match_number - b.match_number))
  const N = R.length
  if (N === 0) return null

  const resolved = resolveCombinedPlayers(matches, picks)

  // The H2H panel reads real entrants first, so it never compares two players
  // who did not actually meet — see resolveRealFirst. The bracket itself keeps
  // using `resolved`, which is what the user picked.
  const h2hResolved = resolveRealFirst(matches, resolved)
  const h2hSeq = buildH2HSequence(matches, h2hResolved, playerById)
  const h2hNav = h2hNeighbours(h2hSeq, h2h?.match?.id)
  const matchIndex = buildMatchIndex(matches)

  // Round each player was actually eliminated in (real results only) — a pick
  // of that player as the winner of that round or any later one is a dead
  // pick, shown wrong immediately rather than waiting for the picked match
  // itself to be played (mirrors BracketView's lossRound handling).
  const lossRound = {}
  for (const m of matches) {
    const wid = m.winner?.id
    if (wid == null || m.is_bye) continue
    const loserId = m.player1?.id === wid ? m.player2?.id : m.player1?.id
    if (loserId != null) lossRound[loserId] = m.round_number
  }

  const totalCols = N + 1
  const size = Math.min(windowSize, totalCols)
  const maxStart = Math.max(0, totalCols - size)
  const start = Math.min(Math.max(0, windowStart), maxStart)
  /* One extra column while a scrub is in flight, so the round being pulled in
     exists in the DOM before it is needed — appended going forward, PREPENDED
     going back, which is the asymmetry the first version missed entirely. */
  const backward = scrubDir < 0
  const renderStart = backward ? Math.max(0, start - 1) : start
  const extra = scrubbing && (backward ? start > 0 : start + size < totalCols) ? 1 : 0
  const visible = Array.from({ length: size + extra }, (_, i) => renderStart + i)
    .filter((c) => c < totalCols)

  const colCount = (c) => (c === 0 ? 2 * R[0].length : R[c - 1].length)

  // Feeder-centred vertical layout for the visible columns. The left-most (base)
  // column pairs each match's two opponents tightly (small within-pair gap,
  // larger gap between matches); columns to its right centre on their feeders.
  /* The whole vertical geometry of a window is a pure function of its LEFTMOST
     column: that one gets the full pair spacing, and every column right of it
     sits at the midpoint of the two boxes feeding it. Which is why scrubbing
     can be a smooth interpolation rather than a redesign — advancing one round
     is exactly "column s+1 stops being a midpoint and becomes a pair slot",
     and every other column follows from that. Extracted so the same rule can
     be evaluated for the window we are on AND the window we are heading to. */
  const layoutFrom = (cols) => {
    const out = {}
    cols.forEach((c, p) => {
      const count = colCount(c)
      if (p === 0) {
        out[c] = []
        const nPairs = Math.ceil(count / 2)
        for (let pi = 0; pi < nPairs; pi++) {
          const mc = pi * PAIR_SLOT + PAIR_SLOT / 2
          const hasSecond = 2 * pi + 1 < count
          out[c].push(hasSecond ? mc - PAIR_OFF : mc)
          if (hasSecond) out[c].push(mc + PAIR_OFF)
        }
      } else {
        const prev = out[cols[p - 1]]
        out[c] = Array.from({ length: count }, (_, i) => {
          const a = prev[2 * i], b = prev[2 * i + 1]
          if (a != null && b != null) return (a + b) / 2
          return a ?? (i * SLOT + SLOT / 2)
        })
      }
    })
    return out
  }

  /* A scrub is one rule evaluated at two anchors, and which anchor is "now"
     depends on the direction.

     FORWARD  now = this window; next = one round deeper. The column being left
              has no place in the destination, so it fades.
     BACKWARD now = this window; next = one round back — and the destination is
              anchored one column LEFT of everything rendered, so the roles
              simply swap: the layout of what we render IS the destination, and
              "now" is that same rule one column in.

     The column arriving on a backward scrub has no position in the current
     layout at all. Its boxes emerge from the parent they feed, which is the
     exact inverse of the forward case where a column's boxes converge onto
     their winner — so the two directions look like each other played
     backwards, which is what makes the gesture read as reversible. */
  const collapseOnto = (parents, count) =>
    Array.from({ length: count }, (_, i) => parents?.[Math.floor(i / 2)] ?? 0)

  let centers
  let centersNext = null
  if (backward && visible.length > 1) {
    centersNext = layoutFrom(visible)
    centers = layoutFrom(visible.slice(1))
    centers[visible[0]] = collapseOnto(centers[visible[1]], colCount(visible[0]))
  } else {
    centers = layoutFrom(visible)
    if (scrubbing && visible.length > 1) centersNext = layoutFrom(visible.slice(1))
  }


  // Both layouts of the expanding column, for the anchor. Assigned during
  // render rather than in an effect: the first move() can arrive in the same
  // frame the gesture starts, before any effect has run.
  if (scrub.current && centersNext) {
    // A column present in BOTH layouts, so the fractional index means the same
    // thing at each end. Forward that is the round being pulled in; backward it
    // is the one we are on, which becomes the second column of the destination.
    const focus = backward ? start : start + 1
    scrub.current.a = centers[focus] || centers[start]
    scrub.current.b = centersNext[focus] || centersNext[start + 1]
    if (scrub.current.idx == null) {
      scrub.current.idx = fracIndex(scrub.current.a, scrub.current.contentY)
    }
  }
  /* Any measurement that has to travel with the layout — a top, a height, the
     middle of a gap. Without a scrub in flight it is the plain number, exactly
     as before, so nothing pays for the gesture when it is not happening.

     EVERYTHING keyed to the centres has to go through this, not just the boxes.
     The match outlines, the score in the gap, the H2H chips and the upset bells
     are all positioned from the same arrays, and interpolating only the boxes
     left them sliding out from under their own furniture.

     Distinct variable names per property, because two travelling values on one
     element would otherwise both claim --a. */
  const trav = (a, b, prop, na = '--a', nb = '--b') => {
    if (b == null || b === a) return { [prop]: a }
    return {
      [na]: a,
      [nb]: b,
      [prop]: `calc((var(${na}) + (var(${nb}) - var(${na})) * var(--t, 0)) * 1px)`,
    }
  }

  const slotStyle = (c, i, a) => trav(a, centersNext?.[c]?.[i], 'top')

  /* ── The scrub, driven from the parent's touch handlers ──────────────────
     Owned HERE rather than in the page, because pinning the row under the
     finger needs both layouts and the scroll container, and this is the only
     place that has them. The page supplies the gesture; this supplies the
     geometry.

     THE ANCHOR IS THE WHOLE POINT. A finger between two names is at some
     fractional index in the incoming column's centres — say 3.4 boxes down.
     That index does not change as the round expands; only the pixel spacing
     does. So the pixel position is recomputed from the same index every frame
     and the scroll is offset to keep it under the finger. The match you were
     pointing at is the match you are still pointing at, which is what makes it
     read as pulling the bracket rather than paging it.

     Everything per-frame is a style write. React renders once when the gesture
     starts and once when it ends. */
  useEffect(() => {
    if (!scrubRef) return
    const step = colW + COL_GAP
    scrubRef.current = {
      // Is there anywhere to go? The page asks before claiming the gesture, so
      // a bracket at its last round still scrolls normally.
      canPage: (dir) => dir > 0 ? start + size < totalCols : start > 0,

      // dir must arrive HERE, not at commit time: it decides which layout the
      // interpolation runs toward, and that has to be settled before the first
      // frame is drawn.
      begin(clientY, dir) {
        const el = scrollRef.current
        if (!el) return false
        const rect = el.getBoundingClientRect()
        const localY = clientY - rect.top
        // Content coordinates, undoing the fit-to-width scale.
        const contentY = (el.scrollTop + localY) / (zoom || 1)
        scrub.current = { localY, idx: null, contentY, step, dir }
        setScrubDir(dir)
        return true
      },

      // t runs 0 -> 1 for "one round forward". The page clamps it.
      move(t) {
        const el = scrollRef.current
        const st = scrub.current
        if (!el || !st) return
        el.style.setProperty('--t', String(t))
        if (st.idx == null) return
        const y = atIndex(st.a, st.idx) + (atIndex(st.b, st.idx) - atIndex(st.a, st.idx)) * t
        el.scrollTop = Math.max(0, y * (zoom || 1) - st.localY)
      },

      // Settle to 0 or 1, then hand the window change to the page. The class
      // does the easing; when it lands, `scrubbing` goes false, --t is cleared
      // and the boxes are already where the new window would have drawn them.
      finish(t, onDone) {
        const el = scrollRef.current
        const st = scrub.current
        if (!el || !st) { setScrubDir(0); return }
        const target = t >= 0.5 ? 1 : 0
        el.classList.add('cv-scroll--settling')
        el.style.setProperty('--t', String(target))
        if (st.idx != null) {
          const y = target ? atIndex(st.b, st.idx) : atIndex(st.a, st.idx)
          el.scrollTop = Math.max(0, y * (zoom || 1) - st.localY)
        }
        window.setTimeout(() => {
          el.classList.remove('cv-scroll--settling')
          el.style.removeProperty('--t')
          scrub.current = null
          setScrubDir(0)
          if (target === 1) onDone?.()
        }, SETTLE_MS)
      },
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scrubRef, start, size, totalCols, colW, zoom])

  const totalH = Math.ceil(colCount(visible[0]) / 2) * PAIR_SLOT
  // Natural (unscaled) footprint of the labels+body block, for the
  // scale-to-fit wrapper below. LABELS_H is an estimate of .cv-labels'
  // rendered height (padding + line height) — a few px of slop here just
  // means a few px of extra/short scroll space, not a visual bug.
  // TRAILING_W accounts for the H2H chip in the last visible column's
  // trailing stub (feeding the next, not-yet-shown round) — real, clickable
  // content, so it counts toward the footprint. The REST of that stub's
  // connector line (reaching to where the next column's box would start) is
  // decorative only, so it deliberately does NOT get a full COL_GAP credit
  // here — in compact mode that lets the zoom-fit target (TournamentDraw.jsx)
  // sit tighter, with the unneeded tail of the line simply overflowing off
  // the viewport edge instead of reserving dead space for it.
  const TRAILING_W = H2H_X + 9 // chip's right edge: its centre (H2H_X into the gap) + half its rotated visual width (height:18 -> 9)
  // `size`, NOT visible.length. The extra scrub column must not enter the
  // footprint: naturalW feeds the zoom-to-fit, so counting it would shrink the
  // whole bracket the instant a finger went down and grow it again on release.
  const naturalW = size * colW + (size - 1) * COL_GAP + TRAILING_W
  const LABELS_H = 34
  const naturalH = totalH + LABELS_H

  // Centres for the column just PAST the visible window (if one exists) — used
  // only to draw the trailing feed bars (connectors + H2H + bell) off the
  // right-most visible column. Its box column itself is never rendered.
  const afterC = visible[visible.length - 1] + 1
  let afterCenters = null
  if (afterC <= N) {
    const count = colCount(afterC)
    const prev = centers[visible[visible.length - 1]]
    afterCenters = Array.from({ length: count }, (_, i) => {
      const a = prev[2 * i], b = prev[2 * i + 1]
      if (a != null && b != null) return (a + b) / 2
      return a ?? (i * SLOT + SLOT / 2)
    })
  }

  // A live match prints its running score in the gap between its two
  // opponents, so open that pair up a little to make room. Applied LAST, after
  // every column (and afterCenters) has been derived, and symmetrically about
  // the pair's midpoint — which is exactly what the next column's box centre,
  // its H2H chip and the connector fan all key off, so none of them shift.
  // Only the live pair itself moves, and only by LIVE_SPREAD each way.
  // Applied to the SCRUB layout too, or the two disagree about where a live
  // pair sits and the box jumps by LIVE_SPREAD at the end of every gesture.
  for (const map of [centers, centersNext]) {
    if (!map) continue
    Object.keys(map).forEach((key) => {
      const c = Number(key)
      const cc = map[c]
      R[c]?.forEach((m, ri) => {
        const a = 2 * ri, b = 2 * ri + 1
        if (!isLiveMatch(m) || cc[a] == null || cc[b] == null) return
        cc[a] -= LIVE_SPREAD
        cc[b] += LIVE_SPREAD
      })
    })
  }

  // ---- box builders -------------------------------------------------------
  // Clicking a box picks ITS player as the predicted winner of the match they
  // feed into next (one column to the right) — e.g. clicking a player shown
  // in the "Round of 16" column (having won R32, about to play R16) predicts
  // them to win THAT match and advance into the Quarterfinals column. Column
  // c's box i always feeds match R[c][floor(i/2)]. The Champion column (c===N)
  // has no further match, so it's never clickable.
  function nextMatchOnClick(c, i, playerId) {
    if (locked || !onPick || playerId == null || c >= N) return null
    const nextMatch = R[c][Math.floor(i / 2)]
    if (!nextMatch) return null
    // Clicking a player picks them in the NEXT match, so it is that match's
    // lock that decides — not the one they are standing in.
    if (lockedMatchIds.has(nextMatch.id)) return null
    return () => onPick(nextMatch.id, playerId)
  }

  // Is the player in column c, row i currently serving? Their live match is
  // the one they feed into next — R[c][floor(i/2)] — and their slot in it is
  // p1 (even i, top) or p2 (odd i, bottom), same convention used everywhere
  // else (entrantBox, centers pairing). live_scores[2] is 1 or 2 for p1/p2.
  function isServing(c, i) {
    if (c >= N) return false
    const nextMatch = R[c][Math.floor(i / 2)]
    if (!nextMatch?.live_scores) return false
    const wantSlot = i % 2 === 0 ? 1 : 2
    return nextMatch.live_scores[2] === wantSlot
  }

  function entrantBox(c, i) {
    const match = R[0][Math.floor(i / 2)]
    // Which line of a bye match the player occupies is not in the source data
    // — Wikipedia lists a bye'd seed only in round 2 — so it is decided here.
    // ATP rulebook 7.16 fixes the seed lines (1, 8, 9, 16 … 121, 128 for a 96
    // draw) and 7.18 gives every seed a bye, which puts the seed on the OUTER
    // line of its first-round match: line 1 in match 1, line 8 in match 4,
    // line 128 in match 64. Seed lines are always ≡ 0 or 1 (mod 4), and an odd
    // line is ≡1 only in odd-numbered matches while an even line is ≡0 only in
    // even-numbered ones — so match parity alone decides it. Half the byes sit
    // below their bye, including the #2 seed's line at the very bottom.
    // Display order only: bracket_position is untouched, so no pick moves.
    const playerSlot = match.is_bye && match.match_number % 2 === 0 ? 1 : 0
    const pid = match.is_bye
      ? (i % 2 === playerSlot ? match.player1?.id ?? null : null)
      : (i % 2 === 0 ? match.player1?.id : match.player2?.id)
    const player = pid != null ? playerById[pid] : null
    const isBye = match.is_bye && i % 2 !== playerSlot
    // A bye match has no real outcome to predict — neither the bye
    // placeholder slot (isBye, handled above) NOR the opponent's own slot
    // should be clickable, so a click can never save a redundant "pick"
    // for a match that was always going to auto-advance regardless.
    const onClick = match.is_bye ? null : nextMatchOnClick(0, i, pid)
    return { key: `e${i}`, player, isBye, serving: !isBye && isServing(0, i), abbrev: true, kind: 'entrant', clickable: !!onClick, onClick }
  }

  function winnerBox(c, i) {
    const match = R[c - 1][i]
    const realId = match.winner?.id ?? null
    const pickId = picks?.[match.id] ?? null
    const displayId = pickId ?? realId
    const player = displayId != null ? playerById[displayId] : null
    const correct = pickId != null && realId != null && pickId === realId
    // Wrong when the real winner disagrees — or when the picked player has
    // already been eliminated in this round or earlier (dead pick), even
    // though this match itself hasn't been played yet.
    const deadPick = pickId != null && lossRound[pickId] != null
      && lossRound[pickId] <= match.round_number
    const wrong = pickId != null && ((realId != null && pickId !== realId) || deadPick)
    const realPlayer = realId != null ? playerById[realId] : null
    // A live match's score belongs to the match's OWN box group (drawn between
    // its two opponents), not under the box holding its eventual winner — so
    // nothing is shown here until the match is decided and match.scores lands.
    const score = match.is_bye || isLiveMatch(match) ? null : scoreNodes(match.scores)

    const onClick = nextMatchOnClick(c, i, displayId)

    return {
      key: `w${match.id}`, player, correct, wrong, score, serving: isServing(c, i),
      realName: wrong && realPlayer ? abbrevName(realPlayer.name) : null,
      realFullName: wrong && realPlayer ? realPlayer.name : null,
      match, abbrev: true, kind: 'winner', clickable: !!onClick, onClick,
    }
  }

  const colX = (idx) => idx * (colW + COL_GAP)

  return (
    <>
      {h2h && (
        <H2HPanel
          slug1={h2h.p1.te_slug} slug2={h2h.p2.te_slug}
          player1={h2h.p1} player2={h2h.p2}
          tournSurface={tournament?.surface} tournGender={tournament?.gender}
          beforeDrawId={tournament?.id} beforeRound={h2h.match?.round_number}
          match={h2h.match}
          matchOrder={matchIndex.order}
          matchTotal={matchIndex.total}
          picks={picks}
          onPick={onPick}
          canPick={!locked}
          onPrev={h2hNav.prev ? () => setH2H(h2hNav.prev) : null}
          onNext={h2hNav.next ? () => setH2H(h2hNav.next) : null}
          onClose={() => setH2H(null)}
        />
      )}
      {predictorsMatch && (
        <PredictorsPopup
          drawId={tournament?.id}
          match={predictorsMatch}
          leagueId={leagueId}
          onClose={() => setPredictorsMatch(null)}
        />
      )}
      {/* insetLeft's caller (NAV_INSET) is already tuned tight to the nav
          button's own footprint — stacking the full 0.75rem base padding on
          top of it left a visibly wide gap; a few px is enough breathing
          room between the button and the first box. */}
      {/* Left padding has to clear the group chip, which is centred on the
          leftmost column's outline border and so overhangs it by 8px + half
          the chip's rotated width (9px). Overflow to the LEFT of a scroll
          container's content origin can't be scrolled to, it's simply clipped,
          so without this the first column's chips lose their left edge. When
          the nav gutter is present its own inset is already wider than that. */}
      <div ref={scrollRef}
           className={`cv-scroll${compact ? ' cv-scroll--compact' : ''}${scrubbing ? ' cv-scrubbing' : ''}`}
           style={{
             paddingLeft: insetLeft ? `${insetLeft + 4}px` : `${GROUP_CHIP_GUTTER}px`,
             // One round's travel, in px, and which way it runs. Read by
             // SCRUB_SHIFT.
             '--step': `${colW + COL_GAP}px`,
             '--tdir': backward ? 1 : -1,
             '--tbase': backward ? -1 : 0,
           }}>
        {/* Scale-to-fit: outer claims the SMALLER (zoomed) footprint so
            .cv-scroll's scrollWidth shrinks with it (needed for 2 rounds to
            fit a narrow phone without horizontal scrolling); inner renders at
            natural size and transform:scale()s down to exactly fill it.
            transform, not the CSS `zoom` property — WebKit doesn't reliably
            cascade `zoom` into descendants that establish their own
            positioning/formatting context (position:absolute, overflow,
            flex, ...), which are exactly the properties nearly every element
            in this bracket uses; transform:scale has been identically
            supported everywhere for well over a decade. */}
        {/* No overflow clipping here (tried overflow-x:hidden — reverted: it
            also clipped the FIRST column's .cv-match-outline, which extends
            -8px past its own column on the left, an intentional overhang not
            a bug; and clipping the trailing connector line mid-stroke made
            it visibly fade to white rather than cleanly disappear, which
            reads as broken, not "cropped"). naturalW still excludes the
            decorative tail past the H2H chip so drawZoom sizes tighter, but
            the actual pixels are simply allowed to overflow past the
            declared box uncropped — same tradeoff as the LABELS_H estimate
            below: a few px of harmless overflow beats a clipping artifact. */}
        <div style={zoom !== 1 ? { width: naturalW * zoom, height: naturalH * zoom } : undefined}>
        <div style={zoom !== 1 ? { width: naturalW, height: naturalH, transform: `scale(${zoom})`, transformOrigin: 'top left' } : undefined}>
        <div className={`cv-labels${labelsHidden ? ' cv-labels--collapsed' : ''}`}
             style={scrubbing ? SCRUB_SHIFT : undefined}>
          {visible.map((c, i) => {
            const label = c === 0
              ? (R[0][0]?.round_name || 'Round 1')
              : c < N ? (R[c][0]?.round_name || `Round ${c + 1}`) : 'Champion'
            // A heading belongs to its column: the one whose column is leaving
            // fades out, the one whose column is arriving fades in. Without
            // this the whole row swapped in a single frame at commit, which is
            // the most visible pop of the lot because it is the only text that
            // changes.
            const state = !scrubbing ? ''
              : i === (backward ? visible.length - 1 : 0) ? ' cv-label--leaving'
              : i === (backward ? 0 : visible.length - 1) ? ' cv-label--arriving'
              : ''
            return (
              <div key={c} style={{ display: 'flex', flexShrink: 0 }}>
                <div className={`cv-label${state}`} style={{ width: colW }}>{label}</div>
                {i < visible.length - 1 && <div style={{ width: COL_GAP }} />}
              </div>
            )
          })}
        </div>

        <div className="cv-body"
             style={scrubbing ? { height: totalH, ...SCRUB_SHIFT } : { height: totalH }}>
          {visible.map((c, colIdx) => {
            const count = colCount(c)
            const cc = centers[c]
            // Where this column's boxes land one round on, for everything that
            // has to travel with them.
            const ccN = centersNext?.[c] || null
            // The column with no place in the destination fades rather than
            // interpolating to a position it does not have. Going forward that
            // is the leftmost; going back it is the one falling off the right.
            const leaving = scrubbing
              && colIdx === (backward ? visible.length - 1 : 0)

            // Interior gap: feeds the next VISIBLE column. Trailing stub: the
            // right-most visible column still gets its feed bars (connectors,
            // H2H, bell) pointing at the next column's slot, even though that
            // column's boxes aren't rendered (out of the window). Computed here
            // (rather than inside the gap IIFE below) so the missing-pick outline,
            // which is drawn inside cv-col, can also key off the match it feeds.
            const isLastVisible = colIdx === visible.length - 1
            const nextC = isLastVisible ? afterC : visible[colIdx + 1]
            const nextCenters = isLastVisible ? afterCenters : centers[nextC]

            return (
              <div key={c} style={{ display: 'flex', flexShrink: 0 }}>
                <div className={`cv-col${leaving ? ' cv-col--leaving' : ''}`}
                     style={{ width: colW, height: totalH }}>
                  {/* Light grey box grouping every match's two feeder boxes together;
                      switches to red once both opponents are known but the user
                      hasn't picked a winner yet (mirrors BracketView's "missing-pick"
                      outline in Picks mode). Rendered first so it sits behind the
                      player boxes. */}
                  {nextC >= 1 && nextC - 1 < R.length && R[nextC - 1].map((m, ri) => {
                    const yTop = cc[2 * ri], yBot = cc[2 * ri + 1]
                    if (yTop == null || yBot == null) return null
                    const { p1: aId, p2: bId } = resolved[m.id] || {}
                    const isMissingPick = !locked && aId != null && bId != null && picks?.[m.id] == null
                    // Top pad clears the "real winner" note (now centred on the
                    // TOP box's own top border, so it barely pokes above it);
                    // bottom pad clears the score line below the BOTTOM box.
                    // Scores only render when colIdx > 0 (see the box.score
                    // line below) — i.e. whichever column is currently the
                    // LEFTMOST visible pane never shows one, regardless of its
                    // absolute round — so the outline must key off colIdx, not c.
                    const topPad = 12
                    const bottomPad = colIdx === 0 ? 12 : 28
                    // The outline wraps the pair, so BOTH its top and its
                    // height are functions of the two centres — and both have
                    // to travel, or the box stays the height of the round it
                    // came from while the names inside it close up.
                    const boxOf = (arr) => {
                      const t0 = arr?.[2 * ri], b0 = arr?.[2 * ri + 1]
                      if (t0 == null || b0 == null) return null
                      return {
                        top: Math.min(t0, b0) - BOX_H / 2 - topPad,
                        height: Math.abs(b0 - t0) + BOX_H + topPad + bottomPad,
                      }
                    }
                    const boxA = boxOf(cc)
                    const boxN = boxOf(ccN)
                    const top = boxA.top
                    const height = boxA.height
                    const outlineTravel = {
                      ...trav(boxA.top, boxN?.top, 'top'),
                      ...trav(boxA.height, boxN?.height, 'height', '--ha', '--hb'),
                    }
                    const isSuspended = m.live_scores?.[4] === 'suspended'
                    const isLive = isLiveMatch(m)

                    /* Where the gap between these two opponents actually begins
                       and ends — which is not simply the two box edges.

                       The box ABOVE prints its completed score underneath
                       itself, and the box BELOW carries the real winner's name
                       across its own top border. Both of those are inside the
                       gap, and centring on the midpoint of the box CENTRES
                       ignored them: with a wrong pick underneath, the running
                       score sat directly on the name of the player who actually
                       won.

                       Measured off the two rules rather than guessed. .cv-score
                       starts 18px below a box's centre and stands about 18 tall,
                       so it reaches 20px past the box's own edge;
                       .cv-real-winner is 11px tall sitting 10px above its box's
                       centre, so it pokes 5px above that box's top edge. */
                    const SCORE_H = 20
                    const NOTE_H = 5
                    const boxAt = (i) => (c === 0 ? entrantBox(c, i) : winnerBox(c, i))
                    const upper = boxAt(yTop <= yBot ? 2 * ri : 2 * ri + 1)
                    const lower = boxAt(yTop <= yBot ? 2 * ri + 1 : 2 * ri)
                    // Scores render only from the second visible column on, so
                    // this keys off colIdx exactly as the outline above does.
                    // The middle of the gap the score sits in. Computed from
                    // whichever pair of centres, so it can travel like the rest.
                    const midOf = (arr) => {
                      const t0 = arr?.[2 * ri], b0 = arr?.[2 * ri + 1]
                      if (t0 == null || b0 == null) return null
                      const gt = Math.min(t0, b0) + BOX_H / 2
                                 + (colIdx > 0 && upper?.score ? SCORE_H : 0)
                      const gb = Math.max(t0, b0) - BOX_H / 2
                                 - (lower?.realName ? NOTE_H : 0)
                      return (gt + gb) / 2
                    }
                    const gapTop = Math.min(yTop, yBot) + BOX_H / 2
                                   + (colIdx > 0 && upper?.score ? SCORE_H : 0)
                    const gapBot = Math.max(yTop, yBot) - BOX_H / 2
                                   - (lower?.realName ? NOTE_H : 0)
                    const gapMid = (gapTop + gapBot) / 2
                    // What the score, the ETA and the bell all hang from.
                    const gapMidTravel = trav(gapMid, midOf(ccN), 'top')
                    /* Whether the upset bell hangs in this column's right-hand
                       corner. Anything centred in the gap between two opponents
                       shares that corner with it, so it has to know.
                       The same guard the overlay below uses, not just the upset
                       test: a column with no round after it draws no bell at
                       all, and reserving the corner there would push the score
                       off centre for nothing — which is the fault this exists to
                       fix, in a different disguise. */
                    const bell = (() => {
                      if (!nextCenters || nextC < 1) return false
                      const { p1: bA, p2: bB } = resolved[m.id] || {}
                      const pick = picks?.[m.id] ?? null
                      const rA = bA != null ? drawRanks[bA] : null
                      const rB = bB != null ? drawRanks[bB] : null
                      if (pick == null || rA == null || rB == null) return false
                      return pick !== (rA <= rB ? bA : bB)
                    })()
                    return (
                      <Fragment key={`mo${m.id}`}>
                        <div
                          className={`cv-match-outline${isMissingPick ? ' cv-match-outline--missing' : ''}`}
                          style={outlineTravel}
                        />
                        {isLive && (
                          <span className={`in-progress-badge${isSuspended ? ' in-progress-badge--suspended' : ''}`} style={{ position: 'absolute', top, left: '50%', transform: 'translate(-50%, -50%)' }}>
                            {isSuspended ? 'Suspended' : 'In Progress'}
                          </span>
                        )}
                        {/* Its counterpart for a match with a slot but no play
                            yet — same badge, indigo, matching the time inside
                            the box so the two read as one statement. */}
                        {!isLive && !m.winner && !m.is_bye && m.expected_start_at && (
                          <span className="in-progress-badge in-progress-badge--scheduled"
                                style={{ position: 'absolute', top, left: '50%', transform: 'translate(-50%, -50%)' }}>
                            Scheduled
                          </span>
                        )}
                        {/* Running score, centred in the gap the LIVE_SPREAD
                            nudge opened between this match's two opponents.
                            Sized to fill that gap; the --sN modifier steps the
                            type down once a score is long enough to threaten
                            the column's width (see CombinedView.css — 2 and 3
                            sets share a size, since 3 sets fits at full size
                            everywhere but compact). */}
                        {/* When this match is due, in the same gap the live
                            score uses — that space belongs to the MATCH, not to
                            either player, which is what makes it read as "these
                            two, at this time". Shown only while it is still to
                            come: once it is under way or over, when it was due
                            says nothing the score does not say better. */}
                        {!isLive && !m.winner && !m.is_bye && (() => {
                          const label = expectedStartLabel(
                            m.expected_start_at, m.expected_source, scheduleZone)
                          if (!label) return null
                          // "Today at ~5:55 PM PDT" -> day part, time part. Two
                          // spans so a phone can stack them instead of shrinking
                          // the type to fit one line — everywhere but the
                          // leftmost column, which has no vertical room for a
                          // second line and shrinks instead (see the CSS).
                          const cut = label.indexOf(' at ')
                          const day = cut > 0 ? label.slice(0, cut + 3) : label
                          const time = cut > 0 ? label.slice(cut + 4) : ''
                          return (
                            <span
                              className={`cv-eta${colIdx > 0 ? ' cv-eta--roomy' : ''}${bell ? ' cv-eta--bell' : ''}`}
                              style={gapMidTravel}
                            >
                              <span className="cv-eta-day">{day}</span>
                              {time && <> <span className="cv-eta-time">{time}</span></>}
                            </span>
                          )
                        })()}
                        {isLive && (() => {
                          // Same coherence rule as BracketView: when a fresh
                          // snapshot exists its games are used, so the point
                          // beside them describes the same instant. ESPN lags up
                          // to 60s, and splicing the two shows a point from
                          // after a game the set score has not caught up to.
                          const snapGames = m.live_point?.games ?? null
                          const nodes = liveScoreNodes(
                            snapGames
                              ? [snapGames[0], snapGames[1], m.live_point.serving,
                                 snapGames[0].map((_, i) =>
                                   i === snapGames[0].length - 1
                                     ? null
                                     : Number(snapGames[0][i]) > Number(snapGames[1][i]))]
                              : m.live_scores)
                          if (!nodes) return null
                          // The point rides with the set score rather than in a
                          // slot of its own: this gap belongs to the match, and
                          // a second floating element in it would compete with
                          // the score for the same centre line. Absent whenever
                          // no fresh snapshot exists, which is every draw the
                          // poller is not watching.
                          const lp = m.live_point ?? null
                          const pts = lp?.point ?? null
                          const showPts = pts && pts.some(p => p != null)
                          return (
                            <span
                              className={`cv-live-score cv-live-score--s${Math.min(nodes.length, 4)}${colIdx > 0 ? ' cv-live-score--roomy' : ''}${bell ? ' cv-live-score--bell' : ''}${isSuspended ? ' cv-live-score--suspended' : ''}`}
                              style={gapMidTravel}
                            >
                              {nodes}
                              {showPts && <LivePoint pts={pts} tiebreak={lp.tiebreak} />}
                            </span>
                          )
                        })()}
                      </Fragment>
                    )
                  })}

                  {Array.from({ length: count }, (_, i) => {
                    const box = c === 0 ? entrantBox(c, i) : winnerBox(c, i)
                    const p = box.player
                    const fit = box.isBye ? null : slotName(p, box.serving)
                    return (
                      <div key={box.key} className="cv-slot" style={slotStyle(c, i, cc[i])}>
                        <div
                          className={`cv-box${box.isBye ? ' cv-box--bye' : ''}${!box.isBye && !p ? ' cv-box--tbd' : ''}${box.correct ? ' cv-box--correct' : ''}${box.wrong ? ' cv-box--wrong' : ''}${box.clickable ? ' cv-box--clickable' : ''}${p != null && p.id === hoveredPlayerId ? ' cv-box--highlight' : ''}`}
                          onClick={box.onClick}
                          /* How the effect above finds this player again once
                             the window has moved and these boxes have been
                             replaced by the next round's. */
                          data-player-id={p?.id}
                          onMouseEnter={p != null ? () => setHoveredPlayerId(p.id) : undefined}
                          onMouseLeave={p != null ? () => setHoveredPlayerId(null) : undefined}
                        >
                          {box.isBye ? (
                            <span className="cv-name cv-name--muted">BYE</span>
                          ) : (
                            <>
                              <span className="cv-badges"><SeedBadge player={p} drawRanks={drawRanks} /></span>
                              {!compact && <Flag nat={p?.nationality} />}
                              <span className={`cv-name${isUnnamedQ(p) ? ' cv-name--muted' : ''}`}
                                    style={fit.scale < 1 ? { fontSize: `${fit.scale}em` } : undefined}
                                    title={p?.nationality ? `${p.name} (${p.nationality})` : (p?.name || undefined)}>
                                {fit.text}
                              </span>
                              {box.serving && <span className="cv-serving" title="Serving"><TennisBall /></span>}
                              <EntryBadge player={p} />
                            </>
                          )}
                        </div>
                        {/* Rendered AFTER cv-box so it paints on top; the box's own
                            top border is removed for wrong picks (see .cv-box--wrong)
                            so it never shows through underneath this label. */}
                        {box.realName && <div className="cv-real-winner" title={box.realFullName || undefined}>{box.realName}</div>}
                        {/* The leftmost pane never shows a score (no room under
                            its boxes). Going forward, THIS column becomes the
                            leftmost the moment the gesture commits — so the
                            score does not disappear on release, it fades across
                            the gesture that is taking its room away.
                            Backward needs nothing: renderStart is already the
                            destination's start, so no column changes index. */}
                        {colIdx > 0 && box.score && (
                          <div className={`cv-score${scrubbing && !backward && colIdx === 1 ? ' cv-score--yielding' : ''}`}>
                            {box.score}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>

                {(() => {
                  if (!nextCenters) return null
                  return (
                    <div className="cv-gap" style={{ width: COL_GAP, height: totalH, position: 'relative' }}>
                      <Connectors leftCenters={cc} rightCenters={nextCenters} totalH={totalH} />
                    </div>
                  )
                })()}
              </div>
            )
          })}

          {/* H2H chips + upset bells, rendered as ONE overlay that's the last
              child of cv-body — painted after (on top of) every column, so
              they're never subject to a column's own stacking level (which is
              what keeps each connector line tucked behind its box edges). */}
          <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
            {visible.map((c, colIdx) => {
              const isLastVisible = colIdx === visible.length - 1
              const nextC = isLastVisible ? afterC : visible[colIdx + 1]
              const nextCenters = isLastVisible ? afterCenters : centers[nextC]
              if (!nextCenters || nextC < 1) return null
              // The same column's centres one round on. The chips hang off the
              // boxes they point at, so they travel with them — without this
              // the H2H buttons and bells stayed put while the bracket moved
              // out from under them. Falls back to no travel for the trailing
              // stub past the window, which is off-screen anyway.
              const nextCentersScrub = centersNext?.[nextC] || null
              const gapX = colIdx * (colW + COL_GAP) + colW
              // The chips belong to the column they hang off, so they have to
              // leave with it. This overlay is a sibling of the columns, not a
              // child, so .cv-col--leaving never reached them and they slid off
              // the edge at full opacity as loose pills.
              const chipsLeaving = scrubbing
                && colIdx === (backward ? visible.length - 1 : 0)
              const chips = nextCenters.map((y, ri) => {
                const chipTop = trav(y, nextCentersScrub?.[ri], 'top')
                const m = R[nextC - 1][ri]
                const { p1: aId, p2: bId } = resolved[m.id] || {}
                const a = aId != null ? playerById[aId] : null
                const b = bId != null ? playerById[bId] : null
                // H2H compares who really played; the bell below stays on the
                // cascade, since it is about the user's pick, not the result.
                const { p1: hAId, p2: hBId } = h2hResolved[m.id] || {}
                const ha = hAId != null ? playerById[hAId] : null
                const hb = hBId != null ? playerById[hBId] : null
                const pickId = picks?.[m.id] ?? null
                const rankA = aId != null ? drawRanks[aId] : null
                const rankB = bId != null ? drawRanks[bId] : null
                const expectedId = rankA != null && rankB != null ? (rankA <= rankB ? aId : bId) : null
                const isUpsetPick = pickId != null && expectedId != null && pickId !== expectedId
                return (
                  <Fragment key={m.id}>
                    {/* Both opponents known is the bar, not TE coverage — a
                        player we have not matched to Tennis Explorer must not
                        take the button away from a real match. */}
                    {ha?.name && hb?.name && (
                      <button
                        className="cv-h2h"
                        style={{ ...chipTop, left: gapX + H2H_X, pointerEvents: 'auto' }}
                        title={`Head-to-head: ${ha.name} vs ${hb.name}`}
                        onClick={() => setH2H({ p1: ha, p2: hb, match: m })}
                      >
                        H2H
                      </button>
                    )}
                    {/* Group chip: same pill as H2H, on the match outline's
                        LEFT border instead of its right (the outline overhangs
                        its column by 8px each side, which is what H2H_X
                        centres on). Completed matches only — an undecided
                        match has no outcome to have been right about. */}
                    {/* Hidden entirely while other players' picks are withheld
                        (a draw whose picks stay editable after the first ball).
                        The popup would open onto "0 / 0 / Nobody", which reads
                        as "nobody predicted this" rather than "not shown yet" —
                        a wrong answer is worse than no button. */}
                    {m.winner?.id != null && !m.is_bye && !predictionsHidden && (
                      <button
                        className="cv-group"
                        style={{ ...chipTop, left: colIdx * (colW + COL_GAP) - H2H_X, pointerEvents: 'auto' }}
                        title={`Who predicted ${m.winner.name}?`}
                        aria-label={`Who predicted ${m.winner.name}?`}
                        onClick={() => setPredictorsMatch(m)}
                      >
                        <GroupIcon />
                      </button>
                    )}
                    {isUpsetPick && (
                      <UpsetBell style={{ ...chipTop, left: gapX + H2H_X - BELL_OFFSET, pointerEvents: 'auto' }} />
                    )}
                  </Fragment>
                )
              })
              return chipsLeaving
                ? <div key={c} className="cv-col--leaving">{chips}</div>
                : chips
            })}
          </div>
        </div>
        </div>
        </div>
      </div>
    </>
  )
}
