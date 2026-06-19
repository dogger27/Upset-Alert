const SURFACES = {
  grass: { label: 'Grass', dot: 'var(--surface-grass)', bg: 'var(--surface-grass-bg)', fg: '#1b6b2c' },
  clay:  { label: 'Clay',  dot: 'var(--surface-clay)',  bg: 'var(--surface-clay-bg)',  fg: '#9a521f' },
  hard:  { label: 'Hard',  dot: 'var(--surface-hard)',  bg: 'var(--surface-hard-bg)',  fg: 'var(--atp-700)' },
}

export function SurfacePill({ surface = 'grass', style = {} }) {
  const key = String(surface).toLowerCase().replace(/\s*\(.*?\)/g, '').trim()
  const s = SURFACES[key] || SURFACES.grass
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      fontFamily: 'var(--font-body)', fontWeight: 'var(--fw-semibold)',
      fontSize: '0.72rem', letterSpacing: '0.02em',
      padding: '3px 9px 3px 8px', borderRadius: 'var(--radius-pill)',
      background: s.bg, color: s.fg, ...style,
    }}>
      <span style={{ width: 7, height: 7, borderRadius: '50%', background: s.dot, flexShrink: 0 }} />
      {s.label}
    </span>
  )
}
