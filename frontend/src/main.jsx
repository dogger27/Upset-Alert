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
