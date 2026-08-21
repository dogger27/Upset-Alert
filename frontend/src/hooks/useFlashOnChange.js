import { useEffect, useRef, useState } from 'react'

/**
 * True for a moment after `value` changes, false otherwise.
 *
 * For marking a number that has just moved. A live score arrives over SSE with
 * no sound and no motion, so a point won while you are looking at the row is
 * indistinguishable from one won a minute ago — the page simply reads
 * differently the next time you glance at it.
 *
 * NOT ON FIRST RENDER, which is the whole reason this is a hook rather than a
 * `key` that remounts the element and lets a CSS animation replay. Remounting
 * cannot tell "this number changed" from "this number has just appeared", so
 * every score on the page would flash on load, on a view switch, and on every
 * change of filter — motion that means nothing, at the moment there is most of
 * it to look at.
 *
 * The timer is the animation's own length. It only ever starts in response to a
 * change, so there is no loop here: nothing this returns feeds back into
 * `value`.
 */
export default function useFlashOnChange(value, ms = 700) {
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
