/*
 * A very small data layer.
 *
 * React Query would be the obvious choice — the web app uses it — but
 * expo-router drags in vaul/Radix, which demand a react-dom this project does
 * not have, so installing it means --legacy-peer-deps and a permanently
 * unhealthy dependency tree. Three read-only screens do not justify that, so
 * this is the ~50 lines of it that we actually use: a module-level cache keyed
 * by string, deduped in-flight requests, and explicit invalidation.
 *
 * What it deliberately does NOT do: refetch on focus, retry, or garbage
 * collect. When those are wanted, that is the moment to reach for the real
 * library — not now.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

const cache = new Map()     // key -> data
const inflight = new Map()  // key -> Promise

export function invalidate(prefix) {
  if (!prefix) { cache.clear(); inflight.clear(); return }
  for (const k of [...cache.keys()]) if (k.startsWith(prefix)) cache.delete(k)
  for (const k of [...inflight.keys()]) if (k.startsWith(prefix)) inflight.delete(k)
}

export function useApi(key, fetcher, { enabled = true } = {}) {
  const [data, setData] = useState(() => (key ? cache.get(key) : undefined))
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(() => enabled && !!key && !cache.has(key))
  const alive = useRef(true)
  const fnRef = useRef(fetcher)
  fnRef.current = fetcher

  useEffect(() => () => { alive.current = false }, [])

  const run = useCallback(async (force = false) => {
    if (!key || !enabled) return
    if (!force && cache.has(key)) { setData(cache.get(key)); setLoading(false); return }
    setLoading(true); setError(null)
    try {
      // Dedupe: two screens mounting at once must not fire the same request
      // twice, which is easy to do with a tab bar and a back gesture.
      let p = force ? null : inflight.get(key)
      if (!p) { p = fnRef.current(); inflight.set(key, p) }
      const result = await p
      cache.set(key, result)
      if (alive.current) { setData(result); setError(null) }
    } catch (e) {
      if (alive.current) setError(e)
    } finally {
      inflight.delete(key)
      if (alive.current) setLoading(false)
    }
  }, [key, enabled])

  useEffect(() => { alive.current = true; run() }, [run])

  return { data, error, loading, refetch: () => run(true) }
}
