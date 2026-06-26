import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { listTournaments } from '../api/tournaments'
import { listAdminUsers } from '../api/auth'
import { getLogs, clearLogs, getAdminPlayers, getRankingsWeeks, getAdminRankings } from '../api/admin'
import { getEntryStatus } from '../api/predictions'
import { useAuth } from '../store/auth'
import { Navigate, useNavigate } from 'react-router-dom'
import { useState, useEffect, useMemo } from 'react'
import './Admin.css'
import './Tournaments.css'

const CURRENT_YEAR = new Date().getFullYear()
const ATP_URL = `https://en.wikipedia.org/wiki/${CURRENT_YEAR}_ATP_Tour`
const WTA_URL = `https://en.wikipedia.org/wiki/${CURRENT_YEAR}_WTA_Tour`
const CATEGORIES = ['rankings', 'espn', 'h2h', 'scheduler', 'notifications', 'discovery', 'scraper']

const TABS = ['Users', 'Tournaments', 'Logs', 'Info', 'Players', 'Rankings']

const CATEGORY_ORDER = { 'Grand Slam': 0, 'ATP 1000': 1, 'WTA 1000': 1, 'ATP 500': 2, 'WTA 500': 2, 'ATP 250': 3, 'WTA 250': 3 }
const GENDER_COLORS = { M: '#edf3ff', F: '#fff0f5' }
const CATEGORY_GROUPS = { '250': ['ATP 250', 'WTA 250'], '500': ['ATP 500', 'WTA 500'], '1000': ['ATP 1000', 'WTA 1000'], 'Grand Slam': ['Grand Slam'] }
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
    return `Local: ${dt.toLocaleString('en-US', { timeZone: venueTimezone, month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })}`
  } catch { return null }
}

function fmtTime(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-CA', {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: false,
    timeZone: 'America/Los_Angeles',
  })
}

function LogDetail({ detail }) {
  const [open, setOpen] = useState(false)
  if (!detail || Object.keys(detail).length === 0) return null
  return (
    <span className="log-detail-wrap">
      <button className="log-detail-toggle" onClick={() => setOpen(o => !o)}>
        {open ? '▾' : '▸'}
      </button>
      {open && (
        <span className="log-detail-popup">
          {Object.entries(detail).map(([k, v]) => (
            <span key={k} className="log-detail-row">
              <span className="log-detail-key">{k}</span>
              <span className="log-detail-val">{String(v)}</span>
            </span>
          ))}
        </span>
      )}
    </span>
  )
}

function UsersPanel({ user }) {
  const { data: adminUsers = [], isLoading } = useQuery({
    queryKey: ['admin-users'],
    queryFn: listAdminUsers,
    enabled: !!user,
  })
  return (
    <div className="card admin-section">
      <h2>
        Users
        <span className="admin-count">{adminUsers.length}</span>
      </h2>
      {isLoading ? (
        <p className="muted" style={{ fontSize: '0.88rem' }}>Loading…</p>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>ID</th>
                <th className="td-left">Name</th>
                <th className="td-left">Username</th>
                <th className="td-left">Email</th>
                <th>Admin</th>
                <th>Joined</th>
              </tr>
            </thead>
            <tbody>
              {adminUsers.map(u => (
                <tr key={u.id}>
                  <td className="td-muted">{u.id}</td>
                  <td className="td-left">{u.display_name}</td>
                  <td className="td-left td-muted">@{u.username}</td>
                  <td className="td-left td-muted">{u.email}</td>
                  <td>{u.is_admin ? '✓' : ''}</td>
                  <td className="td-muted td-nowrap">{u.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function TournamentsPanel({ user }) {
  const navigate = useNavigate()
  const [filterStatus, setFilterStatus] = useState(new Set(['upcoming', 'open', 'active']))
  const [filterGender, setFilterGender] = useState(new Set(['M', 'F']))
  const [filterCategory, setFilterCategory] = useState(new Set(['250', '500', '1000', 'Grand Slam']))
  const [filterYear, setFilterYear] = useState(new Date().getFullYear())
  const [filterMyEvents, setFilterMyEvents] = useState(new Set(['competing', 'not-competing']))

  const { data: tournaments = [], isLoading } = useQuery({
    queryKey: ['tournaments'],
    queryFn: listTournaments,
    refetchInterval: 60_000,
  })

  const { data: entryStatus = {} } = useQuery({
    queryKey: ['entry-status'],
    queryFn: getEntryStatus,
    enabled: !!user,
  })

  const localTzAbbr = Intl.DateTimeFormat('en-US', { timeZoneName: 'short' })
    .formatToParts(new Date()).find(p => p.type === 'timeZoneName')?.value ?? ''

  const preYearFiltered = tournaments.filter(t => {
    if (!filterStatus.has(t.status)) return false
    if (!filterGender.has(t.gender)) return false
    if (!Array.from(filterCategory).some(sel => CATEGORY_GROUPS[sel]?.includes(t.category))) return false
    if (user) {
      const isCompeting = entryStatus[t.id] === 'complete'
      if (isCompeting && !filterMyEvents.has('competing')) return false
      if (!isCompeting && !filterMyEvents.has('not-competing')) return false
    }
    return true
  })
  const availableYears = [...new Set(preYearFiltered.map(t => t.year))].sort((a, b) => b - a)

  useEffect(() => {
    if (availableYears.length > 0 && !availableYears.includes(filterYear)) {
      setFilterYear(availableYears[0])
    }
  }, [availableYears.join(',')])

  const filtered = preYearFiltered.filter(t => t.year === filterYear).sort((a, b) => {
    const sg = STATUS_GROUP_ORDER.indexOf(a.status) - STATUS_GROUP_ORDER.indexOf(b.status)
    if (sg !== 0) return sg
    const dateA = a.start_date ? new Date(a.start_date) : new Date(9999, 0, 0)
    const dateB = b.start_date ? new Date(b.start_date) : new Date(9999, 0, 0)
    if (dateA - dateB !== 0) return dateA - dateB
    const catDiff = (CATEGORY_ORDER[a.category] ?? 9) - (CATEGORY_ORDER[b.category] ?? 9)
    if (catDiff !== 0) return catDiff
    return a.name.localeCompare(b.name) || a.gender.localeCompare(b.gender)
  })

  return (
    <>
      {/* Filters */}
      <div className="card admin-section" style={{ width: 'fit-content', marginBottom: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
          <h2 style={{ margin: 0 }}>Filters</h2>
          <span className="muted" style={{ fontSize: '0.82rem', marginLeft: '1rem' }}>{filtered.length} tournament{filtered.length !== 1 ? 's' : ''}</span>
        </div>
        <div style={{ display: 'flex', gap: '2.5rem', alignItems: 'flex-start' }}>
          <div>
            <h3 className="filter-label">Status</h3>
            {[{ value: 'upcoming', label: 'Upcoming' }, { value: 'open', label: 'Open' }, { value: 'active', label: 'Active' }, { value: 'completed', label: 'Completed' }].map(({ value, label }) => (
              <label key={value} className="filter-row">
                <input type="checkbox" checked={filterStatus.has(value)}
                  onChange={e => { const s = new Set(filterStatus); e.target.checked ? s.add(value) : s.delete(value); setFilterStatus(s) }} />
                {label}
              </label>
            ))}
          </div>
          <div>
            <h3 className="filter-label">Gender</h3>
            {[{ label: "Men's", value: 'M' }, { label: "Women's", value: 'F' }].map(({ label, value }) => (
              <label key={value} className="filter-row">
                <input type="checkbox" checked={filterGender.has(value)}
                  onChange={e => { const s = new Set(filterGender); e.target.checked ? s.add(value) : s.delete(value); setFilterGender(s) }} />
                {label}
              </label>
            ))}
          </div>
          <div>
            <h3 className="filter-label">Category</h3>
            {Object.keys(CATEGORY_GROUPS).map(cat => (
              <label key={cat} className="filter-row">
                <input type="checkbox" checked={filterCategory.has(cat)}
                  onChange={e => { const s = new Set(filterCategory); e.target.checked ? s.add(cat) : s.delete(cat); setFilterCategory(s) }} />
                {cat}
              </label>
            ))}
          </div>
          <div>
            <h3 className="filter-label">Year</h3>
            {availableYears.map(y => (
              <label key={y} className="filter-row">
                <input type="radio" name="admin-filter-year" checked={filterYear === y} onChange={() => setFilterYear(y)} />
                {y}
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
      <div className="card admin-section" style={{ width: 'fit-content' }}>
        {isLoading ? (
          <p className="muted">Loading tournaments…</p>
        ) : (
          <div className="t-table-wrap">
            <table className="t-table">
              <thead>
                <tr>
                  <th rowSpan={2} style={{ width: 20, padding: 0 }}></th>
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
                        <td colSpan={11}>{STATUS_LABELS[status] ?? status}</td>
                      </tr>
                    )
                    if (inGroup.length === 0) {
                      rows.push(
                        <tr key={`empty-${status}`} className="status-group-empty-row">
                          <td colSpan={11}>No {STATUS_LABELS[status].toLowerCase()} tournaments at this time</td>
                        </tr>
                      )
                    } else {
                      inGroup.forEach(t => {
                        const isCompleted = t.status === 'completed'
                        const hasDrawData = !!(isCompleted || t.draw_released_direct_at)
                        const surface = t.surface ? t.surface.replace(/\s*\(.*?\)/g, '') : '—'
                        const isCompeting = t.status !== 'upcoming' && entryStatus[t.id] === 'complete'
                        rows.push(
                          <tr
                            key={t.id}
                            className={hasDrawData ? 'clickable-row' : undefined}
                            style={{ background: GENDER_COLORS[t.gender] || '#fff', cursor: hasDrawData ? 'pointer' : 'default' }}
                            onClick={hasDrawData ? () => navigate(`/tournaments/${t.id}`) : undefined}
                          >
                            <td className="td-star">{isCompeting && <span className="competing-star">★</span>}</td>
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
                            <td className="td-left td-name" style={{ fontWeight: 700 }}>{t.name}</td>
                            <td className="muted">{t.city && t.country ? `${t.city}, ${t.country}` : t.city || t.country || '—'}</td>
                            <td className="muted" title={fmtVenueTime(t.closing_time, t.venue_timezone) ?? undefined}>
                              {t.closing_time
                                ? new Date(t.closing_time + 'Z').toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
                                : '—'}
                            </td>
                            <td>{t.draw_size > 0 ? t.draw_size : '—'}</td>
                            <td>{surface}</td>
                            <td onClick={e => e.stopPropagation()} style={{ padding: '0 0.5rem' }}>
                              {t.wiki_page_id && (
                                <a
                                  href={`https://en.wikipedia.org/wiki/${t.wiki_page_title.replace(/ /g, '_')}`}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  title="View on Wikipedia"
                                  style={{ color: 'var(--text-muted)', lineHeight: 1, display: 'inline-flex' }}
                                >🌐</a>
                              )}
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
    </>
  )
}

function LogsPanel({ user }) {
  const qc = useQueryClient()
  const [levelFilter, setLevelFilter] = useState('')
  const [catFilter, setCatFilter] = useState('')

  const { data: logs = [], isLoading, dataUpdatedAt } = useQuery({
    queryKey: ['admin-logs', levelFilter, catFilter],
    queryFn: () => getLogs({ level: levelFilter || undefined, category: catFilter || undefined }),
    enabled: !!user,
    refetchInterval: 30_000,
  })

  const clearMutation = useMutation({
    mutationFn: () => clearLogs(30),
    onSuccess: () => qc.invalidateQueries(['admin-logs']),
  })
  const clearAllMutation = useMutation({
    mutationFn: () => clearLogs(0),
    onSuccess: () => qc.invalidateQueries(['admin-logs']),
  })

  const errorCount = logs.filter(l => l.level === 'error').length
  const warnCount  = logs.filter(l => l.level === 'warning').length

  return (
    <div className="card admin-section logs-section">
      <div className="logs-header">
        <h2>
          System Logs
          {errorCount > 0 && <span className="admin-count log-count-error">{errorCount} error{errorCount !== 1 ? 's' : ''}</span>}
          {warnCount > 0  && <span className="admin-count log-count-warn">{warnCount} warning{warnCount !== 1 ? 's' : ''}</span>}
          {errorCount === 0 && warnCount === 0 && logs.length > 0 && (
            <span className="admin-count">all clear</span>
          )}
        </h2>
        <div className="logs-controls">
          <div className="log-filters">
            <select className="log-filter-select" value={levelFilter} onChange={e => setLevelFilter(e.target.value)}>
              <option value="">All levels</option>
              <option value="error">Errors</option>
              <option value="warning">Warnings</option>
            </select>
            <select className="log-filter-select" value={catFilter} onChange={e => setCatFilter(e.target.value)}>
              <option value="">All categories</option>
              {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div className="logs-meta">
            {dataUpdatedAt ? (
              <span className="log-refresh-time">
                Updated {new Date(dataUpdatedAt).toLocaleTimeString('en-CA', { hour: '2-digit', minute: '2-digit' })}
              </span>
            ) : null}
            <button
              className="btn-secondary btn-sm"
              onClick={() => clearMutation.mutate()}
              disabled={clearMutation.isPending || clearAllMutation.isPending}
              title="Delete logs older than 30 days"
            >
              {clearMutation.isPending ? 'Clearing…' : 'Clear old'}
            </button>
            <button
              className="btn-secondary btn-sm btn-danger-sm"
              onClick={() => window.confirm('Delete all log entries?') && clearAllMutation.mutate()}
              disabled={clearMutation.isPending || clearAllMutation.isPending}
              title="Delete all log entries"
            >
              {clearAllMutation.isPending ? 'Clearing…' : 'Clear all'}
            </button>
          </div>
        </div>
      </div>
      {isLoading ? (
        <p className="muted" style={{ fontSize: '0.88rem' }}>Loading…</p>
      ) : logs.length === 0 ? (
        <p className="logs-empty">No log entries{levelFilter || catFilter ? ' for this filter' : ''}.</p>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table logs-table">
            <thead>
              <tr>
                <th className="td-left log-col-time">Time</th>
                <th className="log-col-level">Level</th>
                <th className="log-col-cat">Category</th>
                <th className="td-left">Message</th>
              </tr>
            </thead>
            <tbody>
              {logs.map(log => (
                <tr key={log.id} className={`log-row log-row-${log.level}`}>
                  <td className="td-left td-muted td-nowrap log-col-time">{fmtTime(log.created_at)}</td>
                  <td className="log-col-level">
                    <span className={`log-badge log-badge-${log.level}`}>{log.level}</span>
                  </td>
                  <td className="log-col-cat">
                    <span className="log-cat">{log.category}</span>
                  </td>
                  <td className="td-left log-message">
                    {log.message}
                    <LogDetail detail={log.detail} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function InfoPanel() {
  return (
    <details className="card admin-section scraping-explainer" open>
      <summary>How Data Scraping Works</summary>

      <div className="scraping-step">
        <div className="scraping-step-header">
          <span className="scraping-step-num">1</span>
          <strong>Tournament Discovery</strong>
          <span className="scraping-schedule">Daily · midnight UTC</span>
        </div>
        <p>
          The server fetches the current season schedule from Wikipedia and builds the tournament list.
          These are the source pages for {CURRENT_YEAR}:
        </p>
        <div className="scraping-links">
          <a href={ATP_URL} target="_blank" rel="noopener noreferrer">{CURRENT_YEAR} ATP Tour ↗</a>
          <a href={WTA_URL} target="_blank" rel="noopener noreferrer">{CURRENT_YEAR} WTA Tour ↗</a>
        </div>
        <p>
          Each row in the schedule table that contains a Singles link is parsed for the
          tournament name, category (Grand Slam / 500 / 250 etc.), surface, draw size,
          city, and scheduled dates. Tournaments already in the database are updated in
          place; new ones are added automatically.
        </p>
      </div>

      <div className="scraping-step">
        <div className="scraping-step-header">
          <span className="scraping-step-num">2</span>
          <strong>Individual Draw Scraping</strong>
          <span className="scraping-schedule">Daily · noon UTC + on startup</span>
        </div>
        <p>
          For every active or upcoming tournament, the server fetches its dedicated
          singles Wikipedia page (e.g. <em>2026 French Open – Men's singles</em>) and
          parses the bracket template. This extracts:
        </p>
        <ul className="scraping-list">
          <li>Players, seeds, nationalities, and entry types (WC / Q / LL)</li>
          <li>Match pairings for every round</li>
          <li>Match scores and winners as results come in</li>
          <li>Exact tournament start/end dates from the infobox</li>
        </ul>
        <p>
          A tournament's Wikipedia page title is discovered from the season page (step 1)
          and confirmed on first successful fetch — that's when the globe icon appears on
          the Tournaments page. If the page doesn't exist yet (future tournament), the
          system keeps a placeholder and retries daily until Wikipedia creates it.
        </p>
      </div>

      <div className="scraping-step">
        <div className="scraping-step-header">
          <span className="scraping-step-num">3</span>
          <strong>Real-Time Updates via Wikimedia EventStreams</strong>
          <span className="scraping-schedule">Continuous</span>
        </div>
        <p>
          The server maintains a live connection to Wikimedia's EventStreams API — a
          server-sent event feed that broadcasts every Wikipedia page edit in real time.
          For each upcoming and active tournament, the backend subscribes to its singles
          page. The moment any editor updates a match result or adds a player to the
          draw, the server re-scrapes that page automatically — no waiting for the next
          scheduled job. Subscriptions are managed dynamically: tournaments are added
          when they move to "upcoming" status and removed when they complete.
        </p>
      </div>

      <div className="scraping-step">
        <div className="scraping-step-header">
          <span className="scraping-step-num">4</span>
          <strong>Manual Refresh</strong>
          <span className="scraping-schedule">On demand</span>
        </div>
        <p>
          The <strong>Update Draw Data</strong> action in the Tournaments tab re-runs step 2
          immediately for all non-completed tournaments, bypassing the cache. Use it if a
          draw was just released and you don't want to wait for the next scheduled run.
          Completed tournaments are always skipped — their data is never overwritten.
        </p>
      </div>
    </details>
  )
}

function PlayersPanel({ user }) {
  const [genderFilter, setGenderFilter] = useState('')
  const [search, setSearch] = useState('')
  const [searchInput, setSearchInput] = useState('')

  const { data: players = [], isLoading } = useQuery({
    queryKey: ['admin-players', genderFilter, search],
    queryFn: () => getAdminPlayers({
      gender: genderFilter || undefined,
      search: search || undefined,
    }),
    enabled: !!user,
  })

  function handleSearch(e) {
    e.preventDefault()
    setSearch(searchInput)
  }

  return (
    <div className="card admin-section">
      <h2>
        Players (TE)
        <span className="admin-count">{players.length}{search || genderFilter ? '' : '+'}</span>
      </h2>
      <div className="admin-filters-bar">
        <div className="log-filters">
          <select className="log-filter-select" value={genderFilter} onChange={e => setGenderFilter(e.target.value)}>
            <option value="">All genders</option>
            <option value="M">Men (ATP)</option>
            <option value="F">Women (WTA)</option>
          </select>
        </div>
        <form className="admin-search-form" onSubmit={handleSearch}>
          <input
            className="admin-search-input"
            type="text"
            placeholder="Search name…"
            value={searchInput}
            onChange={e => setSearchInput(e.target.value)}
          />
          <button className="btn-secondary btn-sm" type="submit">Search</button>
          {search && (
            <button
              className="btn-secondary btn-sm"
              type="button"
              onClick={() => { setSearch(''); setSearchInput('') }}
            >
              Clear
            </button>
          )}
        </form>
      </div>

      {isLoading ? (
        <p className="muted" style={{ fontSize: '0.88rem' }}>Loading…</p>
      ) : players.length === 0 ? (
        <p className="logs-empty">No players found.</p>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th className="td-left">First</th>
                <th className="td-left">Last</th>
                <th>DOB</th>
                <th>Age</th>
              </tr>
            </thead>
            <tbody>
              {players.map(p => {
                const dob = p.date_of_birth ? new Date(p.date_of_birth) : null
                const age = dob ? Math.floor((Date.now() - dob.getTime()) / (1000 * 60 * 60 * 24 * 365.25)) : null
                return (
                  <tr key={p.id}>
                    <td className="td-left">{p.first_name || '—'}</td>
                    <td className="td-left">{p.last_name || '—'}</td>
                    <td className="td-muted td-nowrap">{p.date_of_birth || '—'}</td>
                    <td className="td-muted">{age ?? '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function RankingsPanel({ user }) {
  const [genderFilter, setGenderFilter] = useState('M')
  const [sortCol, setSortCol] = useState('rank')
  const [sortDir, setSortDir] = useState('asc')

  const { data: weeks = [] } = useQuery({
    queryKey: ['admin-rankings-weeks'],
    queryFn: getRankingsWeeks,
    enabled: !!user,
  })

  const [selectedWeek, setSelectedWeek] = useState('')
  const activeWeek = selectedWeek || weeks[0] || ''

  const { data: rankings = [], isLoading } = useQuery({
    queryKey: ['admin-rankings', activeWeek, genderFilter],
    queryFn: () => getAdminRankings({ week_date: activeWeek, gender: genderFilter || undefined }),
    enabled: !!user && !!activeWeek,
  })

  const handleSort = col => {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(col); setSortDir('asc') }
  }

  const sortIcon = col => (
    <span className={`sort-icon${sortCol === col ? ' sort-active' : ''}`}>
      {sortCol === col ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ' ⇅'}
    </span>
  )

  const sortedRankings = useMemo(() => {
    if (!rankings.length) return rankings
    const getAge = dob => dob ? (Date.now() - new Date(dob).getTime()) / (1000 * 60 * 60 * 24 * 365.25) : null
    return [...rankings].sort((a, b) => {
      let av, bv
      if (sortCol === 'rank')     { av = a.rank ?? Infinity;           bv = b.rank ?? Infinity }
      else if (sortCol === 'elo') { av = a.elo_rank ?? Infinity;       bv = b.elo_rank ?? Infinity }
      else if (sortCol === 'pts') { av = a.points ?? -Infinity;        bv = b.points ?? -Infinity }
      else if (sortCol === 'name'){ av = a.name_display || a.name_raw;  bv = b.name_display || b.name_raw }
      else if (sortCol === 'dob') { av = a.date_of_birth ?? 'zzzz';   bv = b.date_of_birth ?? 'zzzz' }
      else if (sortCol === 'age') { av = getAge(a.date_of_birth) ?? -1; bv = getAge(b.date_of_birth) ?? -1 }
      if (av < bv) return sortDir === 'asc' ? -1 : 1
      if (av > bv) return sortDir === 'asc' ? 1 : -1
      return 0
    })
  }, [rankings, sortCol, sortDir])

  return (
    <div className="card admin-section">
      <h2>Rankings</h2>
      <div className="admin-filters-bar">
        <div className="log-filters">
          <select className="log-filter-select" value={genderFilter} onChange={e => setGenderFilter(e.target.value)}>
            <option value="M">Men (ATP)</option>
            <option value="F">Women (WTA)</option>
            <option value="">Both</option>
          </select>
          <select
            className="log-filter-select"
            value={activeWeek}
            onChange={e => setSelectedWeek(e.target.value)}
          >
            {weeks.map(w => <option key={w} value={w}>{w}</option>)}
          </select>
        </div>
        {activeWeek && (
          <span className="log-refresh-time">{rankings.length} entries</span>
        )}
      </div>

      {isLoading ? (
        <p className="muted" style={{ fontSize: '0.88rem' }}>Loading…</p>
      ) : !activeWeek ? (
        <p className="logs-empty">No ranking weeks available.</p>
      ) : rankings.length === 0 ? (
        <p className="logs-empty">No rankings for this week/gender.</p>
      ) : (
        <div className="admin-table-wrap rankings-table-wrap">
          <table className="admin-table rankings-table">
            <thead>
              <tr>
                <th className="sortable" onClick={() => handleSort('rank')}>Rank (ATP){sortIcon('rank')}</th>
                <th className="sortable" onClick={() => handleSort('elo')}>Rank (ELO){sortIcon('elo')}</th>
                <th className="sortable" onClick={() => handleSort('pts')}>Points{sortIcon('pts')}</th>
                <th className="sortable th-left" onClick={() => handleSort('name')}>Name{sortIcon('name')}</th>
                <th className="sortable" onClick={() => handleSort('dob')}>DOB{sortIcon('dob')}</th>
                <th className="sortable" onClick={() => handleSort('age')}>Age{sortIcon('age')}</th>
              </tr>
            </thead>
            <tbody>
              {sortedRankings.map(r => {
                const dob = r.date_of_birth ? new Date(r.date_of_birth) : null
                const age = dob ? Math.floor((Date.now() - dob.getTime()) / (1000 * 60 * 60 * 24 * 365.25)) : null
                return (
                  <tr key={`${r.player_id}-${r.rank}`}>
                    <td><strong>{r.rank}</strong></td>
                    <td className="td-muted">{r.elo_rank ?? '—'}</td>
                    <td className="td-muted">{r.points != null ? r.points.toLocaleString() : '—'}</td>
                    <td className="td-left">{r.name_display || r.name_raw}</td>
                    <td className="td-muted td-nowrap">{r.date_of_birth || '—'}</td>
                    <td className="td-muted">{age ?? '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default function Admin() {
  const { user } = useAuth()
  const [activeTab, setActiveTab] = useState('Users')

  if (!user) return <Navigate to="/login" replace />

  return (
    <div className="admin-page">
      <h1>Admin</h1>

      <div className="admin-subnav">
        {TABS.map(tab => (
          <button
            key={tab}
            className={`admin-subnav-btn${activeTab === tab ? ' active' : ''}`}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>

      <div className="admin-tab-content">
        {activeTab === 'Users'       && <UsersPanel user={user} />}
        {activeTab === 'Tournaments' && <TournamentsPanel user={user} />}
        {activeTab === 'Logs'        && <LogsPanel user={user} />}
        {activeTab === 'Info'        && <InfoPanel />}
        {activeTab === 'Players'     && <PlayersPanel user={user} />}
        {activeTab === 'Rankings'    && <RankingsPanel user={user} />}
      </div>
    </div>
  )
}
