/*
 * Who is signed in, for the whole app.
 *
 * This is the launch path, lifted out of the single-screen scaffold so every
 * route can read it. The rule it exists to hold onto:
 *
 *   401            the session is genuinely dead   -> clear it, show sign-in
 *   never arrived  the network is                  -> KEEP it, offer Retry
 *
 * Showing a sign-in form for the second case invites someone to
 * re-authenticate over a problem that fixes itself, and is indistinguishable
 * to them from having been logged out. Tokens here are year-long and rolling,
 * so "looks broken" is nearly always transport.
 */

import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { getAppConfig, getMe, login, setToken, setUnauthorizedHandler } from './api'
import { clearToken, loadToken, saveToken } from './session'
import { invalidate } from './useApi'
import { registerThisDevice } from './device'
import { startLiveActivityBridge, stopLiveActivityBridge } from './liveactivity'

const Ctx = createContext(null)

/* Registering the device must never be able to break signing in.
   It needs a session (the row is owned by a user), it can fail for reasons
   that have nothing to do with auth — no entitlement, refused permission, a
   flaky network — and none of those should leave someone staring at a login
   form. So: not awaited, and it swallows its own errors. */
function announceDevice() {
  registerThisDevice().catch(e =>
    console.warn('[auth] device registration skipped:', e.message))
}

export function useAuth() {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAuth used outside AuthProvider')
  return v
}

export function AuthProvider({ children }) {
  const [phase, setPhase] = useState('boot')  // boot | signedout | unreachable | ready
  const [me, setMe] = useState(null)
  const [config, setConfig] = useState(null)
  const [error, setError] = useState('')

  // Public, so it answers before anyone signs in — the fastest way to tell
  // "the phone cannot reach the API" from "the password is wrong".
  useEffect(() => { getAppConfig().then(setConfig).catch(() => setConfig(null)) }, [])

  const boot = useCallback(async () => {
    setError('')
    const stored = await loadToken()
    if (!stored) { setPhase('signedout'); return }
    setToken(stored)
    try {
      setMe(await getMe())
      setPhase('ready')
      announceDevice()
    } catch (e) {
      if (e.status === 401) {
        await clearToken()
        setToken(null)
        setPhase('signedout')
      } else {
        setError(e.message)
        setPhase('unreachable')
      }
    }
  }, [])

  useEffect(() => { boot() }, [boot])

  const signIn = useCallback(async (email, password) => {
    const { access_token } = await login(email.trim(), password)
    setToken(access_token)
    await saveToken(access_token)
    setMe(await getMe())
    setPhase('ready')
    announceDevice()
  }, [])

  const signOut = useCallback(async () => {
    await clearToken()
    setToken(null)
    // Another account's leagues must not survive in the cache, and neither
    // must their Lock Screen.
    invalidate()
    stopLiveActivityBridge().catch(() => {})
    setMe(null)
    setPhase('signedout')
  }, [])

  // Held in a ref so the handler registered once below always calls the
  // current signOut, without re-registering on every render.
  const signOutRef = useRef(signOut)
  signOutRef.current = signOut

  // A token that expires mid-session must land people on sign-in, not on a
  // screen showing an error they cannot act on. Registered once, above the
  // navigator, so no screen has to handle it.
  useEffect(() => {
    setUnauthorizedHandler(() => { signOutRef.current?.() })
    return () => setUnauthorizedHandler(null)
  }, [])

  // The Live Activity bridge needs BOTH a session (its tokens belong to a
  // user) and the config (for content_state_version). An effect keyed on both
  // starts it exactly when they are available, and re-runs harmlessly —
  // startLiveActivityBridge() is idempotent. Fire-and-forget, like everything
  // else here: a phone that cannot do Live Activities must still sign in.
  useEffect(() => {
    if (phase !== 'ready') return
    startLiveActivityBridge(config?.content_state_version ?? 1)
      .then(r => { if (!r.ok) console.log('[LA] not started:', r.note) })
      .catch(e => console.warn('[LA] bridge failed:', e.message))
  }, [phase, config])

  return (
    <Ctx.Provider value={{ phase, me, config, error, signIn, signOut, retry: boot }}>
      {children}
    </Ctx.Provider>
  )
}
