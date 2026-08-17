import { create } from 'zustand'
import { updateMe } from '../api/auth'

/*
 * Which theme the site paints in.
 *
 * Stored on the ACCOUNT, so the choice follows the person across desktop,
 * mobile browser and the installed app rather than being re-made on each one.
 * localStorage is kept as well, but only as a cache: it is what the boot script
 * in public/theme.js reads to paint before the first frame, since the account's
 * value cannot be known until /auth/me comes back. Server wins on load, and
 * every change writes through to both.
 *
 * Dark is the default, deliberately, so prefers-color-scheme is NOT consulted.
 * A visitor whose laptop is set to light still gets the dark site until they
 * ask for otherwise — only an explicit choice of light wins.
 *
 * THEME_KEY has to stay in step with public/theme.js.
 */

export const THEME_KEY = 'ua-theme'

export function storedTheme() {
  try {
    return localStorage.getItem(THEME_KEY) === 'light' ? 'light' : 'dark'
  } catch {
    // Safari in private mode throws on localStorage rather than returning null.
    return 'dark'
  }
}

function paint(theme) {
  document.documentElement.setAttribute('data-theme', theme)
}

function cache(theme) {
  try { localStorage.setItem(THEME_KEY, theme) } catch { /* nothing to do */ }
}

// Re-assert what the boot script should already have done. A no-op when it ran,
// and the difference between "a brief flash" and "the theme silently does not
// apply" when it did not — which is how this shipped broken once, blocked by
// the CSP as an inline script.
paint(storedTheme())

export const useTheme = create((set, get) => ({
  theme: storedTheme(),

  /** The user flipped the switch. */
  setTheme: (value) => {
    const theme = value === 'dark' ? 'dark' : 'light'
    paint(theme)
    cache(theme)
    set({ theme })
    // Only when signed in. The API client turns ANY 401 into "clear the token
    // and go to /login", so firing this as a guest would throw a visitor off
    // the page they were reading for toggling dark mode. The catch cannot stop
    // that — the interceptor runs first — so the request must not be made.
    let signedIn = false
    try { signedIn = !!localStorage.getItem('token') } catch { /* private mode */ }
    if (signedIn) updateMe({ theme }).catch(() => {})
  },

  toggleTheme: () => get().setTheme(get().theme === 'dark' ? 'light' : 'dark'),

  /**
   * Adopt the theme stored on the account, on sign-in or first load.
   *
   * Deliberately does NOT write back — this value came FROM the server, and
   * echoing it would turn every page load into a PATCH. A null/absent value
   * means the account has never chosen, so whatever is cached locally stands.
   */
  adoptAccountTheme: (value) => {
    if (value !== 'light' && value !== 'dark') return
    cache(value)
    if (get().theme === value) return
    paint(value)
    set({ theme: value })
  },
}))
