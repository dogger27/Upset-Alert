import axios from 'axios'

const client = axios.create({ baseURL: import.meta.env.VITE_API_URL ?? '/api' })

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Session ended server-side. Announced as an event rather than by importing the
// auth store, which would close an import cycle (store -> api -> store).
export const AUTH_EXPIRED = 'ua-auth-expired'

client.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      // Dropping the token WITHOUT telling the store left the app half signed
      // in: `user` still set, so the profile menu and every gated view claimed
      // a session, while requests went out bare. That state is invisible and
      // fails silently — an empty bracket rather than a login prompt.
      localStorage.removeItem('token')
      window.dispatchEvent(new Event(AUTH_EXPIRED))
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

export default client
