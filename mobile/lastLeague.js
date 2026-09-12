/*
 * Which league the Leagues tab opens.
 *
 * The tab used to open a LIST, which is a menu standing in front of the thing
 * people came for — and for most accounts it is a list of one or two. So the
 * tab goes straight to the league last read, and the league's own name at the
 * top is the control that changes it (leaguePicker).
 *
 * An external store rather than context, for the same reason as currentDraw:
 * the READER is the tab layout, which sits above every screen that could set
 * this.
 *
 * PERSISTED, unlike currentDraw. A draw id goes stale in weeks — reopening a
 * tournament that finished in March would be worse than asking — but a league
 * is the same league next season, so a cold start should still land where the
 * reader left off rather than on the list they asked not to see.
 *
 * SecureStore is the only key/value store this app already carries (the token
 * and the install id live there). A league id is not a secret, but adding
 * AsyncStorage for one integer would mean a native rebuild, and the keychain
 * holds an integer perfectly well.
 */
import { useSyncExternalStore } from 'react'
import { Platform } from 'react-native'
import * as SecureStore from 'expo-secure-store'

const KEY = 'upsetalert.lastLeague'
// Readable after first unlock and never synced to another device: the same
// terms the install id uses. A league id is not worth a passcode prompt.
const OPTS = { keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY }

/* A league id, or the string 'global' — the Global table is selectable in the
   picker and is therefore a league the tab can reopen. Kept as a STRING for
   that reason; it goes into a route either way. */
let current = null
// Until the read comes back, "no remembered league" and "not asked yet" look
// identical, and the difference decides whether the tab redirects or shows the
// list. The tab must not flash the list on every cold start.
let loaded = false
const subscribers = new Set()

function publish() {
  subscribers.forEach(fn => fn())
}

/* expo-secure-store ships `export default {}` for WEB, so getItemAsync there
   is not a function — a call at import time would throw before any screen
   mounted and take the whole bundle with it. session.js met this first; the
   same two-store shape, for the same reason: web is the prerender and the
   visual-diff harness, not a shipping target. */
const isWeb = Platform.OS === 'web'
const webStore = () => { try { return globalThis.localStorage ?? null } catch { return null } }

async function read() {
  if (isWeb) return webStore()?.getItem(KEY) ?? null
  return SecureStore.getItemAsync(KEY, OPTS)
}

async function write(value) {
  if (isWeb) { webStore()?.setItem(KEY, value); return }
  await SecureStore.setItemAsync(KEY, value, OPTS)
}

/* One read per launch, kicked off at import so the answer is usually already
   there by the first tab press. A store that refuses to answer (a locked
   device, a simulator quirk, a browser with storage off) leaves `current`
   null and the tab falls back to the list — the pre-existing behaviour, which
   is a correct answer rather than a broken screen. */
read()
  .then(v => { if (valid(v)) current = v })
  .catch(() => {})
  .finally(() => { loaded = true; publish() })

/* 'global' or digits. Anything else is not a route this can reopen, and a
   stored junk value would send the tab to a 404 on every launch. */
const valid = v => v != null && /^(global|\d+)$/.test(String(v))

/** Called by the league screen for the league it is showing. */
export function setLastLeague(id) {
  const next = id == null ? null : String(id)
  if (!valid(next) || next === current) return
  current = next
  publish()
  // Fire and forget: the store is a convenience, and a write that fails must
  // not break the screen that reported the league.
  write(next).catch(() => {})
}

/** `{ id, loaded }` — see `loaded` above; do not redirect until it is true. */
export function useLastLeague() {
  const snap = useSyncExternalStore(
    fn => { subscribers.add(fn); return () => subscribers.delete(fn) },
    () => `${current}|${loaded}`,
    () => `${current}|${loaded}`,
  )
  const [id, ok] = snap.split('|')
  return { id: id === 'null' ? null : id, loaded: ok === 'true' }
}
