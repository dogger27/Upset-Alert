import client from './client'

/*
 * Web Push enrolment.
 *
 * iOS is the constraint that shapes all of this: Safari only exposes the Push
 * API to a web app launched from the Home Screen, never to a Safari tab, and
 * only from iOS 16.4. So "unsupported" here usually means "not installed yet"
 * rather than "your browser can't" — isPushSupported() and needsInstall() are
 * separate so the UI can say which.
 */

export const isPushSupported = () =>
  'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window

// True on an iOS browser that would support push, but only once installed.
export const needsInstall = () => {
  const iOS = /iPad|iPhone|iPod/.test(navigator.userAgent)
  const standalone =
    window.navigator.standalone === true ||
    window.matchMedia('(display-mode: standalone)').matches
  return iOS && !standalone
}

// VAPID keys travel as base64url; PushManager wants raw bytes.
function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = window.atob(base64)
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)))
}

export async function getRegistration() {
  if (!isPushSupported()) return null
  return navigator.serviceWorker.register('/sw.js')
}

export async function getPushStatus() {
  const { data } = await client.get('/push/status')
  return data
}

/**
 * Ask for permission, subscribe, and register the channel with the backend.
 * Must be called from a user gesture — iOS and Chrome both reject a permission
 * request that isn't tied to a click.
 */
export async function enablePush() {
  if (!isPushSupported()) throw new Error('unsupported')

  const { data } = await client.get('/push/public-key')
  if (!data.public_key) throw new Error('not-configured')

  const permission = await Notification.requestPermission()
  if (permission !== 'granted') throw new Error(permission) // 'denied' | 'default'

  const reg = await navigator.serviceWorker.register('/sw.js')
  await navigator.serviceWorker.ready

  // An existing subscription is reused rather than replaced: its endpoint is
  // already the row's unique key server-side, so re-posting it just refreshes.
  const sub =
    (await reg.pushManager.getSubscription()) ||
    (await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(data.public_key),
    }))

  const json = sub.toJSON()
  await client.post('/push/subscribe', {
    endpoint: json.endpoint,
    keys: { p256dh: json.keys.p256dh, auth: json.keys.auth },
  })
  return true
}

/** Fire a notification at this account's own devices. Returns {devices, delivered}. */
export async function sendTestPush() {
  const { data } = await client.post('/push/test')
  return data
}

/**
 * Replay the most recent real notification of one type to this account's
 * devices. Returns {devices, delivered, title}.
 */
export async function sendTypedTestPush(prefKey) {
  const { data } = await client.post(`/push/test/${prefKey}`)
  return data
}

export async function disablePush() {
  let endpoint = null
  if (isPushSupported()) {
    const reg = await navigator.serviceWorker.getRegistration()
    const sub = reg && (await reg.pushManager.getSubscription())
    if (sub) {
      endpoint = sub.endpoint
      await sub.unsubscribe()
    }
  }
  // Endpoint-less call clears every device, which is the right fallback when
  // the local subscription is already gone but the server row isn't.
  await client.post('/push/unsubscribe', { endpoint })
}
