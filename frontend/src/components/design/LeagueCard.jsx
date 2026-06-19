import { useState } from 'react'
import { Link } from 'react-router-dom'

export function LeagueCard({ name, sublabel, global: isGlobal = false, icon = null, to, style = {} }) {
  const [hover, setHover] = useState(false)
  const inner = (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {icon && <span style={{ fontSize: '0.95rem', lineHeight: 1 }}>{icon}</span>}
        <span style={{
          fontFamily: 'var(--font-display)', fontWeight: 'var(--fw-bold)', fontSize: '1rem',
          letterSpacing: '0.01em', color: 'var(--ink-900)',
        }}>{name}</span>
      </div>
      {sublabel && <div style={{
        fontFamily: 'var(--font-body)', fontSize: '0.74rem', color: 'var(--text-muted)',
        marginTop: 3, marginLeft: icon ? 24 : 0,
      }}>{sublabel}</div>}
    </>
  )

  const cardStyle = {
    display: 'block', textDecoration: 'none', color: 'inherit',
    background: isGlobal ? 'var(--atp-50)' : 'var(--surface-card)',
    border: `1px solid ${isGlobal ? 'var(--atp-100)' : (hover ? 'var(--green-500)' : 'var(--border)')}`,
    borderRadius: 'var(--radius)',
    padding: '11px 14px',
    boxShadow: hover ? 'var(--shadow-md)' : 'none',
    transform: hover ? 'translateY(-1px)' : 'none',
    transition: 'all var(--dur) var(--ease-out)',
    cursor: 'pointer',
    ...style,
  }

  if (to) {
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
