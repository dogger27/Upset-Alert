import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listLeagues, createLeague, joinLeague } from '../api/leagues'
import { useAuth } from '../store/auth'
import './Leagues.css'

const SCORING_LABELS = {
  classic: 'Classic Bracket (doubling points)',
  atp_wta: 'ATP/WTA Points Mirror',
  upset_bonus: 'Classic + Upset Bonus',
  custom: 'Custom',
}

export default function Leagues() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [showCreate, setShowCreate] = useState(false)
  const [joinCode, setJoinCode] = useState('')
  const [joinLeagueId, setJoinLeagueId] = useState('')

  const { data: leagues } = useQuery({ queryKey: ['leagues'], queryFn: listLeagues })

  const joinMutation = useMutation({
    mutationFn: ({ id, code }) => joinLeague(id, code),
    onSuccess: () => { qc.invalidateQueries(['leagues']); setJoinCode(''); setJoinLeagueId('') },
  })

  return (
    <div className="leagues-page">
      <div className="leagues-header">
        <h1>Leagues</h1>
        {user && (
          <button className="btn-primary" onClick={() => setShowCreate(s => !s)}>
            {showCreate ? 'Cancel' : '+ Create League'}
          </button>
        )}
      </div>

      {showCreate && (
        <CreateLeagueForm
          onDone={(lg) => { setShowCreate(false); navigate(`/leagues/${lg.id}`) }}
        />
      )}

      {user && (
        <div className="card join-box">
          <h3>Join a private league</h3>
          <div className="join-row">
            <input
              placeholder="League ID"
              value={joinLeagueId}
              onChange={e => setJoinLeagueId(e.target.value)}
              style={{ maxWidth: 120 }}
            />
            <input
              placeholder="Invite code"
              value={joinCode}
              onChange={e => setJoinCode(e.target.value)}
              style={{ maxWidth: 180 }}
            />
            <button
              className="btn-secondary"
              disabled={!joinLeagueId || joinMutation.isPending}
              onClick={() => joinMutation.mutate({ id: Number(joinLeagueId), code: joinCode })}
            >
              Join
            </button>
          </div>
          {joinMutation.isError && (
            <p className="error">{joinMutation.error?.response?.data?.detail}</p>
          )}
        </div>
      )}

      <div className="leagues-grid">
        {leagues?.map(lg => (
          <Link key={lg.id} to={`/leagues/${lg.id}`} className="league-card">
            <div className="league-card-name">{lg.name}</div>
            <div className="muted">{SCORING_LABELS[lg.scoring_mode]}</div>
            <div className="league-card-footer">
              <span>{lg.member_count} member{lg.member_count !== 1 ? 's' : ''}</span>
              <span className={`status-badge status-${lg.is_public ? 'public' : 'private'}`}>
                {lg.is_public ? 'Public' : 'Private'}
              </span>
            </div>
          </Link>
        ))}
        {leagues?.length === 0 && (
          <p className="muted">No leagues yet.</p>
        )}
      </div>
    </div>
  )
}

function CreateLeagueForm({ onDone }) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [mode, setMode] = useState('classic')
  const [isPublic, setIsPublic] = useState(false)
  const [customPoints, setCustomPoints] = useState('')
  const [error, setError] = useState('')

  const mutation = useMutation({
    mutationFn: createLeague,
    onSuccess: (lg) => { qc.invalidateQueries(['leagues']); onDone(lg) },
    onError: (e) => setError(e.response?.data?.detail || 'Failed to create'),
  })

  const submit = (e) => {
    e.preventDefault()
    const payload = { name, scoring_mode: mode, is_public: isPublic }
    if (mode === 'custom') {
      try { payload.custom_points = JSON.parse(customPoints) }
      catch { setError('custom_points must be valid JSON, e.g. {"1":1,"2":2,"3":4}'); return }
    }
    mutation.mutate(payload)
  }

  return (
    <div className="card create-form">
      <h3>New League</h3>
      <form onSubmit={submit}>
        <div className="form-row">
          <label>Name</label>
          <input value={name} onChange={e => setName(e.target.value)} required placeholder="My Fantasy Group" />
        </div>
        <div className="form-row">
          <label>Scoring mode</label>
          <select value={mode} onChange={e => setMode(e.target.value)}>
            <option value="classic">Classic Bracket (1→2→4→8…)</option>
            <option value="atp_wta">ATP/WTA Points Mirror</option>
            <option value="upset_bonus">Classic + Upset Bonus</option>
            <option value="custom">Custom</option>
          </select>
        </div>
        {mode === 'custom' && (
          <div className="form-row">
            <label>Points per round (JSON) e.g. {"{"}"1":1,"2":2,"3":4{"}"}  </label>
            <input value={customPoints} onChange={e => setCustomPoints(e.target.value)}
              placeholder='{"1":1,"2":2,"3":4,"4":8,"5":16,"6":32,"7":128}' />
          </div>
        )}
        <div className="form-row form-check">
          <label>
            <input type="checkbox" checked={isPublic} onChange={e => setIsPublic(e.target.checked)} />
            Public league (anyone can join)
          </label>
        </div>
        {error && <p className="error">{error}</p>}
        <button type="submit" className="btn-primary" disabled={mutation.isPending}>
          {mutation.isPending ? 'Creating…' : 'Create League'}
        </button>
      </form>
    </div>
  )
}
