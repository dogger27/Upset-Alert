import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { listTournaments } from '../api/tournaments'
import './Tournaments.css'

const CATEGORY_ORDER = { 'Grand Slam': 0, 'ATP 1000': 1, 'WTA 1000': 1, 'ATP 500': 2, 'WTA 500': 2, 'ATP 250': 3, 'WTA 250': 3 }

const GENDER_COLORS = { M: '#edf3ff', F: '#fff0f5' }

const CATEGORY_GROUPS = {
  '250': ['ATP 250', 'WTA 250'],
  '500': ['ATP 500', 'WTA 500'],
  '1000': ['ATP 1000', 'WTA 1000'],
  'Grand Slam': ['Grand Slam'],
}

const STATUS_GROUP_ORDER = ['completed', 'open', 'active', 'upcoming']
const STATUS_LABELS = { active: 'Active', open: 'Open', upcoming: 'Upcoming', completed: 'Completed' }

function fmtDate(dateStr) {
  if (!dateStr) return '—'
  const [y, m, d] = dateStr.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString('en-US', { month: 'short', day: '2-digit' })
}

function fmtVenueTime(closingTimeUtc, venueTimezone) {
  if (!closingTimeUtc || !venueTimezone) return null
  try {
    const dt = new Date(closingTimeUtc + 'Z')
    const local = dt.toLocaleString('en-US', {
      timeZone: venueTimezone,
      month: 'short', day: 'numeric',
      hour: 'numeric', minute: '2-digit',
      timeZoneName: 'short',
    })
    return `Local: ${local}`
  } catch {
    return null
  }
}

export default function Tournaments() {
  const navigate = useNavigate()
  const [filterStatus, setFilterStatus] = useState(new Set(['upcoming', 'open', 'active']))
  const [filterGender, setFilterGender] = useState(new Set(['M', 'F']))
  const [filterCategory, setFilterCategory] = useState(new Set(['250', '500', '1000', 'Grand Slam']))
  const [filterYear, setFilterYear] = useState(new Date().getFullYear())

  const { data: tournaments = [], isLoading } = useQuery({
    queryKey: ['tournaments'],
    queryFn: listTournaments,
    refetchInterval: 60 * 1000,
  })

  const localTzAbbr = Intl.DateTimeFormat('en-US', { timeZoneName: 'short' })
    .formatToParts(new Date())
    .find(p => p.type === 'timeZoneName')?.value ?? ''

  const availableYears = [...new Set(tournaments.map(t => t.year))].sort((a, b) => b - a)

  const filtered = tournaments.filter(t => {
    if (filterYear !== 'all' && t.year !== filterYear) return false
    if (!filterStatus.has(t.status)) return false
    if (!filterGender.has(t.gender)) return false
    return Array.from(filterCategory).some(sel => CATEGORY_GROUPS[sel]?.includes(t.category))
  }).sort((a, b) => {
    const sg = STATUS_GROUP_ORDER.indexOf(a.status) - STATUS_GROUP_ORDER.indexOf(b.status)
    if (sg !== 0) return sg
    const dateA = a.start_date ? new Date(a.start_date) : new Date(9999, 0, 0)
    const dateB = b.start_date ? new Date(b.start_date) : new Date(9999, 0, 0)
    if (dateA - dateB !== 0) return dateA - dateB
    const catDiff = (CATEGORY_ORDER[a.category] ?? 9) - (CATEGORY_ORDER[b.category] ?? 9)
    if (catDiff !== 0) return catDiff
    const nameDiff = a.name.localeCompare(b.name)
    if (nameDiff !== 0) return nameDiff
    return a.gender.localeCompare(b.gender)
  })

  return (
    <div className="tournaments-page">
      <div className="tournaments-title-row">
        <h1>Tournaments</h1>
        <select
          className="year-select"
          value={filterYear}
          onChange={e => setFilterYear(e.target.value === 'all' ? 'all' : Number(e.target.value))}
        >
          <option value="all">All years</option>
          {availableYears.map(y => (
            <option key={y} value={y}>{y}</option>
          ))}
        </select>
      </div>

      {/* Filters */}
      <div className="card tournaments-section" style={{ width: 'fit-content', margin: '0 auto 1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
          <h2 style={{ margin: 0 }}>Filters</h2>
          <span className="muted" style={{ fontSize: '0.82rem' }}>{filtered.length} tournament{filtered.length !== 1 ? 's' : ''}</span>
        </div>
        <div style={{ display: 'flex', gap: '2.5rem', alignItems: 'flex-start' }}>

          <div>
            <h3 className="filter-label">Status</h3>
            {[{ value: 'upcoming', label: 'Upcoming' }, { value: 'open', label: 'Open' }, { value: 'active', label: 'Active' }, { value: 'completed', label: 'Completed' }].map(({ value, label }) => (
              <label key={value} className="filter-row">
                <input type="checkbox" checked={filterStatus.has(value)}
                  onChange={e => {
                    const s = new Set(filterStatus)
                    e.target.checked ? s.add(value) : s.delete(value)
                    setFilterStatus(s)
                  }} />
                {label}
              </label>
            ))}
          </div>

          <div>
            <h3 className="filter-label">Gender</h3>
            {[{ label: "Men's", value: 'M' }, { label: "Women's", value: 'F' }].map(({ label, value }) => (
              <label key={value} className="filter-row">
                <input type="checkbox" checked={filterGender.has(value)}
                  onChange={e => {
                    const s = new Set(filterGender)
                    e.target.checked ? s.add(value) : s.delete(value)
                    setFilterGender(s)
                  }} />
                {label}
              </label>
            ))}
          </div>

          <div>
            <h3 className="filter-label">Category</h3>
            {Object.keys(CATEGORY_GROUPS).map(cat => (
              <label key={cat} className="filter-row">
                <input type="checkbox" checked={filterCategory.has(cat)}
                  onChange={e => {
                    const s = new Set(filterCategory)
                    e.target.checked ? s.add(cat) : s.delete(cat)
                    setFilterCategory(s)
                  }} />
                {cat}
              </label>
            ))}
          </div>

          <div style={{ marginLeft: 'auto', paddingLeft: '2rem', borderLeft: '1px solid var(--border)', alignSelf: 'stretch', display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: '0.5rem' }}>
            <h3 className="filter-label">Legend</h3>
            {[{ label: "Men's", color: GENDER_COLORS.M, border: '#93b8ff' }, { label: "Women's", color: GENDER_COLORS.F, border: '#ffb3c6' }].map(({ label, color, border }) => (
              <div key={label} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.88rem' }}>
                <span style={{ display: 'inline-block', width: 14, height: 14, borderRadius: 3, background: color, border: `1.5px solid ${border}`, flexShrink: 0 }} />
                {label}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="card tournaments-section" style={{ width: 'fit-content', margin: '0 auto' }}>
        {isLoading && <p className="muted">Loading tournaments…</p>}

        {!isLoading && (
          <div className="t-table-wrap">
            <table className="t-table">
              <thead>
                <tr>
                  <th rowSpan={2}>Start Date</th>
                  <th rowSpan={2}>Category</th>
                  <th colSpan={2} style={{ borderBottom: '1px solid var(--border)' }}>Expected Draw Dates</th>
                  <th rowSpan={2}>Name</th>
                  <th rowSpan={2}>City</th>
                  <th rowSpan={2}>Closes{localTzAbbr ? ` (${localTzAbbr})` : ''}</th>
                  <th rowSpan={2}>Draw</th>
                  <th rowSpan={2}>Surface</th>
                  <th rowSpan={2}></th>
                </tr>
                <tr>
                  <th title="Date Direct Acceptance Players Added to Draw">DA</th>
                  <th title="Date Qualifiers Added to Draw">Qual.</th>
                </tr>
              </thead>
              <tbody>
                {(() => {
                  const rows = []
                  STATUS_GROUP_ORDER.filter(s => filterStatus.has(s)).forEach(status => {
                    const inGroup = filtered.filter(t => t.status === status)
                    rows.push(
                      <tr key={`group-${status}`} className="status-group-header">
                        <td colSpan={10}>{STATUS_LABELS[status] ?? status}</td>
                      </tr>
                    )
                    if (inGroup.length === 0) {
                      rows.push(
                        <tr key={`empty-${status}`} className="status-group-empty-row">
                          <td colSpan={10}>No {STATUS_LABELS[status].toLowerCase()} tournaments at this time</td>
                        </tr>
                      )
                    } else {
                      inGroup.forEach(t => {
                        const isCompleted = t.status === 'completed'
                        const hasDrawData = !!(isCompleted || t.draw_released_direct_at)
                        const surface = t.surface ? t.surface.replace(/\s*\(.*?\)/g, '') : '—'
                        rows.push(
                          <tr
                            key={t.id}
                            className={hasDrawData ? 'clickable-row' : undefined}
                            style={{ background: GENDER_COLORS[t.gender] || '#fff', cursor: hasDrawData ? 'pointer' : 'default' }}
                            onClick={hasDrawData ? () => navigate(`/tournaments/${t.id}`) : undefined}
                          >
                            <td className="muted td-left">{fmtDate(t.start_date)}</td>
                            <td>{t.category ? t.category.replace(/^(ATP|WTA)\s+/, '') : '—'}</td>
                            <td className="td-left">
                              {t.draw_release_direct
                                ? <><span className="muted">{fmtDate(t.draw_release_direct)}</span>{(isCompleted || t.draw_released_direct_at) && <span style={{ marginLeft: '0.4rem', color: '#4CAF50' }}>✓</span>}</>
                                : isCompleted ? <span style={{ color: '#4CAF50' }}>✓</span> : '—'}
                            </td>
                            <td className="td-left">
                              {t.draw_release_qualifiers
                                ? <><span className="muted">{fmtDate(t.draw_release_qualifiers)}</span>{(isCompleted || t.draw_released_qualifiers_at) && <span style={{ marginLeft: '0.4rem', color: '#4CAF50' }}>✓</span>}</>
                                : isCompleted ? <span style={{ color: '#4CAF50' }}>✓</span> : '—'}
                            </td>
                            <td className="td-left" style={{ fontWeight: 700 }}>{t.name}</td>
                            <td className="muted">{t.city && t.country ? `${t.city}, ${t.country}` : t.city || t.country || '—'}</td>
                            <td className="muted" title={fmtVenueTime(t.closing_time, t.venue_timezone) ?? undefined}>
                              {t.closing_time
                                ? new Date(t.closing_time + 'Z').toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
                                : '—'}
                            </td>
                            <td>{t.draw_size > 0 ? t.draw_size : '—'}</td>
                            <td>{surface}</td>
                            <td onClick={e => e.stopPropagation()} style={{ padding: '0 0.5rem' }}>
                              <a
                                href={`https://en.wikipedia.org/wiki/${t.wiki_page_title.replace(/ /g, '_')}`}
                                target="_blank"
                                rel="noopener noreferrer"
                                title="View on Wikipedia"
                                style={{ color: 'var(--text-muted)', lineHeight: 1, display: 'inline-flex' }}
                              >🌐</a>
                            </td>
                          </tr>
                        )
                      })
                    }
                  })
                  return rows
                })()}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
