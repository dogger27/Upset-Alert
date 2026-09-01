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

  // The tour ramps, from the site's --atp-500/--atp-700 and --wta-500/-700.
  // The first pass here used eyeballed approximations (#3b6ea8 / #a8437a);
  // these are the real values, and the difference is visible.
  atp:       '#2563eb',
  atpDeep:   '#1742a0',
  wta:       '#db2777',
  wtaDeep:   '#a3134e',

  // Court surfaces: the dot colour, and the pill's dark-mode fill and ink.
  surfaces: {
    grass: { dot: '#2f9e44', bg: '#102b18', fg: '#6fd18a', label: 'Grass' },
    clay:  { dot: '#c9783a', bg: '#33200f', fg: '#e0a06a', label: 'Clay' },
    hard:  { dot: '#1d4ed8', bg: '#142743', fg: '#8fb6ff', label: 'Hard' },
  },
}

/* --shadow-sm in dark: 0 1px 3px rgba(0,0,0,0.50). RN wants the pieces
   separately, and its shadowRadius is roughly the CSS blur halved. */
/* Pick states, from the bracket's own CSS. THE WHOLE BOX CHANGES, not a mark
   in the corner — that is what makes a wall of matches readable at a glance,
   and it is the single biggest thing the first version of this screen missed. */
/* The bracket's position badge — seed in gold, ranking in grey, qualifier in
   green. Straight from BracketView.css's .pos-badge and its dark tokens. */
/* The ATP / WTA badge, resolved from the site's DARK tokens — the app has no
   light mode, so the light values (#dbeafe / #fce7f3) would be wrong here.
   ATP: --atp-tint-strong + --info.  WTA: --wta-tint + --wta-text. */
export const TOUR = {
  M: { bg: '#1a2f4f', fg: '#7aa9ff', label: 'ATP' },
  F: { bg: '#3a1526', fg: '#ff8ab5', label: 'WTA' },
}

export const BADGE = {
  seeded:   { bg: '#3a2f10', fg: '#e8c766', line: '#6b5518' },
  unseeded: { bg: '#2b3a35', fg: '#b8c6c0', line: '#9fb0a9' },
  qual:     { bg: '#142e24', fg: '#8fd8b0', line: '#35664d' },
}

export const PICK = {
  correct: { bg: '#1c4a33', border: '#45c977' },
  wrong:   { bg: '#4a2320', border: '#f2726a' },
  needs:   { bg: null,      border: '#f0b03f' },
}

export const SHADOW = {
  shadowColor: '#000',
  shadowOffset: { width: 0, height: 1 },
  shadowOpacity: 0.5,
  shadowRadius: 2,
  elevation: 2,
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
