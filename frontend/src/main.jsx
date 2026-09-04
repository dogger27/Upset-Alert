import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
/* BEFORE App, DELIBERATELY, and this is the whole reason it lives here.
   BracketView.css holds the shared draw/schedule vocabulary —
   .in-progress-badge and its variants, .pos-badge, .upset-tooltip*,
   .h2h-strip, .match-box — which pages then override with plain single-class
   selectors of EQUAL specificity (.sched-status positions that badge on a
   schedule row, .sched-status--done recolours it). Equal specificity means
   the later rule wins, so this must be emitted BEFORE any page stylesheet,
   and Rollup emits CSS in module-evaluation order: everything App pulls in
   is evaluated before the entry's own later imports, which is why
   `import './index.css'` below lands last and cannot host this.

   It was ordered correctly by accident until 2026-09-04 — BracketView.jsx
   imported it, and that component sat earlier in the graph than the pages.
   Switching Live Draw off moved the import to a page, it landed after
   Schedule.css, and the schedule's "In progress" pill jumped to the top
   centre of the card at full width, wearing .in-progress-badge's own
   left:50% and transform. */
import './components/BracketView.css'
import App from './App'
import './index.css'
import 'flag-icons/css/flag-icons.min.css'
import { installChunkRecovery } from './utils/chunk'

export const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
})

// Reload a tab whose bundle the server has already replaced. The detection is
// fiddlier than it looks — see utils/chunk.js for why the obvious hooks all
// miss it.
installChunkRecovery()

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

/*
 * Reload when this tab is running a bundle the server has replaced.
 *
 * An installed PWA is the problem case. It is launched from a home-screen
 * snapshot rather than a fresh navigation, so it can hold an index.html — and
 * therefore a bundle — from days ago, through any number of deploys. Nothing
 * about that is visible: the app works, it is simply not the app that was
 * shipped, and every fix appears not to have landed.
 *
 * There is no service worker doing this for us on purpose (sw.js has no fetch
 * handler precisely so it cannot become a cache layer), so the check is done by
 * hand: ask for index.html with cache-busting, read the bundle it points at, and
 * compare it against the one this tab actually loaded.
 *
 * Runs at start and whenever the app is brought back to the foreground, which
 * for a PWA is the moment it is reopened.
 *
 * Guarded by a timestamp, not a flag. If a reload does NOT resolve the mismatch
 * — a half-propagated deploy, an edge serving a stale index.html — a flag would
 * still allow one reload per foreground and present as an app that reloads
 * whenever it is touched. A minute is far longer than a real recovery and far
 * too short to loop.
 */
const UPDATE_KEY = 'ua-update-reload-at'
const runningBundle = document
  .querySelector('script[type="module"][src*="/assets/index-"]')
  ?.getAttribute('src')

async function reloadIfStale() {
  if (!runningBundle || document.visibilityState === 'hidden') return
  try {
    const res = await fetch('/index.html', { cache: 'no-store' })
    if (!res.ok) return
    const shipped = (await res.text()).match(/\/assets\/index-[A-Za-z0-9_-]+\.js/)?.[0]
    if (!shipped || shipped === runningBundle) return

    const last = Number(sessionStorage.getItem(UPDATE_KEY) || 0)
    if (Date.now() - last < 60_000) return
    sessionStorage.setItem(UPDATE_KEY, String(Date.now()))
    window.location.reload()
  } catch {
    // Offline, or index.html unreachable. Staying on the current bundle is the
    // correct outcome — this must never be able to break a working app.
  }
}

reloadIfStale()
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') reloadIfStale()
})
