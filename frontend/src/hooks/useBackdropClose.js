import { useCallback, useRef } from 'react'

/* CLICKING THE BACKDROP CLOSES A POPUP. DRAGGING OFF ONE DOES NOT.
 *
 * `onClick` on a backdrop is not "the user clicked the backdrop": a click
 * event fires on the nearest common ancestor of where the pointer went down
 * and where it came up. Drag the score-history or standings slider past the
 * panel's edge and release — as people do to be sure a slider is at its stop
 * — and mousedown lands on the input while mouseup lands on the backdrop, so
 * the click fires ON THE BACKDROP and the popup shuts. The panel's
 * `stopPropagation` cannot help: the event never passes through the panel.
 *
 * So the gesture has to be both ends: armed on a pointerdown that hits the
 * backdrop itself, disarmed by a pointerup anywhere else. A drag that starts
 * inside the panel never arms it, and one that starts on the backdrop and
 * ends inside the panel is disarmed before the click arrives.
 *
 * Spread the result on the backdrop element; keep the panel's own
 * stopPropagation or not, the target check makes it redundant either way.
 */
export function useBackdropClose(onClose) {
  const armed = useRef(false)
  const onPointerDown = useCallback(e => {
    armed.current = e.target === e.currentTarget
  }, [])
  const onPointerUp = useCallback(e => {
    if (e.target !== e.currentTarget) armed.current = false
  }, [])
  const onClick = useCallback(e => {
    const hit = armed.current && e.target === e.currentTarget
    armed.current = false
    if (hit) onClose?.()
  }, [onClose])
  return { onPointerDown, onPointerUp, onClick }
}
