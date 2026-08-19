/*
 * Push-only service worker.
 *
 * There is deliberately NO fetch handler here. A service worker is required by
 * the Push API, but the moment one intercepts fetches it becomes a cache layer
 * in front of a live SPA, and the classic failure is serving yesterday's JS
 * after a deploy. This worker never touches navigation or assets — it exists
 * solely to receive pushes and open the right page when one is tapped.
 *
 * skipWaiting + clients.claim so a new version takes over immediately rather
 * than waiting for every tab to close; with no caching there is nothing for an
 * abrupt handover to break.
 */

// Bump to force every installed app onto the current build. See below.
const SW_VERSION = '2026-08-19.29'

self.addEventListener('install', () => self.skipWaiting())

/*
 * On update, re-navigate every open window.
 *
 * An installed PWA launches from a home-screen snapshot rather than a fresh
 * navigation, so it can keep serving an index.html — and therefore a JS bundle —
 * from days ago, straight through any number of deploys. The app works; it is
 * simply not the app that shipped, and every fix looks like it never landed.
 *
 * The page cannot fix this by itself: any check we ship lives in the new bundle,
 * which the stale client is precisely the one never to load. This worker is the
 * only piece that updates independently — /sw.js is not content-hashed and
 * revalidates on every launch — so it is the one thing that can reach a client
 * already stuck, and WindowClient.navigate() needs no cooperation from the page.
 *
 * Only on an UPDATE, never a first install: clients controlled by the previous
 * worker are collected before claim(), which returns nothing on a first run, so
 * a new visitor is not bounced immediately after loading. Activation happens
 * once per worker version, so this cannot loop — it fires only when the bytes of
 * this file change.
 */
self.addEventListener('activate', (event) => event.waitUntil((async () => {
  const previouslyControlled = await self.clients.matchAll({ type: 'window' })
  await self.clients.claim()
  if (previouslyControlled.length === 0) return   // first install, nothing stale
  for (const client of previouslyControlled) {
    try { await client.navigate(client.url) } catch { /* client went away */ }
  }
})()))

self.addEventListener('push', (event) => {
  // A push with no/undecodable payload still has to show something: browsers
  // revoke the push permission of an app that receives a push and displays no
  // notification (the "userVisibleOnly" contract).
  let data = {}
  try {
    data = event.data ? event.data.json() : {}
  } catch (e) {
    data = {}
  }

  const title = data.title || 'Upset Alert'
  const actions = (data.actions || []).slice(0, 2) // most platforms show 2
  const options = {
    body: data.body || '',
    icon: '/icon-512.png',
    badge: '/favicon-192x192.png',
    tag: data.tag || 'upset-alert',
    // Replace an older notification carrying the same tag rather than stacking,
    // but still alert — a silent replace can go unnoticed entirely.
    renotify: true,
    // The multi-line detail in body is only visible once expanded, so ask the
    // OS to keep the notification around long enough to be pressed and held.
    requireInteraction: false,
    actions: actions.map((a) => ({ action: a.action, title: a.title })),
    // Per-action URLs travel alongside, since notificationclick only receives
    // the action id.
    data: {
      url: data.url || '/',
      actionUrls: actions.reduce((m, a) => ({ ...m, [a.action]: a.url || data.url || '/' }), {}),
    },
  }
  // If showNotification rejects, nothing appears and nothing is recorded — the
  // push looks delivered from the server's side and simply vanishes. Retry
  // stripped down to the fields every platform supports, because the usual
  // cause is one option the OS's notification centre won't take (macOS ignores
  // action buttons entirely, for instance) rather than the notification itself
  // being unwelcome.
  event.waitUntil(
    self.registration.showNotification(title, options).catch(() =>
      self.registration.showNotification(title, {
        body: options.body,
        icon: '/icon-512.png',
        tag: options.tag,
        data: options.data,
      })
    )
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const d = event.notification.data || {}
  // An action button carries its own destination; tapping the body falls back
  // to the notification's own url.
  const target =
    (event.action && d.actionUrls && d.actionUrls[event.action]) || d.url || '/'

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      // Reuse an already-open window where possible — the same reasoning as the
      // manifest's launch_handler "navigate-existing": tapping several
      // notifications should not leave a stack of duplicate windows.
      for (const client of clientList) {
        if ('focus' in client) {
          if ('navigate' in client) {
            return client.navigate(target).then((c) => (c || client).focus())
          }
          return client.focus()
        }
      }
      return self.clients.openWindow(target)
    })
  )
})
