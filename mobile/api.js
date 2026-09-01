/*
 * The API client, pointed at production.
 *
 * There is no CORS to configure and no cookie to carry: the backend is JWT
 * bearer only and nothing in it assumes a browser, which is why this file is
 * short rather than a port of the web client.
 *
 * The one thing it must get right is TELLING FAILURES APART. "The server said
 * no" and "the request never arrived" look identical to a caller that only
 * receives a message string, and conflating them is how an app signs someone
 * out because their train went into a tunnel. So every error carries:
 *
 *   err.status   the HTTP status, or 0 when the request never completed
 *   err.offline  true when fetch itself threw — DNS, no route, timeout
 *
 * Only status === 401 may end a session. See session.js.
 */

export const API = 'https://upsetalert-api.upsetalert.ca'

let token = null

export function setToken(t) { token = t }
export function getToken() { return token }

function fail(message, { status = 0, offline = false } = {}) {
  const e = new Error(message)
  e.status = status
  e.offline = offline
  return e
}

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

  let res
  try {
    res = await fetch(`${API}${path}`, { method, headers, body: payload })
  } catch (e) {
    // fetch only throws for transport failures; an HTTP error is a resolved
    // promise. So everything landing here is "never reached the server".
    throw fail(e.message || 'Network request failed', { offline: true })
  }

  const text = await res.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }

  if (!res.ok) {
    const detail = (data && data.detail) || res.statusText
    throw fail(typeof detail === 'string' ? detail : JSON.stringify(detail),
               { status: res.status })
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

/* Leagues.
   round-scores is the one worth a note: it is untyped in the OpenAPI spec
   (it returns a plain dict), and its real shape is

     { entries: [{user_id, username, full_name, round_points[], total,
                  correct_count}],
       completed_matches_count, rounds_with_matches[], completed_round_nums[],
       matches_timeline[], user_predictions{} }

   entries arrive ALREADY SORTED by the server: total desc, then points in the
   latest rounds first (Final -> SF -> QF -> ...). Do not re-sort them on the
   client — the tiebreak is lexicographic over the round vector, not a weighted
   sum, and a client-side sort would quietly disagree with the website. */
export const getLeagues = () => request('/leagues')
export const getLeague = (id) => request(`/leagues/${id}`)
export const getLeagueTournaments = (id) => request(`/leagues/${id}/tournaments`)
export const getRoundScores = (leagueId, tournamentId) =>
  request(`/leagues/${leagueId}/round-scores?tournament_id=${tournamentId}`)
