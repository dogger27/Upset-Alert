/*
 * Where the sign-in survives a cold launch.
 *
 * THE RULE THIS FILE EXISTS TO ENFORCE: only a 401 signs anyone out. A network
 * failure, a backend restart, a phone that woke up on a dead Wi-Fi network —
 * none of those are logout, and treating them as logout is the exact bug the
 * web app already shipped once. Tokens here are year-long and rolling, so a
 * session that looks broken is almost always a transport problem, and throwing
 * the token away turns a five-second outage into a re-authentication.
 *
 * Keychain rather than AsyncStorage, and deliberately:
 *
 *   AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY
 *
 * - AFTER_FIRST_UNLOCK, not the WHEN_UNLOCKED default, because Live Activity
 *   and push work will eventually need to read this while the screen is locked.
 *   Choosing it now costs nothing; discovering it later means a migration.
 * - THIS_DEVICE_ONLY because a bearer token is scoped to the device that got
 *   it. Without the suffix iCloud Keychain would sync it to the user's other
 *   hardware, which is a credential leaving the device for no benefit.
 *
 * Note the Keychain outlives app deletion on iOS — reinstalling the same
 * bundle id gets the old value back. That is a feature for install_id (see the
 * app_device model, whose whole design depends on it) and a mild surprise
 * here: deleting the app does NOT sign you out. clearToken() is the only thing
 * that does.
 */

import * as SecureStore from 'expo-secure-store'

const KEY = 'upsetalert.session.jwt'
const OPTS = {
  keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
}

// Historically iOS refused Keychain values much over 2 KB. Our JWT is a few
// hundred bytes, so this should never fire — which is exactly why it is worth
// saying out loud rather than silently failing to persist a session.
const MAX_BYTES = 2048

/* Every call is wrapped: the Keychain is allowed to be unavailable (a
   simulator quirk, a device in a strange state) and that must degrade to an
   in-memory session, never to a crash on launch. */

export async function saveToken(token) {
  if (!token) return false
  if (token.length > MAX_BYTES) {
    console.warn(`[session] token is ${token.length} bytes, over the ${MAX_BYTES} Keychain limit — not persisting`)
    return false
  }
  try {
    await SecureStore.setItemAsync(KEY, token, OPTS)
    return true
  } catch (e) {
    console.warn('[session] could not persist token:', e.message)
    return false
  }
}

export async function loadToken() {
  try {
    return await SecureStore.getItemAsync(KEY, OPTS)
  } catch (e) {
    console.warn('[session] could not read token:', e.message)
    return null
  }
}

export async function clearToken() {
  try {
    await SecureStore.deleteItemAsync(KEY, OPTS)
  } catch (e) {
    console.warn('[session] could not clear token:', e.message)
  }
}
