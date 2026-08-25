# Why `_headers` has no comments

Cloudflare Pages' `_headers` parser does NOT support `#` comments — every
rule below the first comment line is silently dropped. On 2026-08-24 that
served `sw.js`/`theme.js` with the Pages default `max-age=14400`, pinning
installed PWAs to stale bundles. Keep ALL prose here, never in `_headers`.

## Rule rationale (mirrors the file top-to-bottom)

- `/assets/*` 86400, not a year: hashed URLs never change bytes, but a
  request that lands mid-deploy gets the SPA fallback (index.html, 200)
  cached under the asset URL — happened 2026-08-19. A day bounds that
  blast radius. Never fetch a hashed asset to verify a deploy; poll /sw.js.
- `/` and `/index.html` must-revalidate: index maps names to current
  hashes; a cached copy asks for bundles that no longer exist.
- `/sw.js`, `/theme.js` must-revalidate: the service worker decides when
  the app updates; a cached one pins it.
