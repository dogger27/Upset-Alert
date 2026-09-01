/*
 * Telling the server which phone this is, and how to push to it.
 *
 * Called after sign-in, because the row it creates is owned by a user.
 *
 * ON apns_env: THE CLIENT GUESSES AND THE SERVER CORRECTS. Which APNs host a
 * token is valid on is a property of the BUILD — a development build gets
 * `aps-environment: development` (sandbox), TestFlight and the App Store get
 * production — and that is not reliably readable at runtime. Rather than
 * inventing a fragile test, we send __DEV__ as a first guess: apns.py already
 * treats BadDeviceToken as "maybe the other host", retries once, and reports
 * `env_corrected`, which live_activity.py persists. So a wrong guess costs one
 * retry and fixes itself permanently, and no client release is needed to
 * change the answer.
 *
 * ON PERMISSION: an iOS device token does NOT require alert permission — an
 * app can register for remote notifications and receive Live Activity updates
 * while the user has declined banners. So the token is fetched regardless, and
 * a refusal is recorded rather than treated as failure.
 */

import { Platform } from 'react-native'
import * as Notifications from 'expo-notifications'
import * as Device from 'expo-device'
import Constants from 'expo-constants'
import { getInstallId } from './install'
import { registerDevice } from './api'

export async function registerThisDevice() {
  const install_id = await getInstallId()

  let permission = 'unknown'
  try {
    const existing = await Notifications.getPermissionsAsync()
    permission = existing.status
    if (existing.status !== 'granted' && existing.canAskAgain) {
      permission = (await Notifications.requestPermissionsAsync()).status
    }
  } catch (e) {
    console.warn('[device] permission check failed:', e.message)
  }

  let device_token = null
  try {
    // Deliberately attempted even when permission was refused — see above.
    const t = await Notifications.getDevicePushTokenAsync()
    device_token = typeof t === 'string' ? t : t?.data || null
  } catch (e) {
    // Expo Go and the simulator cannot produce one, and neither can a build
    // without the aps-environment entitlement. Registering WITHOUT a token is
    // still worth doing: the row exists, and a later launch fills it in.
    console.warn('[device] no push token:', e.message)
  }

  const payload = {
    install_id,
    platform: Platform.OS,
    device_token,
    apns_env: __DEV__ ? 'sandbox' : 'production',
    bundle_id: Constants.expoConfig?.ios?.bundleIdentifier || undefined,
    app_version: Constants.expoConfig?.version || undefined,
    build: String(Constants.expoConfig?.ios?.buildNumber || '') || undefined,
    os_version: Device.osVersion || undefined,
    device_model: Device.modelName || undefined,
    locale: Intl.DateTimeFormat().resolvedOptions().locale || undefined,
    time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone || undefined,
  }

  const result = await registerDevice(payload)
  return { ...result, permission, had_token: !!device_token }
}
