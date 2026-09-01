/*
 * The palette, in one place.
 *
 * Taken from the web app's dark tokens rather than reinvented, because the two
 * clients will sit side by side in screenshots and on the same person's
 * devices. The web app is dark-first and its light mode is the exception; this
 * app is dark only for now, so there is no second set of values to keep in
 * step.
 */

export const C = {
  bg:      '#101a16',
  card:    '#182521',
  raised:  '#1f2e29',
  border:  '#3a4b45',
  ink:     '#eef2f0',
  muted:   '#93a49e',
  accent:  '#c9783a',   // the "ALERT!" orange
  green:   '#2d6a4f',
  error:   '#f87171',
  atp:     '#3b6ea8',
  wta:     '#a8437a',
}

// Apple's minimum is 44pt. The web app now follows the same rule, so a control
// that feels right in one client feels right in the other.
export const TOUCH = 44
