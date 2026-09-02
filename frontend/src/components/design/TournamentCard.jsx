import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link, useNavigate } from 'react-router-dom'
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
   "★ Competing" and "✓ Picks entered" were the widest things in their footers
   and each says one bit: you are in this one. The star carries that on its own
   once you have seen it named, and the room it gives back is what lets the
   Order of Play button beside it be spelled out. Same glyph in both places on
   purpose — it is the same fact at two moments, before the draw starts and
   after — so `label` differs while nothing else does.

   Only the GOOD state collapses. "Picks incomplete" and "Picks not started"
   keep their words: they are not a badge you have earned, they are something
   you still have to do, and hiding a call to action behind a hover is how it
   goes unnoticed.

   The label has to be reachable by every input, so: hover for a pointer, tap
   for a touch screen, focus for a keyboard. Not a `title` — the native tooltip
   takes about a second, never appears at all on touch, and cannot be styled.

   Portalled to the body because the card sets overflow: hidden to clip its own
   accent bar, and a popover in normal flow is cut off by it — the same trap the
   bracket's upset bell hit. Position comes from the trigger's own rect at the
   moment it opens, so it needs no layout knowledge of its ancestors. */
function InfoStar({ label }) {
  const ref = useRef(null)
  const [tip, setTip] = useState(null)

  const open = () => {
    const r = ref.current?.getBoundingClientRect()
    if (r) setTip({ x: r.left + r.width / 2, y: r.top })
  }
  const close = () => setTip(null)

  /* HOVER IS FOR MICE ONLY, and this is what made a phone need two taps.
     A touch fires a synthetic mouseenter before its click, so the first tap
     opened the popover on enter and the click that followed toggled it straight
     back shut — a tap that visibly did nothing. The second tap worked only
     because mouseenter does not fire again. Gating on pointerType leaves the
     tap with exactly one thing to do. */
  const hover = (fn) => (e) => { if (e.pointerType === 'mouse') fn() }

  const toggle = (e) => {
    // Not the card's link. The star sits inside one, and a tap that bubbled
    // would open the draw instead of the label.
    e.preventDefault()
    e.stopPropagation()
    tip ? close() : open()
  }

  // The rect is captured on open, so anything that moves the trigger afterwards
  // leaves the popover behind. Cheaper and steadier than following it: close.
  useEffect(() => {
    if (!tip) return
    // A pointerdown ON the star is the start of its own toggle, and closing
    // here would race the click that follows — the other half of the two-tap
    // bug. Only somewhere else counts as dismissing.
    const away = (e) => { if (!ref.current?.contains(e.target)) close() }
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
        aria-label={label}
        style={{
          ...pillBase, background: 'var(--green-600)', color: '#fff',
          boxShadow: 'var(--glow-green)', cursor: 'pointer',
          padding: '4px 9px', fontSize: '0.8rem', lineHeight: 1,
        }}
        onPointerEnter={hover(open)}
        onPointerLeave={hover(close)}
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
          {label}
        </span>,
        document.body
      )}
    </>
  )
}

/* The order-of-play button, in both of its states.

   No `date` in the link, deliberately. The schedule page lands on the LATEST
   day it has data for, and that is the right destination from here — a stored
   oop_date is whichever sheet was seen last and can be yesterday's by the time
   anyone clicks. One page owns "which day exists", rather than two places
   guessing and disagreeing.

   The border is what responds to hover: the pill's fill is already carrying its
   own meaning against the pills beside it, and brightening it made the row look
   like it had changed state rather than that something was under the cursor. */
function OopButton({ to }) {
  const [hot, setHot] = useState(false)
  const base = {
    ...pillBase, textDecoration: 'none', letterSpacing: '0.04em',
    border: '1px solid transparent',
    transition: 'border-color var(--dur, 150ms) var(--ease-out, ease), color var(--dur, 150ms) var(--ease-out, ease)',
  }

  if (!to) {
    return (
      <span
        aria-disabled="true"
        title="No order of play published yet"
        style={{ ...base, background: 'var(--n-150)', color: 'var(--text-muted)',
                 opacity: 0.45, cursor: 'default' }}
      >
        Order of Play
      </span>
    )
  }

  return (
    <Link
      to={to}
      onClick={e => e.stopPropagation()}
      onPointerEnter={() => setHot(true)}
      onPointerLeave={() => setHot(false)}
      onFocus={() => setHot(true)}
      onBlur={() => setHot(false)}
      style={{
        ...base, background: 'var(--n-150)', color: 'var(--brand-text)',
        borderColor: hot ? 'var(--brand-line, var(--brand-text))' : 'transparent',
      }}
    >
      {/* Spelled out. "OOP" is the term inside this codebase, not one a reader
          arrives with, and the abbreviation saved room the footer no longer
          needs now that "Competing" has collapsed to its star. */}
      Order of Play
    </Link>
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
    // The action on the left, the state in the middle, order of play on the
    // right — which puts the star in the same centre slot the active card uses,
    // so the one badge does not move as a draw goes from open to under way.
    // "Picks →" rather than "Make picks →": the card it sits on already names
    // the tournament and the arrow already says this goes somewhere, so the
    // verb was the one word carrying nothing, and the row has three items to
    // fit on a phone.
    return centredRow(
      <span style={{
        fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: '0.8rem',
        letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--brand-text)',
      }}>Picks →</span>,
      // Picks entered collapses to the star; the other two keep their words.
      // See the note on InfoStar — an unfinished entry is a thing you still
      // have to do, and a call to action behind a hover goes unnoticed.
      state === 'complete'
        ? <InfoStar label="Picks entered" />
        : <span style={map[state]}>{label[state]}</span>
    )
  }

  if (section === 'active') {
    const competing = pickState === 'complete'
    return centredRow(
      <span style={{ ...pillBase, background: 'var(--n-150)', color: 'var(--text-soft)' }}>🔒 Closed</span>,
      competing ? <InfoStar label="Competing" /> : null
    )
  }

  if (section === 'upcoming') {
    const item = (k, v) => (
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'var(--text-muted)' }}>
        <span style={{ fontWeight: 700, color: 'var(--text-soft)' }}>{k}:</span> {v}
      </span>
    )
    // The OOP button belongs here too — the 'open' card learned this from
    // Winston-Salem's qualifying Saturday, and a Slam is the harder case: its
    // qualifying is PLAYED while the card still says "draw not yet released",
    // so 'upcoming' is exactly when someone wants the US Open's order of play.
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {drawDates?.da && item('Draw', drawDates.da)}
          {drawDates?.qual && item('Qual', drawDates.qual)}
        </div>
        <span style={{ marginLeft: 'auto' }}>{oopPill}</span>
      </div>
    )
  }

  if (section === 'lastweek') {
    const competed = pickState === 'complete'
    // THE SAME THREE TRACKS AS `active`, and the same compact star. A wide
    // "★ Competed" pill in the middle track left no room for the order-of-play
    // button, which wrapped onto a second line — so a finished tournament's
    // card was a different shape from a running one's, for no reason a reader
    // could see. The star carries its meaning in a tooltip, as it does above.
    return centredRow(
      <span style={{ ...pillBase, background: 'var(--n-150)', color: 'var(--text-muted)' }}>Completed</span>,
      competed ? <InfoStar label="Competed" /> : null
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
  const navigate = useNavigate()
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
     action rather than another status.

     Two states, never absent. A tournament with no sheet published yet shows
     the button greyed out rather than not showing it, because a control that
     appears the moment a PDF lands and is missing until then reads as a bug in
     the page rather than as a fact about the tournament. Greyed, it says the
     order of play is a thing that will exist. */
  const oopPill = (
    <OopButton to={oopTo} />
  )

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
        {/* City, surface and dates on ONE line, always.
            It used to wrap, and what wrapped was the date range — pushed onto a
            line of its own by a long city name, where it read as a separate
            fact rather than as the third item in a summary. Nowrap makes the
            city the thing that gives, since a truncated "Winston-Sale…" still
            says where, whereas half a date range says nothing. The surface and
            the dates are short, fixed and never worth shortening. */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'nowrap' }}>
          {city && <span style={{
            fontFamily: 'var(--font-body)', fontSize: '0.8rem', fontWeight: 600,
            color: 'var(--text-soft)',
            minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>{city}</span>}
          <span style={{ flexShrink: 0, display: 'inline-flex' }}><SurfacePill surface={surface} /></span>
          {dateRange && <span style={{
            marginLeft: 'auto', flexShrink: 0,
            fontFamily: 'var(--font-mono)', fontSize: '0.72rem',
            color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums',
            whiteSpace: 'nowrap',
          }}>{dateRange}</span>}
        </div>
        {footer && (
          <div style={{ borderTop: '1px solid var(--border)', paddingTop: 9, marginTop: 1 }}>
            {footer}
          </div>
        )}
      </div>
      {/* The globe is the fallback, not a sibling: once an Order of Play
          button is live on the card, the corner it floats in belongs to that
          — two links pressed together read as clutter, and the sheet is the
          better answer to "what is happening at this tournament". The wiki
          link keeps the corner only while there is no sheet to offer. */}
      {wikiUrl && !oopTo && (
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
    /* NOT an anchor. The card holds two real links of its own — the order of
       play and, before a sheet exists, the Wikipedia draw — and an <a> inside
       an <a> is invalid HTML that the browser splits unpredictably (React
       warned "validateDOMNesting: <a> cannot appear as a descendant of <a>"
       on every dashboard render). The card navigates like a link — click,
       Enter, Space — and stays a div, so the links inside it are the only
       anchors. Their own stopPropagation keeps a tap on them from also
       opening the draw. */
    const go = () => navigate(to)
    const onKey = (e) => {
      if (e.target !== e.currentTarget) return
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go() }
    }
    return (
      <div role="link" tabIndex={0} style={cardStyle} onClick={go} onKeyDown={onKey}
           onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
        {inner}
      </div>
    )
  }
  return (
    <div style={cardStyle} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
      {inner}
    </div>
  )
}
