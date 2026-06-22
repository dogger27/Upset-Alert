import { useState } from 'react'
import { Link } from 'react-router-dom'
import client from '../api/client'
import './AuthForm.css'

export default function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [loading, setLoading] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setLoading(true)
    try {
      await client.post('/auth/forgot-password', { email })
    } catch {
      // Swallow errors — don't leak whether email exists
    } finally {
      setLoading(false)
      setSubmitted(true)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card card">
        <h2>Forgot password</h2>
        {submitted ? (
          <>
            <p style={{ color: 'var(--text-muted)', lineHeight: 1.6 }}>
              If that email is registered, you'll receive a reset link shortly.
            </p>
            <p className="auth-footer"><Link to="/login">Back to log in</Link></p>
          </>
        ) : (
          <form onSubmit={submit}>
            <label>Email</label>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="you@example.com"
              required
            />
            <button type="submit" className="btn-primary" disabled={loading}>
              {loading ? 'Sending…' : 'Send reset link'}
            </button>
            <p className="auth-footer"><Link to="/login">Back to log in</Link></p>
          </form>
        )}
      </div>
    </div>
  )
}
