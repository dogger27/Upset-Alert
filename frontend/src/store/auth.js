import { create } from 'zustand'
import { getMe, login as apiLogin, register as apiRegister, updateMe as apiUpdateMe } from '../api/auth'
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

export const useAuth = create((set) => ({
  user: null,
  loading: true,

  init: async () => {
    const token = localStorage.getItem('token')
    if (!token) { set({ loading: false }); return }
    let user
    try {
      user = await getMe()
    } catch {
      // ONLY getMe() belongs in here. This catch deletes the token, so anything
      // else inside it can silently sign the user out over an unrelated error —
      // and a signed-out session on a page that still looks signed in fails in
      // confusing ways (empty picks, nothing selected) rather than obviously.
      localStorage.removeItem('token')
      set({ loading: false })
      return
    }
    set({ user, loading: false })
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
