import { create } from 'zustand'
import { getMe, login as apiLogin, register as apiRegister } from '../api/auth'

export const useAuth = create((set) => ({
  user: null,
  loading: true,

  init: async () => {
    const token = localStorage.getItem('token')
    if (!token) { set({ loading: false }); return }
    try {
      const user = await getMe()
      set({ user, loading: false })
    } catch {
      localStorage.removeItem('token')
      set({ loading: false })
    }
  },

  login: async (email, password) => {
    const { access_token } = await apiLogin(email, password)
    localStorage.setItem('token', access_token)
    const user = await getMe()
    set({ user })
  },

  register: async (email, displayName, password) => {
    await apiRegister({ email, display_name: displayName, password })
  },

  logout: () => {
    localStorage.removeItem('token')
    set({ user: null })
  },
}))
