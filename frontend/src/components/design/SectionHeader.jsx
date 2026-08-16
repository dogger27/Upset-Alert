export function SectionHeader({ title, description, accent = 'neutral', live = false, count, style = {} }) {
  // Two values per accent, because this one colour is asked to do two jobs: it
  // is the heading's ink AND the fill behind the white count. On a dark theme
  // those want opposite ends of the ramp — one token would either grey out the
  // heading or put white type on a pale green pill.
  const accents = {
    neutral: { ink: 'var(--text-muted)', fill: 'var(--ink-500)' },
    open:    { ink: 'var(--clay-500)',   fill: 'var(--clay-500)' },
    active:  { ink: 'var(--brand-text)', fill: 'var(--brand-fill)' },
    muted:   { ink: 'var(--ink-400)',    fill: 'var(--ink-400)' },
  }
  const { ink, fill } = accents[accent] || accents.neutral
  const color = fill
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, ...style }}>
      <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, flex: '0 0 auto' }}>
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
          color: accent === 'neutral' ? 'var(--text-body)' : ink, margin: 0,
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
        <p style={{ fontFamily: 'var(--font-body)', fontSize: '0.8rem', color: 'var(--text-muted)', margin: 0, flex: '1 1 auto', minWidth: 0 }}>
          {description}
        </p>
      )}
    </div>
  )
}
