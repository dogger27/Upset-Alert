/*
 * Paint the saved theme before the first frame.
 *
 * A separate file rather than an inline <script> in index.html: the site's CSP
 * sets script-src 'self' with no 'unsafe-inline', so an inline block is silently
 * blocked and never runs. That failure is invisible — the page just renders
 * light while the toggle reports dark, until something repaints at runtime.
 *
 * Loaded synchronously (no defer/async, no type=module) so it executes during
 * head parsing, with the attribute already on <html> when styles resolve. A
 * module script would be deferred to after parsing and the light palette would
 * paint first.
 *
 * Light is the default, so an unreadable or missing value means light, and
 * prefers-color-scheme is deliberately not consulted. Keep the storage key in
 * step with THEME_KEY in src/store/theme.js.
 */
(function () {
  var theme = 'light'
  try {
    if (localStorage.getItem('ua-theme') === 'dark') theme = 'dark'
  } catch (e) {
    /* Safari in private mode throws rather than returning null. */
  }
  document.documentElement.setAttribute('data-theme', theme)
})()
