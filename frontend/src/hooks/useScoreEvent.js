import { useEffect, useRef, useState } from 'react'

/**
 * How long each tier stays on screen. Escalating, because the things they mark
 * escalate: a game is one of a dozen in a set, a champion is one a year.
 */
export const FX_MS = {
  game: 3200,
  set: 4200,
  match: 5200,
  champion: 10000,
}

/**
 * The most significant thing that just happened to a match, or null.
 *
 * `marks` is an ordered list of [tier, value] pairs, LOWEST TIER FIRST. Any
 * value that differs from the last render counts as that tier happening, and
 * the highest one wins — which is the whole reason this is one hook rather than
 * four. The tiers are not independent events: a set ending also ends a game,
 * and a match ending ends both, so four separate watchers would fire three
 * animations at once on top of each other and the biggest thing that happened
 * would be the hardest to see.
 *
 * Silent on first render, for the same reason useFlashOnChange is: arriving on
 * a page where a match is already finished is not the match finishing. Without
 * that, every completed match on the day would celebrate itself on load, and a
 * champion decided this morning would throw a ten-second party at midnight.
 */
export default function useScoreEvent(marks) {
  const prev = useRef(null)
  const [fx, setFx] = useState(null)
  const sig = marks.map(m => m[1]).join('')

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
    // sig, not marks — a new array every render would re-run this for ever.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig])

  return fx
}
