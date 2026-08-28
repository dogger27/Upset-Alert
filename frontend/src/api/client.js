import axios from 'axios'

/* A REQUEST THAT NEVER SETTLES IS WORSE THAN ONE THAT FAILS.
   axios defaults to timeout: 0 — no timeout at all — so a socket that stalls on
   a phone's connection leaves the promise pending for as long as the page is
   open. React Query only retries on a REJECTION, so nothing retried and nothing
   errored: the draw page sat on "Loading draw…" indefinitely while the API was
   answering every other caller in about a tenth of a second. A reload appeared
   to "fix" it, which is the signature of this rather than of a server fault.
   Twenty seconds is far beyond any real response here and short enough that the
   retry happens while someone is still looking at the screen. Anything that
   genuinely runs long passes its own timeout — see LONG_MS. */
const client = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? '/api',
  timeout: 20_000,
})

/* For calls that do real work server-side — a scrape, a full resync — where
   waiting IS the expected behaviour and 20s would cut off a healthy request. */
export const LONG_MS = 180_000

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

/* NEVER PROBE /assets/<hash>.js TO VERIFY A DEPLOY.
   Mid-deploy, Cloudflare Pages answers an asset that has not landed yet with
   the SPA's index.html and a 200 — and _headers lets that response be cached
   under the asset's URL, so a verification request can leave every visitor on
   that edge downloading HTML where the bundle should be. It happened on
   2026-08-28 and took a rebuild to clear, because the cached copy carried a
   24-hour max-age and there is no purge token on this box.
   Verify with a UNIQUE QUERY STRING (`?cb=$RANDOM`), which caches under its own
   key and cannot poison the real one. */
export default client
