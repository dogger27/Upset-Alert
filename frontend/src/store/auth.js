import { create } from 'zustand'
import { getMe, login as apiLogin, register as apiRegister, updateMe as apiUpdateMe } from '../api/auth'
import { queryClient } from '../main'

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
    queryClient.clear()
    set({ user })
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
