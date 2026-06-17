import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listTournaments } from '../api/tournaments'
import { listLeagues, createLeague, joinLeague } from '../api/leagues'
import { getEntryStatus } from '../api/predictions'
import { useAuth } from '../store/auth'
import './Home.css'

function fmtDate(s) {
  if (!s) return null
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}


function fmtDateRange(start, end) {
  if (!start) return ''
  const s = new Date(start + 'T00:00:00')
  const mo = (d) => d.toLocaleDateString('en-US', { month: 'short' })
  if (!end) return `${mo(s)} ${s.getDate()}`
  const e = new Date(end + 'T00:00:00')
  const sameMonth = s.getMonth() === e.getMonth() && s.getFullYear() === e.getFullYear()
  return sameMonth
    ? `${mo(s)} ${s.getDate()} - ${e.getDate()}`
    : `${mo(s)} ${s.getDate()} - ${mo(e)} ${e.getDate()}`
}

function fmtModified(iso) {
  if (!iso) return null
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z')
  const date = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  const time = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })
    .replace(' AM', 'am').replace(' PM', 'pm')
  return `${date}, ${time}`
}

function DrawDates({ t, section }) {
  const daConfirmed = !!t.draw_released_direct_at
  const qualConfirmed = !!t.draw_released_qualifiers_at

  if (section === 'active') {
    return <div className="home-card-draw">🔒 Selection closed</div>
  }

  if (section === 'open') {
    return (
      <div className="home-card-draw">
        <span className="draw-confirmed">✓ DA</span>
        {qualConfirmed
          ? <span className="draw-confirmed">✓ Qual</span>
          : t.draw_release_qualifiers
            ? <span className="draw-pending">Qual: {fmtDate(t.draw_release_qualifiers)}</span>
            : null}
      </div>
    )
  }

  if (section === 'upcoming') {
    return (
      <div className="home-card-draw">
        {t.draw_release_direct && <span className="draw-pending">DA: {fmtDate(t.draw_release_direct)}</span>}
        {t.draw_release_qualifiers && <span className="draw-pending">Qual: {fmtDate(t.draw_release_qualifiers)}</span>}
      </div>
    )
  }

  return null
}

function TournamentCard({ t, section, pickStatus: ps }) {
  const pickState = ps?.[t.id] ?? null  // 'complete' | 'partial' | null
  const catShort = t.category ?? ''
  const surface = t.surface ? t.surface.replace(/\s*\(.*?\)/g, '') : ''
  const city = t.city ? t.city : ''
  const hasDrawData = t.status === 'completed' || !!t.draw_released_direct_at

  const cardClass = `home-card home-card-${t.gender === 'M' ? 'men' : 'women'}${!hasDrawData ? ' home-card-upcoming' : ''}`
  const inner = (
    <>
      <div className="home-card-title-row">
        <span className="home-card-title">{t.name}</span>
        <span className="home-card-title-right">
          {t.start_date && <span className="home-card-dates">{fmtDateRange(t.start_date, t.end_date)}</span>}
          {catShort && <span className="home-card-level">{catShort}</span>}
        </span>
      </div>
      <div className="home-card-sub-row">
        <span className="home-card-sub">{city}</span>
        <span className="home-card-sub-center">
          {section === 'active' && pickState === 'complete'
            ? <span className="home-card-entered competing">★ Competing</span>
            : section === 'lastweek' && pickState === 'complete'
              ? <span className="home-card-entered competing">★ Competed</span>
              : (section === 'open' || section === 'upcoming')
                ? <DrawDates t={t} section={section} />
                : null
          }
        </span>
        <span className="home-card-surface">{surface}</span>
      </div>
      {section === 'open' && (
        <div className="home-card-bottom-row">
          <span />
          {pickState === 'complete'
            ? <span className="home-card-entered complete">✓ Picks entered</span>
            : pickState === 'partial'
              ? <span className="home-card-entered partial">⚠ Picks incomplete</span>
              : <span className="home-card-entered none">✕ Picks not started</span>
          }
        </div>
      )}
    </>
  )

  if (!hasDrawData) {
    return <div className={cardClass}>{inner}</div>
  }
  return <Link to={`/tournaments/${t.id}`} className={cardClass}>{inner}</Link>
}

function GenderCol({ label, tournaments, section, pickStatus }) {
  return (
    <div className="home-gender-col">
      <div className="home-gender-header">{label}</div>
      {tournaments.length > 0 ? tournaments.map(t => (
        <TournamentCard key={t.id} t={t} section={section} pickStatus={pickStatus} />
      )) : (
        <p className="home-gender-empty">—</p>
      )}
    </div>
  )
}

function Section({ title, description, tournaments, section, pickStatus, emptyMessage }) {
  if (!tournaments.length && !emptyMessage) return null

  const mens = tournaments.filter(t => t.gender === 'M')
  const womens = tournaments.filter(t => t.gender === 'F')

  return (
    <section className="home-section">
      <div className="home-section-header">
        <h2>{title}</h2>
        <p className="home-section-desc">{description}</p>
      </div>
      {tournaments.length > 0 ? (
        <div className="home-gender-columns">
          <GenderCol label="ATP" tournaments={mens} section={section} pickStatus={pickStatus} />
          <GenderCol label="WTA" tournaments={womens} section={section} pickStatus={pickStatus} />
        </div>
      ) : (
        <p className="home-empty-section">{emptyMessage}</p>
      )}
    </section>
  )
}

function getSection(t) {
  if (t.status === 'active') return 'active'
  if (t.status === 'open') return 'open'
  if (t.status === 'completed' && t.end_date) {
    const today = new Date(); today.setHours(0, 0, 0, 0)
    const end = new Date(t.end_date + 'T00:00:00')
    const daysAgo = (today - end) / (1000 * 60 * 60 * 24)
    if (daysAgo >= 0 && daysAgo <= 7) return 'lastweek'
  }
  if (t.status === 'upcoming' && t.start_date) {
    const today = new Date(); today.setHours(0, 0, 0, 0)
    const in7Days = new Date(today); in7Days.setDate(today.getDate() + 8)
    const start = new Date(t.start_date + 'T00:00:00')
    if (start > today && start <= in7Days) return 'upcoming'
  }
  return null
}

function Modal({ title, onClose, children }) {
  return (
    <div className="home-modal-overlay" onClick={onClose}>
      <div className="home-modal" onClick={e => e.stopPropagation()}>
        <div className="home-modal-header">
          <h3>{title}</h3>
          <button className="home-modal-close" onClick={onClose}>✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}

function CreateLeagueModal({ onClose }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [mode, setMode] = useState('classic')
  const [showRealName, setShowRealName] = useState(false)
  const [customPoints, setCustomPoints] = useState('')
  const [error, setError] = useState('')

  const mutation = useMutation({
    mutationFn: createLeague,
    onSuccess: (lg) => { qc.invalidateQueries(['leagues']); navigate(`/leagues/${lg.id}`) },
    onError: (e) => setError(e.response?.data?.detail || 'Failed to create'),
  })

  const submit = (e) => {
    e.preventDefault()
    const payload = { name, scoring_mode: mode, is_public: false, show_real_name: showRealName }
    if (mode === 'custom') {
      try { payload.custom_points = JSON.parse(customPoints) }
      catch { setError('custom_points must be valid JSON'); return }
    }
    mutation.mutate(payload)
  }

  return (
    <Modal title="Create League" onClose={onClose}>
      <form onSubmit={submit} className="home-modal-form">
        <label className="home-modal-label">Name</label>
        <input className="home-modal-input" value={name} onChange={e => setName(e.target.value)} required placeholder="My Fantasy Group" autoFocus />
        <label className="home-modal-label">Scoring mode</label>
        <select className="home-modal-input" value={mode} onChange={e => setMode(e.target.value)}>
          <option value="classic">Classic Bracket (1→2→4→8…)</option>
          <option value="atp_wta">ATP/WTA Points Mirror</option>
          <option value="upset_bonus">Classic + Upset Bonus</option>
          <option value="custom">Custom</option>
        </select>
        {mode === 'custom' && (
          <>
            <label className="home-modal-label">Points per round (JSON)</label>
            <input className="home-modal-input" value={customPoints} onChange={e => setCustomPoints(e.target.value)}
              placeholder='{"1":1,"2":2,"3":4,"4":8,"5":16,"6":32,"7":128}' />
          </>
        )}
        <label className="home-modal-check">
          <input type="checkbox" checked={showRealName} onChange={e => setShowRealName(e.target.checked)} />
          Show real name on hover
        </label>
        {error && <p className="home-modal-error">{error}</p>}
        <button type="submit" className="btn-primary" disabled={mutation.isPending}>
          {mutation.isPending ? 'Creating…' : 'Create League'}
        </button>
      </form>
    </Modal>
  )
}

function JoinLeagueModal({ onClose }) {
  const qc = useQueryClient()
  const [code, setCode] = useState('')
  const [error, setError] = useState('')

  const mutation = useMutation({
    mutationFn: (code) => joinLeague(code),
    onSuccess: () => { qc.invalidateQueries(['leagues']); onClose() },
    onError: (e) => setError(e.response?.data?.detail || 'Failed to join'),
  })

  const submit = (e) => {
    e.preventDefault()
    setError('')
    mutation.mutate(code)
  }

  return (
    <Modal title="Join a League" onClose={onClose}>
      <form onSubmit={submit} className="home-modal-form">
        <label className="home-modal-label">Invite Code</label>
        <input className="home-modal-input" value={code} onChange={e => setCode(e.target.value)} required placeholder="e.g. F5KP1" autoFocus />
        {error && <p className="home-modal-error">{error}</p>}
        <button type="submit" className="btn-primary" disabled={!code || mutation.isPending}>
          {mutation.isPending ? 'Joining…' : 'Join League'}
        </button>
      </form>
    </Modal>
  )
}

export default function Home() {
  const { user } = useAuth()
  const [modal, setModal] = useState(null)  // 'create' | 'join' | null
  const { data: tournaments } = useQuery({ queryKey: ['tournaments'], queryFn: listTournaments })
  const { data: leagues } = useQuery({ queryKey: ['leagues'], queryFn: listLeagues, enabled: !!user })
  const { data: enteredList } = useQuery({
    queryKey: ['entry-status'],
    queryFn: getEntryStatus,
    enabled: !!user,
  })
  const pickStatus = enteredList || null  // {tournament_id: 'complete' | 'partial'}

  const dataLoaded = tournaments !== undefined
  const active = tournaments?.filter(t => getSection(t) === 'active') || []
  const open = tournaments?.filter(t => getSection(t) === 'open') || []
  const lastWeek = tournaments?.filter(t => getSection(t) === 'lastweek') || []
  const upcoming = tournaments?.filter(t => getSection(t) === 'upcoming') || []

  return (
    <div className="home">
      {!user && (
        <div className="hero">
          <div className="hero-cta">
            <Link to="/register" className="btn-clay">Create Account</Link>
            <Link to="/login" className="btn-secondary">Log in</Link>
          </div>
        </div>
      )}

      <div className="dashboard">
        <h1 className="dashboard-title">Dashboard</h1>
        <div className="dashboard-columns">

          <div className="dashboard-panel dashboard-panel--tournaments">
            <div className="home-sections">
              <Section
                title="Active"
                description="Matches are underway. 🔒 Selection is closed."
                tournaments={active}
                section="active"
                pickStatus={pickStatus}
                emptyMessage={dataLoaded ? 'No active tournaments at this time.' : null}
              />
              <Section
                title="Open"
                description={open.length > 0 ? "The draw has been created. Matches have not yet begun. Make your picks now!" : null}
                tournaments={open}
                section="open"
                pickStatus={pickStatus}
                emptyMessage={dataLoaded ? 'No open tournaments at this time.' : null}
              />
              <Section
                title="Last Week"
                description="Completed in the past 7 days."
                tournaments={lastWeek}
                section="lastweek"
                pickStatus={pickStatus}
              />
              <Section
                title="Next Week"
                description="Starting within 8 days — draw not yet released."
                tournaments={upcoming}
                section="upcoming"
                pickStatus={pickStatus}
              />
            </div>
          </div>

          <div className="dashboard-panel dashboard-panel--leagues">
            <h2 className="dashboard-panel-title">Leagues</h2>
            {user && (
              <div className="league-sidebar-actions">
                <button className="league-sidebar-btn" onClick={() => setModal('create')}>Create</button>
                <button className="league-sidebar-btn" onClick={() => setModal('join')}>Join</button>
              </div>
            )}
            <div className="league-sidebar-list">
              <Link to="/leagues" className="league-sidebar-card league-sidebar-card--global">
                <div className="league-sidebar-card-name">🌍 Global</div>
                <div className="league-sidebar-card-sub">All players</div>
              </Link>
              {user && leagues && leagues.map(lg => (
                <Link key={lg.id} to={`/leagues/${lg.id}`} className="league-sidebar-card">
                  <div className="league-sidebar-card-name">{lg.name}</div>
                  <div className="league-sidebar-card-sub">{lg.member_count} member{lg.member_count !== 1 ? 's' : ''}</div>
                </Link>
              ))}
              {!user && (
                <p className="league-sidebar-login">
                  <Link to="/login">Log in</Link> to see your private leagues.
                </p>
              )}
            </div>
          </div>

        </div>
      </div>

      {modal === 'create' && <CreateLeagueModal onClose={() => setModal(null)} />}
      {modal === 'join'   && <JoinLeagueModal   onClose={() => setModal(null)} />}
    </div>
  )
}
