import { useEffect, useRef, useState } from 'react'

/** How long the banner stays up. Long enough to read across a page of rows. */
const SHOUT_MS = 3600

/**
 * True for a moment after the receiver wins a game.
 *
 * Derived, not fetched. Nothing in the live feed says "break" — but everything
 * needed to know one happened is already on the row, once you have two
 * consecutive readings of it:
 *
 *   the side whose game count went up won that game
 *   the server of that game is who was serving BEFORE it went up
 *   they differ  ->  a break
 *
 * `serving` is who is serving RIGHT NOW and flips the moment a game ends, so by
 * the time the new game count is visible it already names the NEXT server. The
 * previous reading is the only place the relevant one exists, which is why this
 * cannot be computed from a single snapshot however complete that snapshot is.
 *
 * Tiebreaks are excluded. Serve alternates inside one, so "who served this
 * game" has no single answer, and a set won 7-6 is not a break of anything.
 */
export default function useServiceBreak(games, serving, tiebreak) {
  const prev = useRef(null)
  const [broke, setBroke] = useState(false)

  // A string, so the effect compares by value rather than by array identity.
  const sig = games ? `${games[0]?.join(',')}|${games[1]?.join(',')}|${serving}` : ''

  useEffect(() => {
    if (!games) { prev.current = null; return }

    const total = (side) => games[side].reduce((n, c) => n + (Number(c) || 0), 0)
    const now = { a: total(0), b: total(1), serving, tiebreak: !!tiebreak }
    const before = prev.current
    prev.current = now
    if (!before) return

    // Exactly one game, by exactly one player. Anything else is a reconnection,
    // a correction, or a set rolling over with a scoreline we did not watch
    // arrive — none of which is a game being won in front of us.
    const gainA = now.a - before.a
    const gainB = now.b - before.b
    if (gainA + gainB !== 1 || gainA < 0 || gainB < 0) return

    // A tiebreak has no single server. Tested against the reading BEFORE, which
    // is the game that was actually being played.
    if (before.tiebreak) return
    if (before.serving !== 1 && before.serving !== 2) return

    const wonBy = gainA === 1 ? 1 : 2
    if (wonBy === before.serving) return

    setBroke(true)
    const t = setTimeout(() => setBroke(false), SHOUT_MS)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig])

  return broke
}
