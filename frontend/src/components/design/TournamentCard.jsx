import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import { TierBadge } from './TierBadge.jsx'
import { SurfacePill } from './SurfacePill.jsx'

/* Module scope so the OOP link is the same pill as the status ones rather than
   a lookalike — one definition, so they cannot drift apart. */
const pillBase = {
  display: 'inline-flex', alignItems: 'center', gap: 5,
  fontFamily: 'var(--font-body)', fontWeight: 'var(--fw-bold)', fontSize: '0.72rem',
  padding: '4px 10px', borderRadius: 'var(--radius-pill)', whiteSpace: 'nowrap',
}

/* The star alone, with the word behind it.
   "★ Competing" was the widest thing in the footer and it says one bit: you are
   in this one. The star carries that on its own once you have seen it named
   once, and the room it gives back is what lets the OOP button sit beside it.

   The label still has to be reachable, so: hover on a pointer, tap on a touch
   screen, and focus for a keyboard. Not a `title` — the native tooltip takes
   about a second to appear, never appears at all on touch, and cannot be
   styled, which is why nothing else in this app uses one.

   Portalled to the body because the card sets overflow: hidden to clip its own
   accent bar, and a popover in normal flow is cut off by it — the same trap the
   bracket's upset bell hit. Position comes from the trigger's own rect at the
   moment it opens, so it needs no layout knowledge of its ancestors. */
function CompetingStar() {
  const ref = useRef(null)
  const [tip, setTip] = useState(null)

  const open = () => {
    const r = ref.current?.getBoundingClientRect()
    if (r) setTip({ x: r.left + r.width / 2, y: r.top })
  }
  const close = () => setTip(null)

  // A tap must not follow the card's link, and must not be delivered twice —
  // a touch that fires both a synthetic click here and the anchor's navigation
  // would open the draw instead of the popover.
  const toggle = (e) => {
    e.preventDefault()
    e.stopPropagation()
    tip ? close() : open()
  }

  // The rect is captured on open, so anything that moves the trigger afterwards
  // leaves the popover behind. Cheaper and steadier than following it: close.
  useEffect(() => {
    if (!tip) return
    const away = () => close()
    window.addEventListener('scroll', away, true)
    window.addEventListener('resize', away)
    document.addEventListener('pointerdown', away)
    return () => {
      window.removeEventListener('scroll', away, true)
      window.removeEventListener('resize', away)
      document.removeEventListener('pointerdown', away)
    }
  }, [tip])

  return (
    <>
      <span
        ref={ref}
        role="button"
        tabIndex={0}
        aria-label="Competing"
        style={{
          ...pillBase, background: 'var(--green-600)', color: '#fff',
          boxShadow: 'var(--glow-green)', cursor: 'pointer',
          padding: '4px 9px', fontSize: '0.8rem', lineHeight: 1,
        }}
        onMouseEnter={open}
        onMouseLeave={close}
        onFocus={open}
        onBlur={close}
        onClick={toggle}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') toggle(e) }}
      >
        ★
      </span>
      {tip && createPortal(
        <span
          role="tooltip"
          style={{
            position: 'fixed', left: tip.x, top: tip.y - 8,
            transform: 'translate(-50%, -100%)', zIndex: 60,
            ...pillBase, background: 'var(--green-600)', color: '#fff',
            boxShadow: 'var(--shadow-md, 0 6px 20px rgba(0,0,0,0.35))',
            letterSpacing: '0.03em', pointerEvents: 'none',
          }}
        >
          Competing
        </span>,
        document.body
      )}
    </>
  )
}

function renderFooter({ section, pickState, drawDates, oopPill }) {
  /* Status on the left, the card's own action in the middle, order of play on
     the right.
     Flex that WRAPS, not a three-track grid. The grid centred the middle item
     against the card exactly, which was worth having while the row held two
     short pills — but every item here is nowrap, and a grid track will not go
     under its content, so once the right-hand button spelled out "Order of
     Play" the open card's three items measured wider than a 375px phone gives
     them and the card, which clips its own accent bar with overflow: hidden,
     cut the last one off. Wrapping costs a few pixels of drift in the middle
     when the two ends differ in width, and buys a row that is never truncated
     at any width. A label you cannot read is worse than one slightly off
     centre. */
  const centredRow = (left, centre) => (
    <div style={{
      display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6,
    }}>
      <span>{left}</span>
      <span style={{ flex: '1 1 auto', textAlign: 'center', minWidth: 0 }}>{centre}</span>
      <span style={{ marginLeft: 'auto' }}>{oopPill}</span>
    </div>
  )

  if (section === 'open') {
    const map = {
      complete: { ...pillBase, background: 'var(--success-bg)', color: 'var(--success)' },
      partial:  { ...pillBase, background: 'var(--warning-bg)', color: 'var(--warning)' },
      none:     { ...pillBase, background: 'var(--danger-bg)',  color: 'var(--danger)' },
    }
    const label = { complete: '✓ Picks entered', partial: '⚠ Picks incomplete', none: '✕ Picks not started' }
    const state = pickState || 'none'
    // Same three tracks as `active` below, so the OOP button sits in the same
    // corner of the card whether the draw is open or under way. It only ever
    // appeared once picks had closed, which is backwards: a tournament whose
    // qualifying is being played while its main draw is still open is exactly
    // when someone wants the order of play, and Winston-Salem spent its
    // qualifying Saturday with no way to reach it from the dashboard at all.
    return centredRow(
      <span style={map[state]}>{label[state]}</span>,
      <span style={{
        fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: '0.8rem',
        letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--brand-text)',
      }}>Make picks →</span>
    )
  }

  if (section === 'active') {
    const competing = pickState === 'complete'
    return centredRow(
      <span style={{ ...pillBase, background: 'var(--n-150)', color: 'var(--text-soft)' }}>🔒 Closed</span>,
      competing ? <CompetingStar /> : null
    )
  }

  if (section === 'upcoming' && drawDates) {
    const item = (k, v) => (
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'var(--text-muted)' }}>
        <span style={{ fontWeight: 700, color: 'var(--text-soft)' }}>{k}:</span> {v}
      </span>
    )
    return (
      <div style={{ display: 'flex', gap: 14 }}>
        {drawDates.da && item('Draw', drawDates.da)}
        {drawDates.qual && item('Qual', drawDates.qual)}
      </div>
    )
  }

  if (section === 'lastweek') {
    const competed = pickState === 'complete'
    return centredRow(
      <span style={{ ...pillBase, background: 'var(--n-150)', color: 'var(--text-muted)' }}>Completed</span>,
      competed
        ? <span style={{ ...pillBase, background: 'var(--success-bg)', color: 'var(--success)' }}>★ Competed</span>
        : null
    )
  }

  return null
}

function GlobeIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"
      strokeLinecap="round" strokeLinejoin="round"
      style={{ width: 15, height: 15, display: 'block' }}
    >
      <circle cx="12" cy="12" r="10" />
      <ellipse cx="12" cy="12" rx="4" ry="10" />
      <line x1="2" y1="12" x2="22" y2="12" />
    </svg>
  )
}

export function TournamentCard({ tour = 'ATP', name, city, surface = 'grass', tier = '500', dateRange, section = 'open', pickState = null, drawDates = null, to, wikiUrl, oopTo, onGuestClick }) {
  const [hover, setHover] = useState(false)
  const isATP = String(tour).toUpperCase() === 'ATP'
  const accent = isATP ? 'var(--atp-500)' : 'var(--wta-500)'
  const accentDeep = isATP ? 'var(--atp-700)' : 'var(--wta-700)'
  // Role tokens, not the raw --atp-50/--wta-50 ramp steps: those are literal
  // near-whites, so on a dark theme hovering a card turned it into a white
  // slab with near-white text on it.
  const tint = isATP ? 'var(--atp-tint)' : 'var(--wta-tint)'
  const glow = isATP ? 'var(--glow-atp)' : 'var(--glow-wta)'
  const interactive = section !== 'upcoming'

  /* Same pill as the ones beside it — only the ink differs, so it reads as an
     action rather than another status. */
  const oopPill = oopTo ? (
    <Link
      to={oopTo}
      onClick={e => e.stopPropagation()}
      style={{ ...pillBase, background: 'var(--n-150)', color: 'var(--brand-text)',
               textDecoration: 'none', letterSpacing: '0.04em' }}
    >
      {/* Spelled out. "OOP" is the term inside this codebase, not one a reader
          arrives with, and the abbreviation saved room the footer no longer
          needs now that "Competing" has collapsed to its star. */}
      Order of Play
    </Link>
  ) : null

  const footer = renderFooter({ section, pickState, drawDates, oopPill })

  const cardStyle = {
    position: 'relative', display: 'block', textDecoration: 'none', color: 'inherit',
    background: hover && interactive ? tint : 'var(--surface-card)',
    border: '1px solid var(--border)', borderRadius: 'var(--radius-md)',
    boxShadow: hover && interactive ? glow : 'var(--shadow-sm)',
    overflow: 'hidden',
    cursor: interactive ? 'pointer' : 'default',
    transform: hover && interactive ? 'translateY(-3px)' : 'translateY(0)',
    transition: 'transform var(--dur) var(--ease-out), box-shadow var(--dur) var(--ease-out), background var(--dur) var(--ease-out)',
  }

  const inner = (
    <>
      <span style={{
        position: 'absolute', left: 0, top: 0, bottom: 0,
        width: hover && interactive ? 6 : 'var(--accent-bar)',
        background: `linear-gradient(to bottom, ${accent}, ${accentDeep})`,
        transition: 'width var(--dur) var(--ease-out)',
      }} />
      <div style={{ padding: '14px 16px 14px 20px', display: 'flex', flexDirection: 'column', gap: 9 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
          <span style={{
            fontFamily: 'var(--font-display)', fontWeight: 'var(--fw-bold)',
            fontSize: '1.18rem', letterSpacing: '0.01em', lineHeight: 1.05, color: 'var(--text)',
          }}>{name}</span>
          <TierBadge tour={tour} tier={tier} name={name} size="sm" style={{ flexShrink: 0 }} />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          {city && <span style={{ fontFamily: 'var(--font-body)', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-soft)' }}>{city}</span>}
          <SurfacePill surface={surface} />
          {dateRange && <span style={{
            marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: '0.72rem',
            color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums',
          }}>{dateRange}</span>}
        </div>
        {footer && (
          <div style={{ borderTop: '1px solid var(--border)', paddingTop: 9, marginTop: 1 }}>
            {footer}
          </div>
        )}
      </div>
      {wikiUrl && (
        <a
          href={wikiUrl}
          target="_blank"
          rel="noopener noreferrer"
          onClick={e => e.stopPropagation()}
          title="View draw on Wikipedia"
          style={{
            position: 'absolute', bottom: 10, right: 10,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            width: 24, height: 24, borderRadius: '50%',
            color: 'var(--text-muted)',
            opacity: 0.55,
            transition: 'opacity var(--dur)',
          }}
          onMouseEnter={e => e.currentTarget.style.opacity = '1'}
          onMouseLeave={e => e.currentTarget.style.opacity = '0.55'}
        >
          <GlobeIcon />
        </a>
      )}
    </>
  )

  if (onGuestClick && interactive) {
    return (
      <div style={cardStyle} onClick={onGuestClick} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
        {inner}
      </div>
    )
  }
  if (to && interactive) {
    return (
      <Link to={to} style={cardStyle} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
        {inner}
      </Link>
    )
  }
  return (
    <div style={cardStyle} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
      {inner}
    </div>
  )
}
