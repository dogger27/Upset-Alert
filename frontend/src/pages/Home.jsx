import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { listTournaments } from '../api/tournaments'
import { listLeagues } from '../api/leagues'
import { getEntryStatus } from '../api/predictions'
import { useAuth } from '../store/auth'
import './Home.css'

function fmtDate(s) {
  if (!s) return null
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function fmtQueryTime(ts) {
  if (!ts) return null
  const d = new Date(ts)
  const date = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  const time = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })
    .replace(' AM', 'am').replace(' PM', 'pm')
  return `${date}, ${time}`
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
  const catShort = t.category ? t.category.replace(/^(ATP|WTA)\s+/, '') : ''
  const surface = t.surface ? t.surface.replace(/\s*\(.*?\)/g, '') : ''
  const city = t.city ? t.city : ''
  const hasDrawData = t.status === 'completed' || !!t.draw_released_direct_at

  const cardClass = `home-card home-card-${t.gender === 'M' ? 'men' : 'women'}${!hasDrawData ? ' home-card-upcoming' : ''}`
  const inner = (
    <>
      <div className="home-card-title-row">
        <span className="home-card-title">
          {t.name}
          {t.start_date && (
            <span className="home-card-dates">{fmtDateRange(t.start_date, t.end_date)}</span>
          )}
        </span>
        {catShort && <span className="home-card-level">{catShort}</span>}
      </div>
      <div className="home-card-sub-row">
        <span className="home-card-sub">{city}{city && surface ? ' · ' : ''}{surface}</span>
        <DrawDates t={t} section={section} />
      </div>
      {(section === 'active' || section === 'open') && (
        <div className="home-card-bottom-row">
          <span className="home-card-modified">
            {t.last_scraped_at ? `Last modified: ${fmtModified(t.last_scraped_at)}` : ''}
          </span>
          {section === 'active' && pickState === 'complete'
            ? <span className="home-card-entered competing">★ Competing</span>
            : pickState === 'complete'
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
  if (t.status === 'completed') return null
  if (t.status === 'upcoming' && t.start_date) {
    const today = new Date(); today.setHours(0, 0, 0, 0)
    const in7Days = new Date(today); in7Days.setDate(today.getDate() + 8)
    const start = new Date(t.start_date + 'T00:00:00')
    if (start > today && start <= in7Days) return 'upcoming'
  }
  return null
}

export default function Home() {
  const { user } = useAuth()
  const { data: tournaments, dataUpdatedAt } = useQuery({ queryKey: ['tournaments'], queryFn: listTournaments })
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
  const upcoming = tournaments?.filter(t => getSection(t) === 'upcoming') || []

  return (
    <div className="home">
      {!user && (
        <div className="hero">
          <div className="hero-cta">
            <Link to="/register" className="btn-clay">Get started</Link>
            <Link to="/login" className="btn-secondary">Log in</Link>
          </div>
        </div>
      )}

      <div className="home-sections">
        {dataLoaded && (
          <div className="home-main-title-row">
            <h2 className="home-main-title">Tournaments</h2>
            <span className="last-queried">Last queried: {fmtQueryTime(dataUpdatedAt)}</span>
          </div>
        )}

        <Section
          title="Active"
          description="Matches are underway. Selection is closed."
          tournaments={active}
          section="active"
          pickStatus={pickStatus}
          emptyMessage={dataLoaded ? 'No active tournaments at this time.' : null}
        />

        <Section
          title="Open"
          description="Direct Acceptance draw is set — no matches yet. Selection is OPEN."
          tournaments={open}
          section="open"
          pickStatus={pickStatus}
          emptyMessage={dataLoaded ? 'No open tournaments at this time.' : null}
        />

        <Section
          title="Upcoming"
          description="Starting within 8 days — draw not yet released."
          tournaments={upcoming}
          section="upcoming"
          pickStatus={pickStatus}
        />

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
