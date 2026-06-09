import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { listTournaments } from '../api/tournaments'
import { listLeagues } from '../api/leagues'
import { useAuth } from '../store/auth'
import './Home.css'

function fmtDate(s) {
  if (!s) return null
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
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

function TournamentCard({ t, section }) {
  const genderLabel = t.gender === 'M' ? "Men's" : "Women's"
  const catShort = t.category ? t.category.replace(/^(ATP|WTA)\s+/, '') : ''
  const surface = t.surface ? t.surface.replace(/\s*\(.*?\)/g, '') : ''
  const city = t.city ? t.city : ''

  return (
    <Link to={`/tournaments/${t.id}`} className={`home-card home-card-${t.gender === 'M' ? 'men' : 'women'}`}>
      <div className="home-card-meta">{catShort} · {genderLabel}</div>
      <div className="home-card-title">{t.name}</div>
      <div className="home-card-sub">{city}{city && surface ? ' · ' : ''}{surface}</div>
      <DrawDates t={t} section={section} />
    </Link>
  )
}

function Section({ title, description, tournaments, section, emptyMsg }) {
  if (!tournaments.length) return null
  return (
    <section className="home-section">
      <div className="home-section-header">
        <h2>{title}</h2>
        <p className="home-section-desc">{description}</p>
      </div>
      <div className="home-grid">
        {tournaments.map(t => <TournamentCard key={t.id} t={t} section={section} />)}
      </div>
    </section>
  )
}

function getSection(t) {
  const now = new Date()
  const in3Days = new Date(now.getTime() + 3 * 24 * 60 * 60 * 1000)

  if (t.status === 'active') return 'active'
  if (t.status === 'completed') return null

  // pending — show if DA draw is out (Open) or releasing within 3 days (Upcoming)
  if (t.draw_released_direct_at) return 'open'
  if (t.draw_release_direct && new Date(t.draw_release_direct) <= in3Days) return 'upcoming'

  return null
}

export default function Home() {
  const { user } = useAuth()
  const { data: tournaments } = useQuery({ queryKey: ['tournaments'], queryFn: listTournaments })
  const { data: leagues } = useQuery({ queryKey: ['leagues'], queryFn: listLeagues, enabled: !!user })

  const active = tournaments?.filter(t => getSection(t) === 'active') || []
  const open = tournaments?.filter(t => getSection(t) === 'open') || []
  const upcoming = tournaments?.filter(t => getSection(t) === 'upcoming') || []

  const hasAny = active.length + open.length + upcoming.length > 0

  return (
    <div className="home">
      <div className="hero">
        <h1>🚨 Upset Alert</h1>
        <p>Pick the bracket. Track every match. Beat your group.</p>
        {!user && (
          <div className="hero-cta">
            <Link to="/register" className="btn-clay">Get started</Link>
            <Link to="/login" className="btn-secondary">Log in</Link>
          </div>
        )}
      </div>

      <div className="home-sections">
        {hasAny && <h2 className="home-main-title">Tournaments</h2>}

        <Section
          title="Active"
          description="Matches are underway. Selection is closed."
          tournaments={active}
          section="active"
        />

        <Section
          title="Open"
          description="Direct Acceptance draw is set — no matches yet. Selection is OPEN."
          tournaments={open}
          section="open"
        />

        <Section
          title="Upcoming"
          description="DA players expected in the draw within 3 days."
          tournaments={upcoming}
          section="upcoming"
        />

        {!hasAny && (
          <div className="card" style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
            No tournaments in the next 3 days. Check back soon!
          </div>
        )}

        {user && leagues && leagues.length > 0 && (
          <section className="home-section">
            <div className="home-section-header">
              <h2>My Leagues</h2>
            </div>
            <div className="home-grid">
              {leagues.map(lg => (
                <Link key={lg.id} to={`/leagues/${lg.id}`} className="home-card">
                  <div className="home-card-meta">{lg.member_count} member{lg.member_count !== 1 ? 's' : ''}</div>
                  <div className="home-card-title">{lg.name}</div>
                  <div className="home-card-sub">{lg.scoring_mode}</div>
                  <div className={`status-badge status-${lg.is_public ? 'public' : 'private'}`}>
                    {lg.is_public ? 'Public' : 'Private'}
                  </div>
                </Link>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  )
}
