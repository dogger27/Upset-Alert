import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import './UserName.css'

/** A member's handle, with their full name on hover where the league allows
    it (pass full_name only when it should show — the caller owns the gate).

    PORTALED, not a CSS ::after: this span lives inside ellipsis containers
    (`overflow: hidden` on .lt-progress-name-text and friends), and an
    overflow ancestor clips a pseudo-element tooltip into invisibility — the
    exact trap the H2H form boxes hit before, fixed the same way. Fixed
    positioning from getBoundingClientRect survives every ancestor. Touch has
    no hover, so a tap OPENS it — and a timer closes it, because a tap has no
    reliable end. Mouseleave always fires when a pointer goes away; a finger
    just stops touching, and the next tap usually lands on something that does
    not know this tooltip exists — a row, a scroll, another name — so the old
    toggle left full names stranded on screen. */
const TOUCH_DWELL = 3000

export default function UserName({ user, className = '' }) {
  const handle = user?.username || user?.display_name
  const tooltip = user?.full_name && user.full_name !== handle ? user.full_name : null
  const ref = useRef(null)
  const timer = useRef(null)
  const [pos, setPos] = useState(null)

  // Above the guard below, not after it: whether this component has a tooltip
  // depends on its props, and a hook cannot run conditionally.
  useEffect(() => () => clearTimeout(timer.current), [])

  if (!tooltip) {
    return <span className={className}>{handle}</span>
  }
  const close = () => {
    clearTimeout(timer.current)
    setPos(null)
  }
  const open = (dwell = 0) => {
    const r = ref.current?.getBoundingClientRect()
    if (!r) return
    setPos({ x: r.left + r.width / 2, y: r.top })
    clearTimeout(timer.current)
    // Only a touch gets a deadline. A pointer has mouseleave, and a tooltip
    // that vanished from under a stationary cursor would be its own bug.
    if (dwell) timer.current = setTimeout(() => setPos(null), dwell)
  }
  return (
    <>
      <span
        ref={ref}
        className={`username-hover ${className}`}
        onMouseEnter={() => open()}
        onMouseLeave={close}
        onTouchStart={() => (pos ? close() : open(TOUCH_DWELL))}
      >
        {handle}
      </span>
      {pos && createPortal(
        <span className="username-hover-tip"
              style={{ position: 'fixed', left: pos.x, top: pos.y - 6,
                       transform: 'translate(-50%, -100%)' }}>
          {tooltip}
        </span>,
        document.body
      )}
    </>
  )
}
