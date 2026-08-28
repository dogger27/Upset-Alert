import { create } from 'zustand'
import { getMe, login as apiLogin, register as apiRegister, updateMe as apiUpdateMe, refreshToken } from '../api/auth'
import { AUTH_EXPIRED } from '../api/client'
import { queryClient } from '../main'
import { useTheme } from './theme'

// The server needs the reader's zone only to render deadlines in outgoing
// email, where no browser is present to do it. Take it from the browser rather
// than asking — Intl already knows, and a settings question users have to
// answer would be both friction and a worse answer. Write only on change, so
// this is a no-op on all but the first load (and after travel or a zone rename).
async function syncTimezone(user) {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone
    if (!tz || tz === user?.timezone) return user
    return await apiUpdateMe({ timezone: tz })
  } catch {
    // Never let this block sign-in: a missing zone costs a UTC-labelled email,
    // a thrown error costs the session.
    return user
  }
}

// Half of the server's year, so a token is renewed well before it can lapse
// while still leaving most opens with nothing to do.
const RENEW_BELOW_MS = 180 * 24 * 60 * 60 * 1000

/* Milliseconds left on a JWT, read from its own `exp`, or null if it cannot be
   read. Decoding here is not a security check — the server owns that — it only
   decides whether to spend a request renewing. */
function tokenLifeLeft(token) {
  try {
    const payload = JSON.parse(
      atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
    return payload?.exp ? payload.exp * 1000 - Date.now() : null
  } catch {
    return null
  }
}

export const useAuth = create((set) => ({
  user: null,
  loading: true,

  init: async () => {
    const token = localStorage.getItem('token')
    if (!token) { set({ loading: false }); return }
    let user, lastErr
    // ONLY A 401 ENDS A SESSION. This used to delete the token on ANY failure,
    // which meant a backend restart or a phone changing cells while the app
    // opened signed the reader out — the one thing that must never happen by
    // accident. A transient error now leaves the token alone and simply tries
    // again; the visibilitychange handler below re-runs init on the next
    // focus, so even an app opened during a deploy recovers by itself.
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        user = await getMe()
        break
      } catch (err) {
        lastErr = err
        if (err?.response?.status === 401) break
        await new Promise(r => setTimeout(r, attempt === 0 ? 800 : 2500))
      }
    }
    if (!user) {
      // The 401 interceptor has already cleared the token and redirected; this
      // is only for completeness. Anything else keeps the token: the session is
      // probably fine and the network was not.
      if (lastErr?.response?.status === 401) localStorage.removeItem('token')
      set({ loading: false })
      return
    }
    set({ user, loading: false })
    // Roll a half-spent token forward, so an active reader's window keeps
    // moving and the login form stays out of their way. Failure is silent by
    // design: the token they have is still valid, and this can be retried on
    // any later open.
    try {
      const left = tokenLifeLeft(localStorage.getItem('token'))
      if (left !== null && left < RENEW_BELOW_MS) {
        const { access_token } = await refreshToken()
        if (access_token) localStorage.setItem('token', access_token)
      }
    } catch { /* keep the working token */ }
    // The account's theme outranks whatever this device had cached — that is the
    // point of storing it server-side. Deliberately after the session is
    // established, so a bad theme value costs the wrong palette, not the login.
    try { useTheme.getState().adoptAccountTheme(user.theme) } catch { /* cosmetic */ }
    set({ user: await syncTimezone(user) })
  },

  login: async (email, password) => {
    const { access_token } = await apiLogin(email, password)
    localStorage.setItem('token', access_token)
    const user = await getMe()
    useTheme.getState().adoptAccountTheme(user.theme)
    queryClient.clear()
    set({ user: await syncTimezone(user) })
  },

  register: async (email, username, fullName, password) => {
    await apiRegister({ email, username, full_name: fullName, display_name: fullName, password })
  },

  updateProfile: async (data) => {
    const user = await apiUpdateMe(data)
    set({ user })
  },

  logout: () => {
    localStorage.removeItem('token')
    queryClient.clear()
    set({ user: null })
  },
}))

/*
 * Never let the app be half signed in.
 *
 * `user` lives in memory and the token lives in localStorage, and the two can
 * come apart: the 401 interceptor drops the token, and iOS can evict storage
 * while an installed app is merely suspended rather than closed — the JS heap
 * survives, the token does not. Either way the store still says "signed in", so
 * the profile menu and every gated view agree, while requests go out bare and
 * quietly return nothing. It presents as a bracket full of TBD, not as a login
 * screen, which is why it took so long to name.
 *
 * The token is the only real evidence of a session, so it decides.
 */
window.addEventListener(AUTH_EXPIRED, () => {
  useAuth.setState({ user: null, loading: false })
})

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'visible') return
  let token = null
  try { token = localStorage.getItem('token') } catch { /* private mode */ }
  const { user, init } = useAuth.getState()
  if (user && !token) {
    // Storage went away underneath a session that is still on screen.
    useAuth.setState({ user: null, loading: false })
    queryClient.clear()
  } else if (token && !user) {
    // Resumed holding a token the store has not resolved yet.
    init()
  }
})
