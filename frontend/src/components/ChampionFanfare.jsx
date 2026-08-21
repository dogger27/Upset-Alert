import { createPortal } from 'react-dom'
import { useMemo } from 'react'
import './ChampionFanfare.css'

/* What gets thrown. Trophies and crowns lead because they name the occasion;
   the rest is confetti and exists to fill the screen. */
const TOKENS = ['🏆', '👑', '🥇', '⭐', '✨', '🎉', '🎊', '🌟', '💫', '🏅']

/* One burst of 44 pieces. Enough to read as an explosion at a glance and few
   enough that a phone still runs it at frame rate — every piece is one span
   moving on transform and opacity, which the compositor can do without
   touching layout. */
const PIECES = 44

/**
 * Ten seconds of nonsense for a champion.
 *
 * Rendered into a portal at the top of the document rather than inside the card
 * that triggered it: the card is inside a grid of fixed-height cells with its
 * own stacking context, and a celebration that has to cover the screen cannot
 * be a child of one cell of it.
 *
 * pointer-events: none throughout. The page underneath stays completely usable
 * — a ten-second animation that blocks a tap is a ten-second outage.
 *
 * Unmounts itself by unmounting the hook that renders it: useScoreEvent clears
 * the tier after FX_MS.champion, so nothing here has to own a timer, and the
 * animation and the lifetime cannot drift apart.
 */
export default function ChampionFanfare({ name }) {
  // Fixed at mount. Re-rolling on every render would restart every piece's
  // trajectory each time the parent updated — and the parent is a live score,
  // so it updates constantly.
  const pieces = useMemo(() => Array.from({ length: PIECES }, (_, i) => ({
    token: TOKENS[i % TOKENS.length],
    // Spread around the full circle with a little jitter, so it reads as a
    // burst rather than as spokes on a wheel.
    angle: (360 / PIECES) * i + (Math.random() * 14 - 7),
    distance: 38 + Math.random() * 46,     // vh from the centre
    delay: Math.random() * 900,            // ms
    spin: (Math.random() * 1080 - 540),    // deg over its flight
    size: 1.6 + Math.random() * 2.4,       // rem
    drift: Math.random() * 30 - 15,        // deg of arc on the way out
  })), [])

  return createPortal(
    <div className="fanfare" role="presentation" aria-hidden="true">
      <div className="fanfare-glow" />
      <div className="fanfare-rays" />

      <div className="fanfare-centre">
        <div className="fanfare-trophy">🏆</div>
        {name && <div className="fanfare-name">{name}</div>}
        <div className="fanfare-title">Champion</div>
      </div>

      {pieces.map((p, i) => (
        <span
          key={i}
          className="fanfare-piece"
          style={{
            '--angle': `${p.angle}deg`,
            '--drift': `${p.drift}deg`,
            '--distance': `${p.distance}vh`,
            '--spin': `${p.spin}deg`,
            '--size': `${p.size}rem`,
            animationDelay: `${p.delay}ms`,
          }}
        >
          {p.token}
        </span>
      ))}
    </div>,
    document.body,
  )
}
