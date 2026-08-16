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
 * Light is the default, deliberately, so prefers-color-scheme is NOT consulted.
 * A visitor whose laptop is set to dark still gets the light site until they
 * ask for otherwise.
 *
 * THEME_KEY has to stay in step with public/theme.js.
 */

export const THEME_KEY = 'ua-theme'

export function storedTheme() {
  try {
    return localStorage.getItem(THEME_KEY) === 'dark' ? 'dark' : 'light'
  } catch {
    // Safari in private mode throws on localStorage rather than returning null.
    return 'light'
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
    // Fire-and-forget: a signed-out or offline user still gets the theme they
    // asked for from the cache above, so a failure here is not worth surfacing.
    updateMe({ theme }).catch(() => {})
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
