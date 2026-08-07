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

self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))

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
  const options = {
    body: data.body || '',
    icon: '/icon-512.png',
    badge: '/favicon-192x192.png',
    tag: data.tag || 'upset-alert',
    // Replace an older notification carrying the same tag rather than stacking,
    // but still alert — a silent replace can go unnoticed entirely.
    renotify: true,
    data: { url: data.url || '/' },
  }
  event.waitUntil(self.registration.showNotification(title, options))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = (event.notification.data && event.notification.data.url) || '/'

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
