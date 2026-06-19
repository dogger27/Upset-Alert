export function SectionHeader({ title, description, accent = 'neutral', live = false, count, style = {} }) {
  const accents = {
    neutral: 'var(--ink-500)',
    open: 'var(--clay-500)',
    active: 'var(--green-600)',
    muted: 'var(--ink-400)',
  }
  const color = accents[accent] || accents.neutral
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap', ...style }}>
      <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
        {live && (
          <span style={{ position: 'relative', display: 'inline-flex', width: 9, height: 9 }}>
            <span style={{
              position: 'absolute', inset: 0, borderRadius: '50%', background: color,
              animation: 'ua-ping 1.6s var(--ease-out) infinite',
            }} />
            <span style={{ position: 'relative', width: 9, height: 9, borderRadius: '50%', background: color }} />
          </span>
        )}
        <h2 style={{
          fontFamily: 'var(--font-display)', fontWeight: 'var(--fw-black)',
          fontSize: '1.35rem', letterSpacing: '0.06em', textTransform: 'uppercase',
          color: accent === 'neutral' ? 'var(--ink-700)' : color, margin: 0,
        }}>{title}</h2>
        {count != null && (
          <span style={{
            fontFamily: 'var(--font-mono)', fontSize: '0.7rem', fontWeight: 600,
            color: '#fff', background: color, borderRadius: 'var(--radius-pill)',
            padding: '2px 8px', lineHeight: 1.4,
          }}>{count}</span>
        )}
      </div>
      {description && (
        <p style={{ fontFamily: 'var(--font-body)', fontSize: '0.8rem', color: 'var(--text-muted)', margin: 0 }}>
          {description}
        </p>
      )}
    </div>
  )
}
