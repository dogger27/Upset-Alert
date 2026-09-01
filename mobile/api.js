/*
 * The API client, pointed at production.
 *
 * There is no CORS to configure and no cookie to carry: the backend is JWT
 * bearer only and nothing in it assumes a browser, which is why this file is
 * twenty lines rather than a port of the web client.
 *
 * The token lives in SecureStore rather than AsyncStorage once auth is real —
 * see the note in App.js. Kept in memory here so the first build has no native
 * dependency and runs in Expo Go unchanged.
 */

export const API = 'https://upsetalert-api.upsetalert.ca'

let token = null

export function setToken(t) { token = t }
export function getToken() { return token }

async function request(path, { method = 'GET', body, form } = {}) {
  const headers = {}
  if (token) headers.Authorization = `Bearer ${token}`

  let payload
  if (form) {
    headers['Content-Type'] = 'application/x-www-form-urlencoded'
    payload = new URLSearchParams(form).toString()
  } else if (body) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }

  const res = await fetch(`${API}${path}`, { method, headers, body: payload })
  const text = await res.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!res.ok) {
    const detail = (data && data.detail) || res.statusText
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return data
}

/* The login endpoint takes form encoding, not JSON — it is FastAPI's
   OAuth2PasswordRequestForm, and `username` is the EMAIL. */
export const login = (email, password) =>
  request('/auth/login', { method: 'POST', form: { username: email, password } })

export const getMe = () => request('/auth/me')
export const getAppConfig = () => request('/app/config')
export const getOffer = () => request('/app/live-activities/offer')
export const getScheduleDay = (playDate) =>
  request(`/schedule/day${playDate ? `?play_date=${playDate}` : ''}`)
