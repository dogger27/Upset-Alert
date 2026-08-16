import { create } from 'zustand'

/*
 * Which theme the site paints in.
 *
 * Stored per device rather than on the account: it answers "what is this
 * screen like right now", not "who am I". The same person wants dark on a phone
 * in bed and light on a desk, and a server round-trip would also mean the first
 * paint after every sign-in was the wrong colour.
 *
 * Light is the default, deliberately, so prefers-color-scheme is NOT consulted.
 * A visitor whose laptop is set to dark still gets the light site until they
 * ask for otherwise.
 *
 * The attribute is applied by an inline script in index.html before first
 * paint; this store is the same decision expressed for React. THEME_KEY and the
 * value it reads have to stay in step with that script.
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

export const useTheme = create((set, get) => ({
  theme: storedTheme(),

  setTheme: (value) => {
    const theme = value === 'dark' ? 'dark' : 'light'
    paint(theme)
    try { localStorage.setItem(THEME_KEY, theme) } catch { /* nothing to do */ }
    set({ theme })
  },

  toggleTheme: () => get().setTheme(get().theme === 'dark' ? 'light' : 'dark'),
}))
