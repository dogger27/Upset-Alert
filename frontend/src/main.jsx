import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import './index.css'
import 'flag-icons/css/flag-icons.min.css'

export const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
})

/*
 * Recover from a deploy landing under an open tab.
 *
 * Asset filenames are content-hashed, so a deploy replaces them. A tab opened
 * before it still holds the old index.html in memory, and the moment it lazily
 * imports a chunk it asks for a hash that no longer exists. Cloudflare Pages
 * answers a missing path with index.html — 200, text/html — so the browser
 * reports "Expected a JavaScript-or-Wasm module script but the server responded
 * with a MIME type of text/html" and the page is stuck until it is reloaded by
 * hand. index.html itself revalidates on every navigation, so a reload is all
 * that is needed; nothing is broken but the copy this tab is holding.
 *
 * Guarded by a timestamp rather than a flag. If the reload does NOT fix it (a
 * genuinely broken deploy, an asset that really is missing), a plain flag would
 * still permit one reload per session per tab, and the failure would present as
 * a page that reloads whenever it is touched. Ten seconds is long past a real
 * recovery and far too short to loop.
 */
const RELOAD_KEY = 'ua-chunk-reload-at'
window.addEventListener('vite:preloadError', (event) => {
  const last = Number(sessionStorage.getItem(RELOAD_KEY) || 0)
  if (Date.now() - last < 10_000) return   // already tried; let the error surface
  event.preventDefault()
  sessionStorage.setItem(RELOAD_KEY, String(Date.now()))
  window.location.reload()
})

// Keep an already-granted subscriber's worker up to date, but don't install one
// for everybody: a visitor who has never enabled notifications has no use for a
// service worker, and registering it anyway is a background download plus an
// extra moving part on every page load. Enabling push registers it on demand
// (see api/push.enablePush), so this only ever refreshes an existing install.
if ('serviceWorker' in navigator && 'Notification' in window && Notification.permission === 'granted') {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {})
  })
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
)
