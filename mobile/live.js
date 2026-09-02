/*
 * Live updates: subscribe to a tournament's server-sent events and refetch
 * what is on screen when it changes — the site's useLiveUpdates.
 *
 * The event carries no data on purpose. It is a nudge; the screen refetches
 * through its normal request — already written, already cached, already
 * authorised. Pushing scores down this channel would create a second way to
 * learn a score, and therefore a second thing to keep consistent.
 *
 * The app had no refresh at all: a score reached the screen only on a pull.
 * For a set score that is slow; for the POINT score, which changes every few
 * seconds, it made the feature pointless — a 40-15 delivered minutes late is
 * worse than none, which is exactly the reasoning the server's freshness
 * guard is built on.
 *
 * Two transports, one API: the browser's own EventSource where there is one
 * (the harness), react-native-sse's XHR-based one on the phone — pure JS, so
 * no native rebuild. Neither can send an Authorization header, which is fine:
 * the stream only ever says "something changed", never what.
 *
 * Backgrounded, the streams are closed — iOS would kill them anyway — and on
 * return everything subscribed is refetched at once, because whatever
 * happened while the phone was in a pocket was not delivered.
 */
import { useEffect } from 'react'
import { AppState, Platform } from 'react-native'
import RNEventSource from 'react-native-sse'
import { API } from './api'
import { invalidate } from './useApi'

const Source = Platform.OS === 'web' && globalThis.EventSource ? globalThis.EventSource : RNEventSource

export function useLiveUpdates(tournamentIds, prefixes) {
  const ids = (Array.isArray(tournamentIds) ? tournamentIds : [tournamentIds]).filter(Boolean)
  const idKey = ids.join(',')
  const prefixKey = JSON.stringify(prefixes)

  useEffect(() => {
    if (ids.length === 0) return
    let sources = []
    const nudge = () => { for (const p of prefixes) invalidate(p) }

    const open = () => {
      close()
      sources = ids.map(id => {
        const es = new Source(`${API}/stream/${id}`)
        // The server names the event; listen for it AND the default channel,
        // so a rename server-side degrades to "still works".
        es.addEventListener('draw_updated', nudge)
        es.addEventListener('message', nudge)
        // No error handler that closes the stream: both transports reconnect
        // by themselves, and closing here would turn one dropped connection —
        // a tunnel blip, a cell handoff — into a permanently dead screen.
        es.addEventListener('error', () => {})
        return es
      })
    }
    const close = () => { for (const es of sources) { try { es.close() } catch {} } sources = [] }

    open()
    const sub = AppState.addEventListener('change', state => {
      if (state === 'active') { open(); nudge() } else if (state === 'background') close()
    })
    return () => { close(); sub.remove() }
    // ids and prefixes are literals at the call sites; the serialised forms
    // keep this from reconnecting on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idKey, prefixKey])
}
