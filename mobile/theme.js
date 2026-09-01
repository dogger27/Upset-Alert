/*
 * The design system, taken from the website rather than invented.
 *
 * These are the web app's dark tokens verbatim (frontend/src/index.css,
 * :root[data-theme='dark']). The two clients are the same product on the same
 * person's devices, and a mobile app with its own approximate palette reads as
 * a knock-off of the site — which is exactly what the first pass looked like,
 * because I eyeballed the colours instead of copying them.
 *
 * Dark only. The website is dark-first and its light mode is the exception;
 * there is no second set of values to keep in step until someone asks for one.
 */

export const C = {
  // Surfaces. Each step lifts toward the light: sunken < page < card < raised,
  // kept close together so elevation reads through the border, not a glare.
  bg:        '#0b1512',
  sunken:    '#0a120f',
  card:      '#182521',
  raised:    '#20302a',
  control:   '#22322c',
  border:    '#253430',
  borderOn:  '#3a4b45',

  // Off-white, not #fff — pure white on a dark field haloes at text sizes.
  ink:       '#e6eeea',
  inkBody:   '#c8d6d0',
  muted:     '#9fb0a9',
  faint:     '#8a9a94',

  green:     '#2d6a4f',
  greenLit:  '#52b788',
  greenDeep: '#14342a',

  // The "ALERT!" clay. The brand's one warm note; spend it, do not spread it.
  clay:      '#c9783a',
  clayDeep:  '#7d451f',

  ok:        '#52b788',
  bad:       '#f87171',
  warn:      '#e0a34a',

  // Court surfaces, matching the site's swatches.
  grass:     '#2f9e44',
  clayCourt: '#c9783a',
  hard:      '#3b6ea8',

  atp:       '#3b6ea8',
  wta:       '#a8437a',
}

/* Type scale.
 *
 * Saira Condensed for anything that behaves like a scoreboard — headings,
 * numbers, labels. It is the site's display face and it is condensed, which is
 * the whole reason it works here: a player's name and three set scores have to
 * share 340 points of phone.
 *
 * Sizes are a modular-ish scale rather than round numbers, and line heights are
 * explicit — RN's defaults differ per platform and drift as text scales.
 */
export const T = {
  display:  { fontFamily: 'SairaCondensed_700Bold',   fontSize: 30, lineHeight: 34, letterSpacing: 0.3 },
  h1:       { fontFamily: 'SairaCondensed_700Bold',   fontSize: 24, lineHeight: 28, letterSpacing: 0.2 },
  h2:       { fontFamily: 'SairaCondensed_600SemiBold', fontSize: 19, lineHeight: 23 },
  eyebrow:  { fontFamily: 'SairaCondensed_700Bold',   fontSize: 12, lineHeight: 14, letterSpacing: 1.1 },
  score:    { fontFamily: 'SairaCondensed_700Bold',   fontSize: 20, lineHeight: 22 },

  body:     { fontFamily: 'Archivo_400Regular',       fontSize: 15, lineHeight: 21 },
  bodyMed:  { fontFamily: 'Archivo_500Medium',        fontSize: 15, lineHeight: 21 },
  bodyBold: { fontFamily: 'Archivo_700Bold',          fontSize: 15, lineHeight: 21 },
  small:    { fontFamily: 'Archivo_400Regular',       fontSize: 13, lineHeight: 18 },
  smallMed: { fontFamily: 'Archivo_500Medium',        fontSize: 13, lineHeight: 18 },
  tiny:     { fontFamily: 'Archivo_500Medium',        fontSize: 11, lineHeight: 15 },
}

/* Spacing. One scale, used everywhere, so gaps are chosen rather than typed. */
export const S = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 }

export const R = { sm: 8, md: 12, lg: 16, pill: 999 }

// Apple's minimum. The website follows the same rule, so a control that feels
// right in one client feels right in the other.
export const TOUCH = 44
