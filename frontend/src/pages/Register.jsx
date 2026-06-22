import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import './AuthForm.css'

export default function Register() {
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [fullName, setFullName] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [registered, setRegistered] = useState(false)
  const { register } = useAuth()

  const submit = async (e) => {
    e.preventDefault()
    setError(''); setLoading(true)
    if (password !== confirm) { setError('Passwords do not match'); setLoading(false); return }
    try {
      await register(email, username, fullName, password)
      setRegistered(true)
    } catch (err) {
      setError(err.response?.data?.detail || 'Registration failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card card">
        {registered ? (
          <>
            <h2>Check your email</h2>
            <p style={{ color: 'var(--text-muted)', lineHeight: 1.6 }}>
              We sent a verification link to <strong>{email}</strong>.
              Click it to activate your account.
            </p>
            <p className="auth-footer"><Link to="/login">Back to log in</Link></p>
          </>
        ) : (
          <>
            <h2>Create account</h2>
            <form onSubmit={submit} autoComplete="on">
              <label>Username</label>
              <input autoComplete="nickname" value={username} onChange={e => setUsername(e.target.value)} required placeholder="Your unique handle" />
              <label>Full Name</label>
              <input autoComplete="name" value={fullName} onChange={e => setFullName(e.target.value)} required placeholder="Your full name" />
              <label>Email</label>
              <input type="email" autoComplete="username" value={email} onChange={e => setEmail(e.target.value)} required />
              <label>Password</label>
              <input type="password" autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} required minLength={8} />
              <label>Confirm Password</label>
              <input type="password" autoComplete="new-password" value={confirm} onChange={e => setConfirm(e.target.value)} required minLength={8} />
              {error && <p className="error">{error}</p>}
              <button type="submit" className="btn-primary" disabled={loading}>
                {loading ? 'Creating…' : 'Create account'}
              </button>
            </form>
            <p className="auth-footer">Already have an account? <Link to="/login">Log in</Link></p>
          </>
        )}
      </div>
    </div>
  )
}
