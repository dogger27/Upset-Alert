import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../store/auth'
import client from '../api/client'
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
  const [code, setCode] = useState('')
  const [codeError, setCodeError] = useState('')
  const [codeLoading, setCodeLoading] = useState(false)
  const [verified, setVerified] = useState(false)
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

  const submitCode = async (e) => {
    e.preventDefault()
    setCodeError(''); setCodeLoading(true)
    try {
      await client.post('/auth/verify-email-code', { email, code })
      setVerified(true)
    } catch (err) {
      setCodeError(err.response?.data?.detail || 'Invalid or expired code')
    } finally {
      setCodeLoading(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card card">
        {verified ? (
          <>
            <h2>Email verified!</h2>
            <p style={{ color: 'var(--text-muted)', lineHeight: 1.6 }}>
              Your account is active. You can now log in.
            </p>
            <p className="auth-footer"><Link to="/login">Log in</Link></p>
          </>
        ) : registered ? (
          <>
            <h2>Check your email</h2>
            <p style={{ color: 'var(--text-muted)', lineHeight: 1.6 }}>
              We sent a 6-digit code to <strong>{email}</strong>.
              Enter it below or click the link in the email.
            </p>
            <form onSubmit={submitCode} style={{ marginTop: '1rem' }}>
              <label>Verification code</label>
              <input
                type="text"
                inputMode="numeric"
                maxLength={6}
                pattern="\d{6}"
                placeholder="000000"
                value={code}
                onChange={e => setCode(e.target.value.replace(/\D/g, ''))}
                style={{ letterSpacing: '0.25em', fontSize: '1.5rem', textAlign: 'center' }}
                autoFocus
              />
              {codeError && <p className="error">{codeError}</p>}
              <button type="submit" className="btn-primary" disabled={codeLoading || code.length !== 6}>
                {codeLoading ? 'Verifying…' : 'Verify'}
              </button>
            </form>
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

