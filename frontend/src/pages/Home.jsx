import { useState, useRef, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listTournaments } from '../api/tournaments'
import { listLeagues, createLeague, joinLeague } from '../api/leagues'
import { getEntryStatus } from '../api/predictions'
import { useAuth } from '../store/auth'
import { TournamentCard } from '../components/design/TournamentCard.jsx'
import { SectionHeader } from '../components/design/SectionHeader.jsx'
import { LeagueCard } from '../components/design/LeagueCard.jsx'
import { computeCohortInfo, getHomeSection } from '../utils/drawStatus.js'
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

export function CreateLeagueModal({ onClose }) {
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

export function JoinLeagueModal({ onClose }) {
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

function LeagueStrip({ memberLeagues, onCreateLeague, onJoinLeague }) {
  const scrollRef = useRef(null)
  const [canScrollLeft, setCanScrollLeft]   = useState(false)
  const [canScrollRight, setCanScrollRight] = useState(false)

  const checkScroll = () => {
    const el = scrollRef.current
    if (!el) return
    setCanScrollLeft(el.scrollLeft > 1)
    setCanScrollRight(el.scrollLeft < el.scrollWidth - el.clientWidth - 1)
  }

  useEffect(() => {
    checkScroll()
    const el = scrollRef.current
    if (!el) return
    el.addEventListener('scroll', checkScroll, { passive: true })
    const ro = new ResizeObserver(checkScroll)
    ro.observe(el)
    return () => { el.removeEventListener('scroll', checkScroll); ro.disconnect() }
  }, [memberLeagues])

  const scroll = (dir) => scrollRef.current?.scrollBy({ left: dir * 220, behavior: 'smooth' })

  return (
    <div className="dash-league-strip">
      <div className="dash-league-actions">
        <div className="dash-league-actions-header">Leagues</div>
        <div className="dash-league-actions-btns">
          <button className="league-sidebar-btn" onClick={onCreateLeague}>Create League</button>
          <button className="league-sidebar-btn" onClick={onJoinLeague}>Join League</button>
        </div>
      </div>
      <div className="dash-league-divider" />
      <div className="dash-league-scroll-wrap">
        <div className="dash-league-scroll" ref={scrollRef}>
          <LeagueCard name="Global" sublabel="All players" global icon="🌍" to="/leagues" style={{ minWidth: 120 }} />
          {memberLeagues.map(lg => (
            <LeagueCard
              key={lg.id}
              name={lg.name}
              sublabel={`${lg.member_count} member${lg.member_count !== 1 ? 's' : ''}`}
              to={`/leagues/${lg.id}`}
              style={{ minWidth: 120 }}
            />
          ))}
        </div>
        {canScrollLeft  && <button className="dash-league-arrow dash-league-arrow--left"  onClick={() => scroll(-1)}>‹</button>}
        {canScrollRight && <button className="dash-league-arrow dash-league-arrow--right" onClick={() => scroll(1)}>›</button>}
      </div>
    </div>
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
  const cohortInfo = computeCohortInfo(tournaments)
  const sec = t => getHomeSection(t, cohortInfo)
  const active   = tournaments?.filter(t => sec(t) === 'active')   || []
  const open     = tournaments?.filter(t => sec(t) === 'open')     || []
  const lastWeek = tournaments?.filter(t => sec(t) === 'lastweek') || []
  const upcoming = tournaments?.filter(t => sec(t) === 'upcoming') || []

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
        <div style={{ marginBottom: 16 }}>
          <h1 style={{
            fontFamily: 'var(--font-display)', fontWeight: 900, fontSize: '2.75rem',
            letterSpacing: '0.01em', lineHeight: 1, color: 'var(--ink-900)', textTransform: 'uppercase',
          }}>Dashboard</h1>
        </div>

        {user && (
          <LeagueStrip
            memberLeagues={memberLeagues}
            onCreateLeague={() => setModal('create')}
            onJoinLeague={() => setModal('join')}
          />
        )}

        <h2 style={{
          fontFamily: 'var(--font-display)', fontWeight: 900, fontSize: '1.6rem',
          letterSpacing: '0.01em', textTransform: 'uppercase', color: 'var(--ink-900)',
          marginBottom: 14,
        }}>Draws</h2>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, width: 'fit-content' }}>
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
      </div>

      {modal === 'create'         && <CreateLeagueModal    onClose={() => setModal(null)} />}
      {modal === 'join'           && <JoinLeagueModal      onClose={() => setModal(null)} />}
      {modal === 'login-required' && <LoginRequiredModal   onClose={() => setModal(null)} />}
    </div>
  )
}
