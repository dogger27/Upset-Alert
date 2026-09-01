/*
 * This installation's stable identity.
 *
 * A UUID minted once and kept in the Keychain, sent as `install_id`. It is the
 * identity the server keys devices on, NOT the APNs device token — and that
 * distinction is the whole point.
 *
 * A device token is not stable. It changes on reinstall, on restore from
 * backup, and occasionally for reasons Apple does not explain. Keying on it
 * means one phone silently becomes two rows, and the same person gets every
 * notification twice. The web app already shipped that bug once, de-duplicating
 * on User-Agent, which its own docstring records.
 *
 * The Keychain is the right home precisely because it SURVIVES APP DELETION on
 * iOS. Reinstalling the app gets the same install_id back, so the reinstall
 * that mints a brand-new device token still lands on the existing row and
 * updates it, rather than creating a duplicate.
 */

import * as SecureStore from 'expo-secure-store'
import * as Crypto from 'expo-crypto'

const KEY = 'upsetalert.install.id'
// AFTER_FIRST_UNLOCK so background work can read it while the screen is
// locked; THIS_DEVICE_ONLY because an install id that synced to the user's
// other hardware would defeat its purpose — it identifies THIS installation.
const OPTS = { keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY }

let cached = null

export async function getInstallId() {
  if (cached) return cached
  try {
    let id = await SecureStore.getItemAsync(KEY, OPTS)
    if (!id) {
      id = Crypto.randomUUID()
      await SecureStore.setItemAsync(KEY, id, OPTS)
    }
    cached = id
    return id
  } catch (e) {
    // A Keychain that will not answer must not break the app. An in-memory id
    // means this session registers as a new device and is forgotten on
    // restart — degraded, but working, and honest about it.
    console.warn('[install] keychain unavailable, using a session-only id:', e.message)
    cached = cached || Crypto.randomUUID()
    return cached
  }
}
