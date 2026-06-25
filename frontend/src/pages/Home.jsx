import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listTournaments } from '../api/tournaments'
import { listLeagues, createLeague, joinLeague } from '../api/leagues'
import { getEntryStatus } from '../api/predictions'
import { useAuth } from '../store/auth'
import { TournamentCard } from '../components/design/TournamentCard.jsx'
import { SectionHeader } from '../components/design/SectionHeader.jsx'
import { LeagueCard } from '../components/design/LeagueCard.jsx'
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
    ? `${mo(s)} ${s.getDate()} – ${e.getDate()}`
    : `${mo(s)} ${s.getDate()} – ${mo(e)} ${e.getDate()}`
}

function tierFromCategory(category) {
  const cat = (category || '').toUpperCase()
  if (cat.includes('SLAM') || cat.includes('GRAND')) return 'GS'
  if (cat.includes('1000')) return '1000'
  if (cat.includes('500')) return '500'
  return '250'
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
    const in8Days = new Date(today); in8Days.setDate(today.getDate() + 8)
    const start = new Date(t.start_date + 'T00:00:00')
    if (start > today && start <= in8Days) return 'upcoming'
  }
  return null
}

function TCard({ t, section, pickStatus, onLoginRequired }) {
  const { user } = useAuth()
  const pickState = pickStatus?.[t.id] ?? 'none'
  const tour = t.gender === 'M' ? 'ATP' : 'WTA'
  const tier = tierFromCategory(t.category)
  const surface = (t.surface || 'hard').replace(/\s*\(.*?\)/g, '').trim().toLowerCase()
  const dateRange = fmtDateRange(t.start_date, t.end_date)
  const hasDrawData = t.status === 'completed' || !!t.draw_released_direct_at
  const drawDates = section === 'upcoming' ? {
    da: t.draw_release_direct ? fmtDate(t.draw_release_direct) : null,
    qual: t.draw_release_qualifiers ? fmtDate(t.draw_release_qualifiers) : null,
  } : null

  const wikiUrl = section === 'upcoming' && t.wiki_page_id
    ? `https://en.wikipedia.org/wiki?curid=${t.wiki_page_id}`
    : undefined

  const toLink = hasDrawData ? `/tournaments/${t.id}` : undefined

  return (
    <TournamentCard
      tour={tour}
      name={t.name}
      city={t.city}
      surface={surface}
      tier={tier}
      dateRange={dateRange}
      section={section}
      pickState={pickState}
      drawDates={drawDates}
      to={user ? toLink : undefined}
      onGuestClick={!user && toLink ? onLoginRequired : undefined}
      wikiUrl={wikiUrl}
    />
  )
}

function GenderCol({ label, tour, tournaments, section, pickStatus, onLoginRequired }) {
  const accent = tour === 'ATP' ? 'var(--atp-600)' : 'var(--wta-600)'
  const borderColor = tour === 'ATP' ? 'var(--atp-100)' : 'var(--wta-100)'

  if (!tournaments.length) return <div style={{ width: 400 }} />

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 9, width: 400 }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 7,
        fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: '0.82rem',
        letterSpacing: '0.1em', textTransform: 'uppercase', color: accent,
        paddingBottom: 6, borderBottom: `2px solid ${borderColor}`,
      }}>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: accent }} />
        {label}
      </div>
      {tournaments.map(t => (
        <TCard key={t.id} t={t} section={section} pickStatus={pickStatus} onLoginRequired={onLoginRequired} />
      ))}
    </div>
  )
}

const SECTION_BG = {
  open:    'rgba(201,120,58,0.07)',   // faint clay tint
  active:  'rgba(45,106,79,0.07)',    // faint green tint
  muted:   'rgba(147,163,156,0.10)',  // neutral gray tint
}

function Section({ title, description, accent, live, items, section, pickStatus, emptyMessage, onLoginRequired }) {
  if (!items.length && !emptyMessage) return null
  const atp = items.filter(t => t.gender === 'M')
  const wta = items.filter(t => t.gender === 'F')
  const bg = SECTION_BG[accent] || SECTION_BG.muted
  return (
    <section style={{
      display: 'flex', flexDirection: 'column', gap: 16,
      background: bg, border: '1px solid var(--border-strong)',
      borderRadius: 'var(--radius-lg)', padding: '20px 24px 22px',
      boxShadow: 'var(--shadow-xs)',
    }}>
      <SectionHeader
        title={title}
        description={description}
        accent={accent}
        live={live}
        count={items.length}
      />
      {items.length ? (
        <div style={{ display: 'flex', gap: 22, paddingLeft: 4 }}>
          <GenderCol label="ATP" tour="ATP" tournaments={atp} section={section} pickStatus={pickStatus} onLoginRequired={onLoginRequired} />
          <GenderCol label="WTA" tour="WTA" tournaments={wta} section={section} pickStatus={pickStatus} onLoginRequired={onLoginRequired} />
        </div>
      ) : (
        <p style={{ fontFamily: 'var(--font-body)', fontSize: '0.85rem', color: 'var(--text-muted)', fontStyle: 'italic', margin: 0, paddingLeft: 4 }}>
          {emptyMessage}
        </p>
      )}
    </section>
  )
}

function Modal({ title, onClose, children }) {
  return (
    <div className="home-modal-overlay" onClick={onClose}>
      <div className="home-modal" onClick={e => e.stopPropagation()}
        style={{ animation: 'ua-rise 0.22s var(--ease-out)' }}>
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
  const [showRealName, setShowRealName] = useState(false)
  const [error, setError] = useState('')

  const mutation = useMutation({
    mutationFn: createLeague,
    onSuccess: (lg) => { qc.invalidateQueries(['leagues']); navigate(`/leagues/${lg.id}`) },
    onError: (e) => setError(e.response?.data?.detail || 'Failed to create'),
  })

  const submit = (e) => {
    e.preventDefault()
    mutation.mutate({ name, scoring_mode: 'classic', is_public: false, show_real_name: showRealName })
  }

  return (
    <Modal title="Create League" onClose={onClose}>
      <form onSubmit={submit} className="home-modal-form">
        <label className="home-modal-label">Name</label>
        <input className="home-modal-input" value={name} onChange={e => setName(e.target.value)} required placeholder="My Fantasy Group" autoFocus />
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

function LoginRequiredModal({ onClose }) {
  return (
    <Modal title="Login Required" onClose={onClose}>
      <p style={{ fontFamily: 'var(--font-body)', fontSize: '0.92rem', color: 'var(--ink-700)', margin: '0 0 20px' }}>
        Please log in to view the draw and make match predictions!
      </p>
      <div style={{ display: 'flex', gap: 10 }}>
        <Link to="/login" className="btn-secondary" style={{ flex: 1, textAlign: 'center' }}>Log in</Link>
        <Link to="/register" className="btn-clay" style={{ flex: 1, textAlign: 'center' }}>Create Account</Link>
      </div>
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
        <input className="home-modal-input home-modal-input--mono" value={code} onChange={e => setCode(e.target.value.toUpperCase())} required placeholder="e.g. F5KP1" autoFocus />
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
  const [modal, setModal] = useState(null)
  const { data: tournaments } = useQuery({ queryKey: ['tournaments'], queryFn: listTournaments })
  const { data: leagues } = useQuery({ queryKey: ['leagues'], queryFn: listLeagues, enabled: !!user })
  const { data: enteredList } = useQuery({
    queryKey: ['entry-status'],
    queryFn: getEntryStatus,
    enabled: !!user,
  })
  const pickStatus = enteredList || null

  const memberLeagues = leagues?.filter(lg => lg.members?.some(m => m.id === user?.id)) ?? []
  const nonMemberLeagues = user?.is_admin
    ? (leagues?.filter(lg => !lg.members?.some(m => m.id === user?.id)) ?? [])
    : []

  const dataLoaded = tournaments !== undefined
  const active   = tournaments?.filter(t => getSection(t) === 'active')   || []
  const open     = tournaments?.filter(t => getSection(t) === 'open')     || []
  const lastWeek = tournaments?.filter(t => getSection(t) === 'lastweek') || []
  const upcoming = tournaments?.filter(t => getSection(t) === 'upcoming') || []

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)' }}>
      {!user && (
        <div className="hero">
          <div className="hero-cta">
            <Link to="/register" className="btn-clay">Create Account</Link>
            <Link to="/login" className="btn-secondary">Log in</Link>
          </div>
        </div>
      )}

      <div style={{ maxWidth: 1280, margin: '0 auto', padding: '26px 28px 56px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 22 }}>
          <div>
            <h1 style={{
              fontFamily: 'var(--font-display)', fontWeight: 900, fontSize: '2.75rem',
              letterSpacing: '0.01em', lineHeight: 1, color: 'var(--ink-900)', textTransform: 'uppercase',
            }}>Dashboard</h1>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 22, alignItems: 'flex-start' }}>
          {/* Tournaments column — don't stretch; let content width drive */}
          <div style={{ flex: '0 0 auto', display: 'flex', flexDirection: 'column', gap: 16 }}>
            <Section
              title="Open"
              accent="open"
              live
              description="The draw is out — get your picks locked in now."
              items={open}
              section="open"
              pickStatus={pickStatus}
              onLoginRequired={() => setModal('login-required')}
              emptyMessage={dataLoaded ? 'No open tournaments at this time.' : null}
            />
            <Section
              title="Active"
              accent="active"
              description="Matches are underway. 🔒 Selection is closed."
              items={active}
              section="active"
              pickStatus={pickStatus}
              onLoginRequired={() => setModal('login-required')}
              emptyMessage={dataLoaded ? 'No active tournaments at this time.' : null}
            />
            <Section
              title="Next Week"
              accent="muted"
              description="Starting within 8 days — draw not yet released."
              items={upcoming}
              section="upcoming"
              pickStatus={pickStatus}
            />
            {user && (
              <Section
                title="Last Week"
                accent="muted"
                description="Completed in the past 7 days."
                items={lastWeek}
                section="lastweek"
                pickStatus={pickStatus}
              />
            )}
          </div>

          {/* Leagues sidebar — only for logged-in users */}
          {user && <aside style={{
            width: 256, flexShrink: 0,
            background: 'rgba(45,106,79,0.07)', border: '1px solid var(--border-strong)',
            borderRadius: 'var(--radius-lg)', padding: '22px 20px',
            position: 'sticky', top: 20,
          }}>
            <h2 style={{
              fontFamily: 'var(--font-display)', fontWeight: 900, fontSize: '1.2rem',
              letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--ink-700)',
              marginBottom: 14,
            }}>Leagues</h2>

            <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
              <button className="league-sidebar-btn" onClick={() => setModal('create')}>Create</button>
              <button className="league-sidebar-btn" onClick={() => setModal('join')}>Join</button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <LeagueCard
                name="Global"
                sublabel="All players"
                global
                icon="🌍"
                to="/leagues"
              />
              {memberLeagues.map(lg => (
                <LeagueCard
                  key={lg.id}
                  name={lg.name}
                  sublabel={`${lg.member_count} member${lg.member_count !== 1 ? 's' : ''}`}
                  to={`/leagues/${lg.id}`}
                />
              ))}
              {nonMemberLeagues.length > 0 && (
                <>
                  <div style={{
                    borderTop: '1px solid var(--border)',
                    margin: '6px 0 2px',
                  }} />
                  <div style={{
                    fontFamily: 'var(--font-body)', fontSize: '0.7rem',
                    color: 'var(--text-muted)', letterSpacing: '0.05em',
                    textTransform: 'uppercase', paddingLeft: 2, marginBottom: 4,
                  }}>Other Leagues</div>
                  {nonMemberLeagues.map(lg => (
                    <LeagueCard
                      key={lg.id}
                      name={lg.name}
                      sublabel={`${lg.member_count} member${lg.member_count !== 1 ? 's' : ''}`}
                      to={`/leagues/${lg.id}`}
                      style={{ opacity: 0.75 }}
                    />
                  ))}
                </>
              )}

            </div>
          </aside>}
        </div>
      </div>

      {modal === 'create'         && <CreateLeagueModal    onClose={() => setModal(null)} />}
      {modal === 'join'           && <JoinLeagueModal      onClose={() => setModal(null)} />}
      {modal === 'login-required' && <LoginRequiredModal   onClose={() => setModal(null)} />}
    </div>
  )
}
