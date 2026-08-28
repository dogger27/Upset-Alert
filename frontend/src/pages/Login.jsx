import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../store/auth'
import { conditionalUIAvailable, passkeysSupported, signInWithPasskey } from '../api/passkeys'
import './AuthForm.css'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [passkeyBusy, setPasskeyBusy] = useState(false)
  const { login, adoptToken } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const successMessage = location.state?.message
  const hasPasskeys = passkeysSupported()
  // The conditional request stays open while the page is; the button press
  // has to cancel it first, because a browser allows only one at a time.
  const autofillAbort = useRef(null)

  /* Offer the passkey from inside the sign-in field itself, so someone with
     one never types anything: the browser shows it in the autofill sheet and
     Face ID does the rest. Entirely silent if it is unavailable, declined or
     interrupted — a password sign-in must still work exactly as before. */
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      if (!await conditionalUIAvailable()) return
      const controller = new AbortController()
      autofillAbort.current = controller
      try {
        const token = await signInWithPasskey({ conditional: true, signal: controller.signal })
        if (token && !cancelled) {
          await adoptToken(token)
          navigate('/')
        }
      } catch { /* dismissed, aborted, or unsupported — the form still works */ }
    })()
    return () => { cancelled = true; autofillAbort.current?.abort() }
  }, [adoptToken, navigate])

  const passkeySignIn = async () => {
    setError(''); setPasskeyBusy(true)
    try {
      autofillAbort.current?.abort()
      const token = await signInWithPasskey()
      if (!token) return
      await adoptToken(token)
      navigate('/')
    } catch (err) {
      // A cancelled sheet is not a failure; anything else is worth saying.
      if (err?.name !== 'NotAllowedError' && err?.name !== 'AbortError') {
        setError(err.response?.data?.detail || 'That passkey did not work.')
      }
    } finally {
      setPasskeyBusy(false)
    }
  }

  const submit = async (e) => {
    e.preventDefault()
    setError(''); setLoading(true)
    try {
      await login(email, password)
      navigate('/')
    } catch (err) {
      setError(err.response?.data?.detail || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card card">
        <h2>Log in</h2>
        {successMessage && <p style={{ color: 'var(--success, green)', marginBottom: '0.5rem' }}>{successMessage}</p>}
        <form onSubmit={submit} autoComplete="on">
          <label>Email or username</label>
          {/* NOT type="email": the browser's own validation would reject a
              username before the form could be submitted at all. */}
          <input type="text" autoComplete="username" inputMode="email"
                 autoCapitalize="none" autoCorrect="off"
                 value={email} onChange={e => setEmail(e.target.value)} required />
          <label>Password</label>
          <input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required />
          {error && <p className="error">{error}</p>}
          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? 'Logging in…' : 'Log in'}
          </button>
        </form>
        {hasPasskeys && (
          <>
            <div className="auth-or"><span>or</span></div>
            <button type="button" className="btn-secondary auth-passkey-btn"
                    onClick={passkeySignIn} disabled={passkeyBusy}>
              {passkeyBusy ? 'Waiting for your device…' : 'Sign in with a passkey'}
            </button>
          </>
        )}
        <p className="auth-footer"><Link to="/forgot-password">Forgot password?</Link></p>
        <p className="auth-footer">No account? <Link to="/register">Sign up</Link></p>
      </div>
    </div>
  )
}
