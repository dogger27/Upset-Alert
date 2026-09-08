/*
 * The geometry of a round scrub, as arithmetic with no React in it.
 *
 * THE MODEL. A draw is rounds of match groups; every group in round r feeds
 * one group in round r+1 — groups 2k and 2k+1 feed group k. On screen each
 * round is a column of groups at one spacing G (a group's height plus the
 * gap between groups), its first group's centre at P + H/2 from the top.
 *
 * A scrub is ONE NUMBER, `pos`: the round the reader is looking at, as a
 * real. 2 is round index 2 settled; 2.4 is forty percent of the way from
 * round 2 to round 3. Every column j knows where it stands from s = pos - j:
 *
 *   s = 0    it is the round on screen, laid out as it settles
 *   s → 1    it is sliding off to the LEFT and its groups are CONDENSING onto
 *            the groups they feed: 2k and 2k+1 close onto k's settled spot,
 *            so the column shrinks to half its span as it leaves
 *   s → -1   it is off to the RIGHT and its groups are SPREAD onto the pairs
 *            that feed them: k sits at the midpoint of 2k and 2k+1, so the
 *            column arrives at twice its settled span and contracts
 *
 * That is the site's telescoping (CombinedView.jsx: collapseOnto and its
 * inverse), and it is why a scrub reads as one animation played either way:
 * pulling the next round in, the outgoing column condenses and the incoming
 * one contracts; pulling the previous round back, the SAME formulas run the
 * other way and the outgoing column expands while the incoming one unfolds.
 * The two columns move coherently — while they are both on screen, a group
 * sits exactly on the midpoint of the two groups feeding it at every value of
 * pos, which is what keeps the picture of the bracket true mid-gesture.
 *
 * THE ANCHOR. The finger is held on a fractional row index of the round it
 * started on — "three and a bit groups down" — and that index survives the
 * spacing changing. Its pixel position is re-derived from the same index at
 * every pos and the scroll offset moved by the difference, so the match under
 * the finger is the match still under the finger when its successor arrives.
 *
 * Nothing here depends on a direction being decided up front: a finger that
 * wanders back across where it started simply carries pos through the
 * integer and the other neighbour's formulas take over. Nor does a commit
 * change any of these numbers, which is what makes the landing frame and the
 * committed frame identical.
 *
 * Every function is a worklet so the gesture can call it on the UI thread;
 * the directive is a plain string, so node runs them unchanged for the tests.
 */

/** Clamp a column offset to the one-round window either formula covers. */
export function clampOffset(s) {
  'worklet'
  return s > 1 ? 1 : s < -1 ? -1 : s
}

/** A row's vertical shift, in points, for its column at offset s = pos - j. */
export function rowShift(i, s, G) {
  'worklet'
  const c = clampOffset(s)
  if (c > 0) return (Math.floor(i / 2) - i) * G * c
  if (c < 0) return (i + 0.5) * G * -c
  return 0
}

/** The finger's fractional row index in a settled column: 0 on the first
    group's centre, 1 on the next. Clamped to the rows that exist, so a finger
    above the first group holds the first group, as the site does. */
export function rowIndexAt(contentY, P, H, G, n) {
  'worklet'
  if (n <= 0 || G <= 0) return 0
  const idx = (contentY - P - H / 2) / G
  return idx < 0 ? 0 : idx > n - 1 ? n - 1 : idx
}

/** Where the anchored row index of the starting column sits, in content
    points, for the column at offset s. Linear interpolation between the
    settled position and the condensed (s > 0) or spread (s < 0) one, so a
    finger on a fractional index moves the way the two rows either side of it
    do. */
export function anchorY(idx, s, P, H, G) {
  'worklet'
  const c = clampOffset(s)
  const base = P + H / 2
  if (c === 0) return base + idx * G
  const i = Math.floor(idx)
  const f = idx - i
  if (c > 0) {
    // Condensing: rows i and i+1 land on their successors' settled rows.
    const target = (1 - f) * Math.floor(i / 2) + f * Math.floor((i + 1) / 2)
    return base + (idx + (target - idx) * c) * G
  }
  // Spreading: every row k opens onto the midpoint of the pair feeding it,
  // which is affine in k, so it holds for a fractional index directly.
  return base + (idx + ((2 * idx + 0.5) - idx) * -c) * G
}

/** The height the scroll content needs at pos: the taller of the two columns
    a fractional pos sits between, the one column at an integer. */
export function contentHeightAt(pos, heights, fallback) {
  'worklet'
  const lo = Math.floor(pos), hi = Math.ceil(pos)
  const a = heights[lo] > 0 ? heights[lo] : fallback
  const b = heights[hi] > 0 ? heights[hi] : fallback
  return a > b ? a : b
}

/** How far the scroll may go at pos without ever having to jump when the
    height snaps to the landed column's: the two neighbours' own limits,
    blended by the fraction between them, which is exactly the landed limit
    at either integer. */
export function scrollLimitAt(pos, heights, fallback, viewportH) {
  'worklet'
  const lo = Math.floor(pos), hi = Math.ceil(pos)
  const f = pos - lo
  const a = heights[lo] > 0 ? heights[lo] : fallback
  const b = heights[hi] > 0 ? heights[hi] : fallback
  const la = a - viewportH > 0 ? a - viewportH : 0
  const lb = b - viewportH > 0 ? b - viewportH : 0
  return la + (lb - la) * f
}

/* Release. One swipe moves at most one round (owner, 2026-09-07), and
   distance decides only WHETHER it counts: a flick lands it, a slow drag
   lands it past COMMIT_PX unless the finger was already coming back, and
   anything shorter settles home. */
export const FLICK_PX_PER_S = 250
export const COMMIT_PX = 40

/** The integer round to settle on. `vx` is the finger's velocity in px/s
    (right is positive, and right is towards EARLIER rounds); `dragPx` is the
    finger's travel since the scrub was recognised, same sign. */
export function settleTarget(pos, r0, vx, dragPx, lo, hi) {
  'worklet'
  const s = pos - r0
  let target
  if (Math.abs(vx) >= FLICK_PX_PER_S) {
    target = vx < 0 ? Math.ceil(pos) : Math.floor(pos)
  } else if (Math.abs(s) >= 0.5) {
    target = r0 + (s > 0 ? 1 : -1)
  } else if (s !== 0 && Math.abs(dragPx) >= COMMIT_PX && -vx * s >= 0) {
    target = r0 + (s > 0 ? 1 : -1)
  } else {
    target = r0
  }
  if (target > r0 + 1) target = r0 + 1
  if (target < r0 - 1) target = r0 - 1
  if (target > hi) target = hi
  if (target < lo) target = lo
  return target
}
