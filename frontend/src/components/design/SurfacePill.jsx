const SURFACES = {
  grass: { label: 'Grass', dot: 'var(--surface-grass)', bg: 'var(--surface-grass-bg)', fg: 'var(--surface-grass-fg)' },
  clay:  { label: 'Clay',  dot: 'var(--surface-clay)',  bg: 'var(--surface-clay-bg)',  fg: 'var(--surface-clay-fg)' },
  hard:  { label: 'Hard',  dot: 'var(--surface-hard)',  bg: 'var(--surface-hard-bg)',  fg: 'var(--surface-hard-fg)' },
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
