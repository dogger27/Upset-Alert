/*
 * The device's text-size setting, as a multiplier.
 *
 * WHY THIS EXISTS: React Native scales `fontSize` with the system text size but
 * leaves a hard-coded `lineHeight` exactly where it was. Set both — which every
 * style in theme.js did — and a reader with larger text gets glyphs that
 * outgrow their line box and are clipped top and bottom. Reported as "the
 * button text is cut off" on the draw's round strip; it was every fixed
 * lineHeight in the app, on any phone with the setting turned up.
 *
 * Read once at module load. The setting cannot change without the app being
 * backgrounded and, in practice, relaunched.
 *
 * The `require` is deliberate and the try/catch is not defensive padding:
 * theme.js is loaded directly by node in theme.test.mjs, where react-native
 * cannot resolve and `require` is not even defined in an ES module. Metro
 * compiles this to CommonJS, so the require succeeds there. Node falls through
 * to 1, which is exactly right for a test that only inspects token names.
 */
let scale = 1
try {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  scale = require('react-native').PixelRatio.getFontScale() || 1
} catch {
  scale = 1
}

/* HARNESS OVERRIDE. react-native-web always reports a font scale of 1, which
   left the visual-diff harness blind to the whole class of "larger text"
   bugs — it could not reproduce the clipped chips or the truncated names the
   phone showed. tools/visual-diff.mjs sets this before the bundle loads so a
   render on Jupiter can use the reader's actual text size. Never set by the
   app itself. */
if (typeof globalThis !== 'undefined' && Number(globalThis.__UA_FONT_SCALE) > 0) {
  scale = Number(globalThis.__UA_FONT_SCALE)
}

export const FONT_SCALE = scale

/** A line height that grows with the reader's text size, like the glyphs do. */
export const leading = px => Math.round(px * scale)
