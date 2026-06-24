import { useState } from 'react'
import { Link } from 'react-router-dom'
import { TierBadge } from './TierBadge.jsx'
import { SurfacePill } from './SurfacePill.jsx'

function renderFooter({ section, pickState, drawDates }) {
  const pillBase = {
    display: 'inline-flex', alignItems: 'center', gap: 5,
    fontFamily: 'var(--font-body)', fontWeight: 'var(--fw-bold)', fontSize: '0.72rem',
    padding: '4px 10px', borderRadius: 'var(--radius-pill)', whiteSpace: 'nowrap',
  }
  const row = (left, right) => (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
      <span>{left}</span>{right}
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
    return row(
      <span style={map[state]}>{label[state]}</span>,
      <span style={{
        fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: '0.8rem',
        letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--green-600)',
      }}>Make picks →</span>
    )
  }

  if (section === 'active') {
    const competing = pickState === 'complete'
    return row(
      <span style={{ ...pillBase, background: 'var(--ink-100)', color: 'var(--ink-600)' }}>🔒 Selection closed</span>,
      competing
        ? <span style={{ ...pillBase, background: 'var(--green-600)', color: '#fff', boxShadow: 'var(--glow-green)', letterSpacing: '0.03em' }}>★ Competing</span>
        : null
    )
  }

  if (section === 'upcoming' && drawDates) {
    const item = (k, v) => (
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'var(--text-muted)' }}>
        <span style={{ fontWeight: 700, color: 'var(--ink-600)' }}>{k}:</span> {v}
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
    return row(
      <span style={{ ...pillBase, background: 'var(--ink-100)', color: 'var(--ink-500)' }}>Completed</span>,
      competed
        ? <span style={{ ...pillBase, background: 'var(--green-100)', color: 'var(--green-700)' }}>★ Competed</span>
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

export function TournamentCard({ tour = 'ATP', name, city, surface = 'grass', tier = '500', dateRange, section = 'open', pickState = null, drawDates = null, to, wikiUrl, onGuestClick }) {
  const [hover, setHover] = useState(false)
  const isATP = String(tour).toUpperCase() === 'ATP'
  const accent = isATP ? 'var(--atp-500)' : 'var(--wta-500)'
  const accentDeep = isATP ? 'var(--atp-700)' : 'var(--wta-700)'
  const tint = isATP ? 'var(--atp-50)' : 'var(--wta-50)'
  const glow = isATP ? 'var(--glow-atp)' : 'var(--glow-wta)'
  const interactive = section !== 'upcoming'

  const footer = renderFooter({ section, pickState, drawDates })

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
            fontSize: '1.18rem', letterSpacing: '0.01em', lineHeight: 1.05, color: 'var(--ink-900)',
          }}>{name}</span>
          <TierBadge tour={tour} tier={tier} name={name} size="sm" style={{ flexShrink: 0 }} />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          {city && <span style={{ fontFamily: 'var(--font-body)', fontSize: '0.8rem', fontWeight: 600, color: 'var(--ink-600)' }}>{city}</span>}
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
