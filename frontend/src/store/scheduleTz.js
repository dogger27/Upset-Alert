import { create } from 'zustand'
import { updateMe } from '../api/auth'

/*
 * Which clock the schedule prints in: the reader's own, or the venue's.
 *
 * This used to be a pair of buttons above the day's matches, which put a
 * setting somebody changes once — if ever — in the busiest strip of the
 * busiest page, next to the filters they change constantly. It is a
 * PREFERENCE, so it now lives with the other preferences and the schedule
 * simply obeys it.
 *
 * MY TIME IS THE DEFAULT. "When is this on?" is a question about the reader's
 * evening, not the tournament's, and for the great majority of readers those
 * are different clocks. Venue time remains one switch away for anyone actually
 * at the tournament, or reading the sheet alongside our times.
 *
 * Stored on the ACCOUNT (users.schedule_tz) so the choice follows a reader
 * from phone to desktop; localStorage is a CACHE, exactly as with the theme,
 * because the account value is unknown until /auth/me returns and the schedule
 * must render before then without flipping clocks under the reader.
 *
 * TZ_KEY is unchanged from when this lived in Schedule.jsx, so anyone who
 * already chose venue time keeps it.
 */

export const TZ_KEY = 'ua-schedule-tz'

export function storedTz() {
  try {
    return localStorage.getItem(TZ_KEY) === 'venue' ? 'venue' : 'user'
  } catch {
    // Safari in private mode throws rather than returning null.
    return 'user'
  }
}

function cache(mode) {
  try { localStorage.setItem(TZ_KEY, mode) } catch { /* nothing to do */ }
}

export const useScheduleTz = create((set, get) => ({
  tzMode: storedTz(),

  /** The reader flipped the switch in their preferences. */
  setTzMode: (value) => {
    const mode = value === 'venue' ? 'venue' : 'user'
    cache(mode)
    set({ tzMode: mode })
    // Guests get the local cache only. The API client turns ANY 401 into
    // "clear the token and go to /login", and the interceptor runs before this
    // .catch — so for a signed-out reader the request must not be made at all,
    // the same trap the theme store documents.
    let signedIn = false
    try { signedIn = !!localStorage.getItem('token') } catch { /* private mode */ }
    if (signedIn) updateMe({ schedule_tz: mode }).catch(() => {})
  },

  /**
   * Adopt the account's choice on sign-in or first load.
   *
   * Does NOT write back: this value came FROM the server, and echoing it would
   * turn every page load into a PATCH. Null means the account has never
   * chosen, so the local cache — and therefore My time — stands.
   */
  adoptAccountTz: (value) => {
    if (value !== 'venue' && value !== 'user') return
    cache(value)
    if (get().tzMode === value) return
    set({ tzMode: value })
  },
}))
