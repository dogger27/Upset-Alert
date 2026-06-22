import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import client from '../api/client'
import './AuthForm.css'

export default function ResetPassword() {
  const [params] = useSearchParams()
  const token = params.get('token') || ''
  const navigate = useNavigate()

  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  if (!token) {
    return (
      <div className="auth-page">
        <div className="auth-card card">
          <h2>Invalid link</h2>
          <p style={{ color: 'var(--text-muted)' }}>
            This reset link is missing or invalid.
          </p>
          <p className="auth-footer"><Link to="/forgot-password">Request a new one</Link></p>
        </div>
      </div>
    )
  }

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    if (password !== confirm) { setError('Passwords do not match'); return }
    if (password.length < 8) { setError('Password must be at least 8 characters'); return }
    setLoading(true)
    try {
      await client.post('/auth/reset-password', { token, password })
      navigate('/login', { state: { message: 'Password reset — please log in.' } })
    } catch (err) {
      setError(err.response?.data?.detail || 'Link expired or invalid. Please request a new one.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card card">
        <h2>Reset password</h2>
        <form onSubmit={submit}>
          <label>New password</label>
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            minLength={8}
            required
          />
          <label>Confirm password</label>
          <input
            type="password"
            value={confirm}
            onChange={e => setConfirm(e.target.value)}
            required
          />
          {error && <p className="error">{error}</p>}
          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? 'Saving…' : 'Set new password'}
          </button>
        </form>
      </div>
    </div>
  )
}
