/*
 * The site's scoreboard events, as plain logic: WHAT just happened to a
 * match, and for how long to say so. The drawing lives in fx.jsx.
 *
 * Ported whole from hooks/useFlashOnChange.js, hooks/useScoreEvent.js and
 * pages/Schedule.jsx (scoreMarks, arrivalTier). Every rule in them is
 * load-bearing and most are not obvious — silent on first render, arrival
 * as the exception, counting games rather than comparing them — so this is
 * a copy, not a rewrite.
 */
import { useEffect, useRef, useState } from 'react'
import { AccessibilityInfo } from 'react-native'
import { parseSet } from './score'

/* True for a moment after `value` changes, false otherwise. NOT on first
   render: remounting cannot tell "this number changed" from "this number
   has just appeared", and every score on screen would flash on load. The
   timer is the animation's own length (fx.jsx BUMP_MS) and stays in step
   with it. */
export const BUMP_MS = 2600
export function useFlashOnChange(value, ms = BUMP_MS) {
  const prev = useRef(value)
  const [flash, setFlash] = useState(false)
  useEffect(() => {
    if (prev.current === value) return
    prev.current = value
    setFlash(true)
    const t = setTimeout(() => setFlash(false), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return flash
}

/* How long each tier stays on screen. Escalating, because the things they
   mark escalate: a game is one of a dozen in a set, a champion one a year. */
export const FX_MS = { game: 3200, set: 4200, match: 5200, champion: 10000 }

/* The most significant thing that just happened to a match, or null.
   `marks` is [tier, value] pairs, LOWEST TIER FIRST; any value that differs
   from the last render counts as that tier, and the highest wins — a set
   ending also ends a game, and four watchers would fire three animations on
   top of each other. Silent on first render; `onArrival` is the one
   exception, for a match the DATA says finished moments ago while nobody
   was watching (the normal phone case). Two effects, deliberately: the
   arrival one is mount-only and survives StrictMode's double mount. */
export function useScoreEvent(marks, onArrival = null) {
  const prev = useRef(null)
  const [fx, setFx] = useState(null)
  const sig = marks.map(m => m[1]).join('')

  useEffect(() => {
    const before = prev.current
    prev.current = marks.map(m => m[1])
    if (before === null) return
    let hit = null
    for (let i = 0; i < marks.length; i++) {
      if (marks[i][1] !== before[i]) hit = marks[i][0]
    }
    if (!hit) return
    setFx(hit)
    const t = setTimeout(() => setFx(null), FX_MS[hit] ?? 3000)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig])

  useEffect(() => {
    if (!onArrival) return
    setFx(onArrival)
    const t = setTimeout(() => setFx(null), FX_MS[onArrival] ?? 3000)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return fx
}

/* What a schedule row is watched on, lowest tier first. COUNTED, not
   compared: "games played" going up by one IS a game finishing. The set in
   play is left out of the decided count, or every game the leader wins
   would register as the set ending. A final is the only match that also
   ends a draw — main-draw singles only; a doubles final ends nothing anyone
   picked. */
export function scoreMarks(e) {
  const live = e.status === 'live'
  const lp = e.live_point ?? null
  const g = lp?.games ?? (e.live_scores ? [e.live_scores[0], e.live_scores[1]] : null)
  const sets = live ? g : (e.scores ? [e.scores[0], e.scores[1]] : null)
  let games = 0, decided = 0
  if (sets) {
    const n = Math.max(sets[0]?.length ?? 0, sets[1]?.length ?? 0)
    for (let i = 0; i < n; i++) {
      const x = Number(parseSet(sets[0]?.[i]).g) || 0
      const y = Number(parseSet(sets[1]?.[i]).g) || 0
      games += x + y
      const inPlay = live && i === n - 1 && !lp?.match_tiebreak
      if (!inPlay && x !== y) decided += 1
    }
  }
  const done = e.status === 'completed' ? 1 : 0
  const isFinal = e.discipline === 'singles' && e.stage === 'main'
    && /^(f|final)$/i.test(String(e.round_label ?? '').trim())
  return [
    ['game', games],
    ['set', decided],
    ['match', done],
    ['champion', done && isFinal ? 1 : 0],
  ]
}

/* How recently a match has to have finished for its result to still count
   as news when the screen opens. */
const JUST_FINISHED_MS = 90_000

/* The tier to fire on FIRST render, or null to stay quiet. */
export function arrivalTier(e, marks) {
  if (e.status !== 'completed' || !e.completed_at) return null
  const at = Date.parse(e.completed_at)
  if (!Number.isFinite(at) || Date.now() - at > JUST_FINISHED_MS) return null
  return marks[3][1] ? 'champion' : 'match'
}

/* Motion is the part that is optional; knowing the score changed is not.
   With Reduce Motion on, the wrappers in fx.jsx keep their colour and drop
   their movement. */
export function useReduceMotion() {
  const [reduce, setReduce] = useState(false)
  useEffect(() => {
    let alive = true
    AccessibilityInfo.isReduceMotionEnabled?.().then(v => { if (alive) setReduce(!!v) }).catch(() => {})
    const sub = AccessibilityInfo.addEventListener?.('reduceMotionChanged', v => setReduce(!!v))
    return () => { alive = false; sub?.remove?.() }
  }, [])
  return reduce
}
