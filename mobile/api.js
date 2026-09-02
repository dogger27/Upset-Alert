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

/* Production by default. Expo inlines any EXPO_PUBLIC_* variable at build
   time, so this stays a plain constant in the bundle rather than a runtime
   lookup. The override exists for the web export the visual-diff harness
   renders (pointed at a local backend) and, later, for aiming a build at
   staging without editing this file. */
export const API = process.env.EXPO_PUBLIC_API_URL || 'https://upsetalert-api.upsetalert.ca'

let token = null
let onUnauthorized = null

export function setToken(t) { token = t }
export function getToken() { return token }

/* Called when a request that CARRIED A TOKEN comes back 401 — i.e. the session
   really has expired mid-use. Deliberately not fired for a 401 on a request
   with no token: signing in with the wrong password is also a 401, and routing
   that through "your session ended" would be nonsense. */
export function setUnauthorizedHandler(fn) { onUnauthorized = fn }

function fail(message, { status = 0, offline = false } = {}) {
  const e = new Error(message)
  e.status = status
  e.offline = offline
  return e
}

async function request(path, { method = 'GET', body, form } = {}) {
  const headers = {}
  const sent = !!token
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
    if (res.status === 401 && sent && onUnauthorized) onUnauthorized()
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

/* Sign-up, as the site does it: create the account, then confirm the
   six-digit code from the email, then log in — login refuses an unverified
   address, so the code step is not optional. */
export const register = (body) => request('/auth/register', { method: 'POST', body })
export const verifyEmailCode = (email, code) =>
  request('/auth/verify-email-code', { method: 'POST', body: { email, code } })
/* The About page's contact form — same route, same fields. */
export const sendContact = (body) => request('/contact', { method: 'POST', body })
export const forgotPassword = (email) =>
  request('/auth/forgot-password', { method: 'POST', body: { email } })

export const getMe = () => request('/auth/me')
/* Account preferences. schedule_tz ('venue' | 'user') lives HERE, not in
   device storage, so it follows the reader from phone to desktop — the site's
   own note on the subject. */
export const updateMe = (data) => request('/auth/me', { method: 'PATCH', body: data })

/* The site's account actions, same endpoints.
   - Notification preferences are one list of enabled keys: an email key is
     the bare name ("round_standings"), its push twin is "push_" + name.
   - Password change re-checks the current one server-side.
   - Deleting an account is irreversible and REQUIRED in-app by App Store
     guideline 5.1.1(v) wherever an account can be created; it re-checks the
     password because a year-long session is not enough on its own. */
export const getNotificationPrefs = () => request('/auth/me/notifications')
export const setNotificationPrefs = (enabledKeys) =>
  request('/auth/me/notifications', { method: 'PUT', body: { enabled_keys: enabledKeys } })
export const changePassword = (currentPassword, newPassword) =>
  request('/auth/me/password', { method: 'PATCH', body: { current_password: currentPassword, new_password: newPassword } })
export const deleteAccount = (currentPassword) =>
  request('/auth/me', { method: 'DELETE', body: { current_password: currentPassword } })
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

/* The site's league actions, same payloads. Create is private and classic
   scoring by default — the site offers no other mode from the form. Join
   takes the code as a query param, uppercased by the caller. */
export const createLeague = (name, showRealName) =>
  request('/leagues', { method: 'POST', body: { name, scoring_mode: 'classic', is_public: false, show_real_name: !!showRealName } })
export const joinLeague = (inviteCode) =>
  request(`/leagues/join?invite_code=${encodeURIComponent(inviteCode)}`, { method: 'POST' })
export const shareLeagueByEmail = (leagueId, emails) =>
  request(`/leagues/${leagueId}/share-email`, { method: 'POST', body: { emails } })

/* Someone else's record. Returns { username, entries }; the caller's own
   record comes from getMyDrawHistory and has no username on it. */
export const getUserDrawHistory = (userId) => request(`/auth/users/${userId}/draw-history`)
export const getRoundScores = (leagueId, tournamentId) =>
  request(`/leagues/${leagueId}/round-scores?tournament_id=${tournamentId}`)

/* One draw's bracket, and this user's picks in it.
   DrawOut is { tournament, draw_entries[], matches[], lock_mode, draw_locked,
   lock_reason, predictions_hidden }. A MatchOut carries player1/player2/winner
   as DrawEntryOut (or null — an unplayed slot), plus round_number, round_name,
   is_bye, status and scores. */
export const getDraw = (tournamentId) => request(`/tournaments/${tournamentId}/draw`)
export const getPredictions = (tournamentId) => request(`/predictions/${tournamentId}`)

/* Device registration. install_id is the identity, not device_token — see
   install.js for why keying on the token duplicates rows. */
export const registerDevice = (body) =>
  request('/app/devices', { method: 'POST', body })

/* Live Activities.
   push-to-start: one token per install, lets the SERVER begin an activity the
   user never opened the app for — which is the point, since the match worth
   watching at 2am is the one nobody is holding their phone for.
   The per-activity token is re-posted every time ActivityKit reissues it; the
   endpoint upserts on (device, activity_id) for exactly that reason. */
export const registerPushToStart = (install_id, attributes_type, token) =>
  request('/app/devices/push-to-start', {
    method: 'POST', body: { install_id, attributes_type, token },
  })

export const registerActivity = (body) =>
  request('/app/live-activities', { method: 'POST', body })

/* Dashboard.
   entry-status returns {tournament_id: 'complete' | 'partial'} and ONLY for
   draws with at least one pick — absent means not entered, which is a third
   state the UI has to show, not a missing value to default away. */
export const listTournaments = () => request('/tournaments')
export const getEntryStatus = () => request('/predictions/entry-status')

/* Head-to-head between two Tennis Explorer slugs. The BACKEND caches this
   (shared table, weekly TTL) because the underlying source is a scrape and can
   be slow — so there is no client cache beyond useApi's, and no retry storm to
   design around. Slugs come off draw_entries.te_slug, which is null when a
   player never matched a TE profile; the caller must not offer H2H then. */
export const getH2H = (p1, p2) =>
  request(`/h2h?p1=${encodeURIComponent(p1)}&p2=${encodeURIComponent(p2)}`)

/* Who called a finished match right, and who didn't. With no league_id this is
   every PARTICIPANT in the draw — someone with at least one pick — which is the
   same bar the standings use. Only completed non-bye matches answer. */
export const getPredictors = (tournamentId, matchId, leagueId) =>
  request(`/tournaments/${tournamentId}/matches/${matchId}/predictors` +
          (leagueId ? `?league_id=${leagueId}` : ''))

/* Your record across every draw you competed in. Persisted for everyone, but
   the endpoint filters to draws you actually entered — see the draw-history
   note: a draw you never picked in is not a result you placed last in. */
export const getMyDrawHistory = () => request('/auth/me/draw-history')

/* Best single-draw performances, grouped by TIER and then split men/women —
   the two are separate competitions and a combined table would rank a 128-draw
   Slam against a 32-draw 250. */
export const getHallOfFame = () => request('/tournaments/hall-of-fame')

/* Reconciliation. The server's view of what is running drifts from the
   device's — the app is killed without calling DELETE, a user swipes an
   activity away, a new build replaces the one that owned it — and this is the
   only thing that puts them back in step. */
export const listActivities = () => request('/app/live-activities')
export const endActivity = (activityId) =>
  request(`/app/live-activities/${encodeURIComponent(activityId)}`, { method: 'DELETE' })

/* Schedule.
   An entry is one line of the order of play. Its shape is worth knowing:
     players     [{side:'a'|'b', position, name, entry_name, seed, ...}]
                 `name` is the SHEET's format — surname in caps — and
                 `entry_name` is proper case. Prefer entry_name; fall back.
     live_point  the richer feed: has the current POINT. Use it when present.
     live_scores games only, no point — ESPN cannot supply one.
     scores      the final, once completed.
     winner_side 0 = side a, 1 = side b. */
/* Scoped to one tournament when arriving from its card, so the landing-day
   rule below picks from THAT event's sheets. open_counts rides along. */
export const getScheduleDates = (tournamentId) =>
  request(`/schedule/dates${tournamentId ? `?tournament_id=${tournamentId}` : ''}`)

/* One draw's standings. Public — no auth — and the shape is
   {rank, user, total_points, correct_count, has_upset_pick}. Used on the
   dashboard to answer "where am I" without opening the draw. */
export const getDrawStandings = (tournamentId) =>
  request(`/tournaments/${tournamentId}/standings`)
