import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import client from '../api/client'
import './DrawHistory.css'

function fetchMyHistory() {
  return client.get('/auth/me/draw-history').then(r => ({ username: null, entries: r.data }))
}
function fetchUserHistory(userId) {
  return client.get(`/auth/users/${userId}/draw-history`).then(r => r.data)
}

function categoryShort(cat) {
  if (!cat) return ''
  if (cat.includes('Slam') || cat.includes('slam')) return 'Grand Slam'
  if (cat.includes('1000')) return '1000'
  if (cat.includes('500')) return '500'
  return '250'
}

function categoryLabel(entry) {
  const isATP = entry.gender === 'M'
  return entry.category ? `${isATP ? 'ATP' : 'WTA'} ${categoryShort(entry.category)}` : (isATP ? 'ATP' : 'WTA')
}

function rankBadge(rank) {
  if (rank === 1) return 'dh-rank--gold'
  if (rank === 2) return 'dh-rank--silver'
  if (rank === 3) return 'dh-rank--bronze'
  return ''
}

function fmtDateRange(start, end) {
  if (!start) return null
  const s = new Date(start + 'T00:00:00')
  const fmt = (d, opts) => d.toLocaleDateString('en-US', opts)
  if (!end) return fmt(s, { month: 'short', day: 'numeric', year: 'numeric' })
  const e = new Date(end + 'T00:00:00')
  if (s.getFullYear() !== e.getFullYear()) {
    return `${fmt(s, { month: 'short', day: 'numeric', year: 'numeric' })} – ${fmt(e, { month: 'short', day: 'numeric', year: 'numeric' })}`
  }
  if (s.getMonth() === e.getMonth()) {
    return `${fmt(s, { month: 'short', day: 'numeric' })} – ${e.getDate()}, ${e.getFullYear()}`
  }
  return `${fmt(s, { month: 'short', day: 'numeric' })} – ${fmt(e, { month: 'short', day: 'numeric' })}, ${e.getFullYear()}`
}

const COLUMNS = [
  { key: 'tournament', label: 'Tournament' },
  { key: 'category', label: 'Category' },
  { key: 'date', label: 'Date' },
  { key: 'points', label: 'Points' },
  { key: 'correct', label: 'Correct' },
  { key: 'rank', label: 'Rank (Global)' },
]

const DEFAULT_DIR = { tournament: 'asc', category: 'asc', date: 'desc', points: 'desc', correct: 'desc', rank: 'asc' }

function sortValue(entry, key) {
  switch (key) {
    case 'tournament': return entry.name ?? null
    case 'category': return categoryLabel(entry)
    case 'date': return entry.start_date ?? null
    case 'points': return entry.points ?? null
    case 'correct': return entry.total_matches > 0 ? entry.correct_count / entry.total_matches : null
    case 'rank': return entry.rank ?? null
    default: return null
  }
}

function compareEntries(a, b, key, dir) {
  const va = sortValue(a, key)
  const vb = sortValue(b, key)
  const aNull = va === null || va === undefined || va === ''
  const bNull = vb === null || vb === undefined || vb === ''
  if (aNull && bNull) return 0
  if (aNull) return 1
  if (bNull) return -1
  const cmp = typeof va === 'number' && typeof vb === 'number'
    ? va - vb
    : String(va).localeCompare(String(vb))
  return dir === 'asc' ? cmp : -cmp
}

function SortIndicator({ active, dir }) {
  if (!active) return <span className="dh-sort-icon dh-sort-icon--idle">⇅</span>
  return <span className="dh-sort-icon">{dir === 'asc' ? '▲' : '▼'}</span>
}

const BracketIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="17" y1="12" x2="24" y2="12"/>
    <polyline points="17,6 17,18"/>
    <line x1="10" y1="6" x2="17" y2="6"/>
    <line x1="10" y1="18" x2="17" y2="18"/>
    <polyline points="10,3 10,9"/>
    <polyline points="10,15 10,21"/>
    <line x1="3" y1="3" x2="10" y2="3"/>
    <line x1="3" y1="9" x2="10" y2="9"/>
    <line x1="3" y1="15" x2="10" y2="15"/>
    <line x1="3" y1="21" x2="10" y2="21"/>
  </svg>
)

function TournamentRow({ entry, userId }) {
  const isATP = entry.gender === 'M'
  const catLabel = categoryLabel(entry)
  const dateRange = fmtDateRange(entry.start_date, entry.end_date)
  const pct = entry.total_matches > 0
    ? ` (${(entry.correct_count / entry.total_matches * 100).toFixed(0)}%)`
    : ''

  const params = new URLSearchParams()
  if (userId) params.set('user', String(userId))
  const qs = params.toString()
  const drawUrl = `/tournaments/${entry.tournament_id}${qs ? '?' + qs : ''}`

  return (
    <tr className="dh-row">
      <td className="dh-cell dh-cell-tournament" data-label="Tournament">
        <Link to={drawUrl} className="dh-tourn-link" title="View draw">
          <BracketIcon />
          <span className="dh-tourn-name">{entry.name}</span>
        </Link>
      </td>
      <td className="dh-cell dh-cell-category" data-label="Category">
        <span className={`dh-category ${isATP ? 'dh-category--atp' : 'dh-category--wta'}`}>{catLabel}</span>
      </td>
      <td className="dh-cell" data-label="Date">{dateRange}</td>
      <td className="dh-cell" data-label="Points"><strong>{entry.points}</strong></td>
      <td className="dh-cell" data-label="Correct">{entry.correct_count} / {entry.total_matches}{pct}</td>
      <td className="dh-cell" data-label="Rank (Global)">
        <span className={`dh-rank ${rankBadge(entry.rank)}`}>#{entry.rank} / {entry.total_participants}</span>
      </td>
    </tr>
  )
}

export default function DrawHistory() {
  const [searchParams] = useSearchParams()
  const userIdParam = searchParams.get('user')
  const userId = userIdParam ? Number(userIdParam) : null

  const { data, isLoading, isError } = useQuery({
    queryKey: ['draw-history', userId],
    queryFn: () => userId ? fetchUserHistory(userId) : fetchMyHistory(),
    staleTime: 5 * 60 * 1000,
  })

  const [sortKey, setSortKey] = useState('correct')
  const [sortDir, setSortDir] = useState(DEFAULT_DIR.correct)

  function handleSort(key) {
    if (key === sortKey) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir(DEFAULT_DIR[key] ?? 'asc')
    }
  }

  const username = data?.username ?? null
  const entries = data?.entries ?? (Array.isArray(data) ? data : [])

  const sortedEntries = useMemo(() => {
    return [...entries].sort((a, b) => compareEntries(a, b, sortKey, sortDir))
  }, [entries, sortKey, sortDir])

  const pageTitle = 'Draw History'

  if (isLoading) return <div className="dh-page"><div className="dh-container"><p className="dh-state">Loading…</p></div></div>
  if (isError)   return <div className="dh-page"><div className="dh-container"><p className="dh-state dh-state--error">Failed to load draw history.</p></div></div>
  if (!entries || entries.length === 0) return (
    <div className="dh-page">
      <div className="dh-container">
        <div className="dh-header">
          <div className="dh-header-row">
            <h1 className="dh-title">{pageTitle}</h1>
            {username && <span className="dh-username-label">{username}</span>}
          </div>
          <p className="dh-subtitle">Global league</p>
        </div>
        <p className="dh-state">
          {username
            ? <><strong>{username}</strong> has not yet completed any draws.</>
            : <>You have not yet completed any draws. <Link to="/">Browse tournaments →</Link></>}
        </p>
      </div>
    </div>
  )

  return (
    <div className="dh-page">
      <div className="dh-container">
        <div className="dh-header">
          <div className="dh-header-row">
            <h1 className="dh-title">{pageTitle}</h1>
            {username && <span className="dh-username-label">{username}</span>}
          </div>
          <p className="dh-subtitle">Global league</p>
        </div>

        <div className="dh-table-wrap">
          <table className="dh-table">
            <thead>
              <tr>
                {COLUMNS.map(col => (
                  <th
                    key={col.key}
                    className="dh-th-sortable"
                    aria-sort={sortKey === col.key ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
                    tabIndex={0}
                    onClick={() => handleSort(col.key)}
                    onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleSort(col.key) } }}
                  >
                    <span className="dh-th-inner">
                      {col.label}
                      <SortIndicator active={sortKey === col.key} dir={sortDir} />
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedEntries.map(e => <TournamentRow key={e.tournament_id} entry={e} userId={userId} />)}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
