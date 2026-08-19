/*
 * Recovering from a deploy that lands under an open tab.
 *
 * Asset filenames are content-hashed, so a deploy replaces them. A tab opened
 * beforehand still holds the previous index.html, and the moment it lazily
 * imports a chunk it asks for a hash that no longer exists. Cloudflare Pages
 * answers a missing path with index.html — 200, text/html — so the browser
 * reports "Expected a JavaScript-or-Wasm module script but the server responded
 * with a MIME type of text/html" and the page stays broken until reloaded by
 * hand. index.html revalidates on every navigation, so a reload is all it takes.
 *
 * Detecting it is the hard part, and the first two attempts both missed:
 *
 *   - vite:preloadError only fires when a chunk fails to FETCH. Pages does not
 *     fail; it returns 200 with the wrong content type, so nothing raises it.
 *   - A window 'error' listener reading event.message sees nothing: a failed
 *     resource load is a plain Event with no message, unlike an uncaught
 *     exception.
 *   - unhandledrejection never fires either, because every dynamic import in
 *     this app sits inside a try/catch that swallows the rejection first.
 *
 * So the reliable place to catch it is the import itself — hence lazyImport —
 * with the global listeners kept as a backstop for anything that escapes.
 */

const RELOAD_KEY = 'ua-chunk-reload-at'
const MIME_FAILURE =
  /module script|MIME type|Failed to fetch dynamically imported|error loading dynamically imported/i

/** True when this looks like a chunk that no longer exists on the server. */
export function isStaleChunkError(err) {
  if (!err) return false
  const msg = err?.message || String(err)
  return MIME_FAILURE.test(msg)
}

/**
 * Reload once to pick up the current index.html. Guarded by a timestamp rather
 * than a flag: if the reload does NOT fix it — a genuinely broken deploy, an
 * asset that really is missing — a plain flag would still allow one reload per
 * tab per session, and the failure would present as a page that reloads
 * whenever it is touched. Ten seconds is long past a real recovery and far too
 * short to loop.
 */
export function recoverStaleChunk(event) {
  let last = 0
  try { last = Number(sessionStorage.getItem(RELOAD_KEY) || 0) } catch { /* private mode */ }
  if (Date.now() - last < 10_000) return false
  event?.preventDefault?.()
  try { sessionStorage.setItem(RELOAD_KEY, String(Date.now())) } catch { /* ignore */ }
  window.location.reload()
  return true
}

/**
 * Wrap a dynamic import so a stale chunk triggers a reload before the caller's
 * own error handling swallows it.
 *
 *   const push = await lazyImport(() => import('../api/push'))
 */
export async function lazyImport(loader) {
  try {
    return await loader()
  } catch (err) {
    if (isStaleChunkError(err)) recoverStaleChunk()
    throw err
  }
}

/** Global backstop for failures that escape a call site. */
export function installChunkRecovery() {
  window.addEventListener('vite:preloadError', recoverStaleChunk)

  window.addEventListener('error', (event) => {
    // A failed <script>/<link> load carries no message — identify it by the
    // element that failed instead.
    const el = event?.target
    const src = el?.src || el?.href || ''
    if (el?.tagName === 'SCRIPT' && src.includes('/assets/')) {
      recoverStaleChunk(event)
      return
    }
    if (isStaleChunkError({ message: event?.message })) recoverStaleChunk(event)
  }, true)

  window.addEventListener('unhandledrejection', (event) => {
    if (isStaleChunkError(event?.reason)) recoverStaleChunk(event)
  })
}
