import { useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import './UserName.css'

/** A member's handle, with their full name on hover where the league allows
    it (pass full_name only when it should show — the caller owns the gate).

    PORTALED, not a CSS ::after: this span lives inside ellipsis containers
    (`overflow: hidden` on .lt-progress-name-text and friends), and an
    overflow ancestor clips a pseudo-element tooltip into invisibility — the
    exact trap the H2H form boxes hit before, fixed the same way. Fixed
    positioning from getBoundingClientRect survives every ancestor. Touch has
    no hover, so a tap toggles it. */
export default function UserName({ user, className = '' }) {
  const handle = user?.username || user?.display_name
  const tooltip = user?.full_name && user.full_name !== handle ? user.full_name : null
  const ref = useRef(null)
  const [pos, setPos] = useState(null)

  if (!tooltip) {
    return <span className={className}>{handle}</span>
  }
  const open = () => {
    const r = ref.current?.getBoundingClientRect()
    if (r) setPos({ x: r.left + r.width / 2, y: r.top })
  }
  return (
    <>
      <span
        ref={ref}
        className={`username-hover ${className}`}
        onMouseEnter={open}
        onMouseLeave={() => setPos(null)}
        onTouchStart={() => (pos ? setPos(null) : open())}
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
