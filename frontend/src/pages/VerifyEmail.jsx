import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import client from '../api/client'
import './AuthForm.css'

export default function VerifyEmail() {
  const [params] = useSearchParams()
  const token = params.get('token') || ''
  const [status, setStatus] = useState('verifying') // verifying | success | error

  useEffect(() => {
    if (!token) { setStatus('error'); return }
    client.get(`/auth/verify-email?token=${encodeURIComponent(token)}`)
      .then(() => setStatus('success'))
      .catch(() => setStatus('error'))
  }, [token])

  return (
    <div className="auth-page">
      <div className="auth-card card">
        {status === 'verifying' && (
          <p style={{ color: 'var(--text-muted)' }}>Verifying your email…</p>
        )}
        {status === 'success' && (
          <>
            <h2>Email verified!</h2>
            <p style={{ color: 'var(--text-muted)', lineHeight: 1.6 }}>
              Your account is active. You can now log in.
            </p>
            <p className="auth-footer"><Link to="/login">Log in</Link></p>
          </>
        )}
        {status === 'error' && (
          <>
            <h2>Link invalid or expired</h2>
            <p style={{ color: 'var(--text-muted)', lineHeight: 1.6 }}>
              Verification links expire after 24 hours.
            </p>
            <p className="auth-footer">
              <Link to="/register">Sign up again</Link>
            </p>
          </>
        )}
      </div>
    </div>
  )
}
