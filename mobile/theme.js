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

import { leading } from './fontScale.js'

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
  // A third step, for an edge that has to carry a card on a field almost its
  // own colour — the schedule's rows. borderOn is the RAISED edge (chips,
  // controls); this is brighter still and deliberately rare.
  borderLit: '#4e625b',

  // Off-white, not #fff — pure white on a dark field haloes at text sizes.
  ink:       '#e6eeea',
  inkBody:   '#c8d6d0',
  muted:     '#9fb0a9',
  faint:     '#8a9a94',

  green:     '#2d6a4f',
  greenLit:  '#52b788',
  greenMid: '#3f9170',   // between green and greenLit: a score that reads (4:1 on the card) without shouting
  // The site's --brand-text-strong in DARK: its lightest legible green, for
  // something that has to read first. Lighter than greenLit on purpose.
  greenBright: '#7fd4a6',
  // The site's dark --gold-ink: a name whose podium place is locked.
  gold:        '#e0b34a',
  greenDeep: '#14342a',

  // The "ALERT!" clay. The brand's one warm note; spend it, do not spread it.
  clay:      '#c9783a',
  clayLight: '#e8a87c',   // the site's --clay-300: the brand dot and its ring
  clayDeep:  '#7d451f',

  ok:        '#52b788',
  bad:       '#f87171',
  warn:      '#e0a34a',
  // A break POINT on the point timeline: the chance, a pale yellow beside
  // the break's amber (warn), so the two read as one story, lighter first.
  breakPoint: '#f1e27a',
  // Set and match POINTS: the pale forms of the set (info) and match
  // (lossMark) ticks, the chance beside the thing it can become.
  setPoint:   '#bcd2ff',
  matchPoint: '#fbb6b6',
  info:      '#7aa9ff',   // the site's --info (dark): a match carried to a later day
  lossMark:  '#f87171',   // the site's --bad-fg: the cross beside the loser, and the match tick
  h2hP1:     '#38a8f0',   // the site's --h2h-p1 (dark): the top player in a comparison
  h2hP2:     '#c76df2',   // the site's --h2h-p2 (dark): the bottom player

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

/* THE TWO SIDES OF ONE MATCH.
 *
 * A head-to-head needs to say "this number is his and that one is hers" six
 * times on one screen, and the tour colours cannot: in a men's match both
 * players are ATP navy. The site solves it with blue against purple; the app
 * already owns two accents that are nothing to do with a tour — the brand
 * green and the one warm clay — so the pair is theirs.
 *
 * Learned once, in the underline beneath each name, and then used for
 * everything that belongs to a side: which of them leads a row, and who won
 * each previous meeting. One key, one meaning, no second legend.
 *
 * The clay plate is the value the clay-court tag already uses, referenced
 * rather than repeated, so there is one dark clay in this file.
 */
/* THE BETTER FIGURE in a comparison (owner, 2026-09-24): one colour for
   both players, and deliberately neither green nor red — beside a result's
   tick and cross those would read as who WON the match. A calm blue: the
   plate a step below the card, a mid edge, light ink. */
export const BETTER = { ink: '#9cc0ff', line: '#4d7ab5', plate: '#15233a' }

export const SIDE = {
  left:  { ink: C.greenBright, line: C.greenLit, plate: C.greenDeep },
  right: { ink: C.clayLight,   line: C.clay,     plate: C.surfaces.clay.bg },
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
/* `card`, `plate` and `line` shade a whole dashboard card by tour.
 *
 * `plate` (the tier stamp's backing) and `line`/`bg` are the site's dark
 * --{atp,wta}-tint and -rule. `card` IS NOT A SITE TOKEN and there is no
 * honest way to pretend otherwise: the site's cards are never tour-coloured
 * except on hover, so its dark palette has nothing at this lightness. These
 * two were chosen to read as pink and blue rather than as near-black — the
 * site's own --wta-tint-strong shipped first and the owner's verdict was "WAY
 * too dark" (2026-09-15) — while keeping the off-white ink at 7:1 against
 * them, which is what caps how light they may go while the text stays white.
 *
 * So the three steps run light → dark: card, then plate under the stamp, with
 * `line` the one edge lighter than the card it draws around.
 */
/* `text` is the site's --atp-text / --wta-text, and it is the ink the tier
   stamps are drawn in — the ATP's own 250 artwork is exactly this blue, which
   is where the pair comes from. Not `fg`: that is --info, a step deeper, and
   the pill wears it against a much darker fill than the stamp's plate.
   gen-tier-stamps.py bakes these into the artwork and tierStamps.test.mjs
   fails if the two ever disagree. */
/* THE INK RAMP AND THE HAIRLINE BELONG TO THE SURFACE THEY SIT ON.
 *
 * `ink`/`inkBody`/`muted`/`faint` shadow the C.* ramp for a card that is
 * tinted by tour, and `rule` its footer's hairline. The neutral card keeps the
 * C.* values; a card that is pink or blue edge to edge cannot, and the reason
 * is arithmetic rather than taste:
 *
 *   THE C.* RAMP WAS DRAWN AGAINST #182521 (oklch L 0.25). The tints sit at
 *   L 0.43 — nearly twice as light — so every step below the title lost about
 *   half its contrast the day the cards were tinted: C.muted 6.98:1 on the
 *   neutral card but 3.60 on the ATP one, C.faint 5.38 → 2.77. Under 3:1 is
 *   below the floor for any text, and C.faint carries "Opens Sep 19".
 *
 *   AND THE HUE WAS WRONG ON TOP OF IT. The ramp runs 165–171° (green-cyan),
 *   which is where it belongs on a green-grey card — the neutral card is
 *   173.6°. The WTA tint is 356°, i.e. almost exactly the ramp's complement,
 *   and that is the olive cast the pink cards had (owner, 2026-09-16).
 *
 * So: same lightness steps where they still clear AA, re-hued to each tint's
 * own family at the hue of `text` (the tinted ink this palette already had),
 * and the bottom two lifted back over 4:1 — muted to 5.0, faint to 4.2, which
 * keeps them a visible step apart rather than collapsing into one value.
 * `ink` is HELD at its own lightness: 6.9/7.2:1 is the 7:1 the note above
 * already claims, and 13:1 is not reachable on an L 0.43 surface at all.
 *
 * `rule` is the same defect in a hairline. The footer's rule was `plate`,
 * 0.17 L BELOW the tinted card, where C.border sits 0.06 ABOVE the neutral
 * one — so a seam that catches the light on one card was a groove cut into
 * the other. This is that same +0.059 lift at the tint's own hue.
 */
export const TOUR = {
  /* `deep` is one step BELOW `bg`: a plate set into a cell already wearing the
     tour, which is what the schedule's draw bar needs for its tier pill
     (owner, 2026-09-22 — "the bg of the category pills should be a darker
     colour of the blue / pink"). ATP's is the `plate` it already had, which
     was already that step; WTA's `plate` equals its `bg`, so its deep step is
     the one value here that is new. */
  M: { bg: '#1a2f4f', fg: '#7aa9ff', label: 'ATP', card: '#2c5081', plate: '#14243d', line: '#4d7ab5', text: '#8fb6ff',
       deep: '#14243d',
       ink: '#e5ecf8', inkBody: '#c9d3e4', muted: '#c0cbe0', faint: '#aebad0', rule: '#466187' },
  F: { bg: '#3a1526', fg: '#ff8ab5', label: 'WTA', card: '#7d3352', plate: '#3a1526', line: '#b8567d', text: '#ffb3c6',
       deep: '#280e1a',
       ink: '#f7e7eb', inkBody: '#e2ccd0', muted: '#dbbfc6', faint: '#ccafb5', rule: '#854d62' },
  // MIXED DOUBLES belongs to neither tour, so it takes neither tour's colour.
  // The unseeded chip's pair rather than a new one invented for it: a blend of
  // blue and pink is a gradient decision on a 10pt pill, and there is no such
  // token on the site to borrow.
  X: { bg: '#2b3a35', fg: '#b8c6c0', label: 'MXD' },
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
  display:  { fontFamily: 'SairaCondensed_700Bold',   fontSize: 30, lineHeight: leading(34), letterSpacing: 0.3 },
  h1:       { fontFamily: 'SairaCondensed_700Bold',   fontSize: 24, lineHeight: leading(28), letterSpacing: 0.2 },
  h2:       { fontFamily: 'SairaCondensed_600SemiBold', fontSize: 19, lineHeight: leading(23) },
  eyebrow:  { fontFamily: 'SairaCondensed_700Bold',   fontSize: 12, lineHeight: leading(14), letterSpacing: 1.1 },
  score:    { fontFamily: 'SairaCondensed_700Bold',   fontSize: 20, lineHeight: leading(22) },

  body:     { fontFamily: 'Archivo_400Regular',       fontSize: 15, lineHeight: leading(21) },
  bodyMed:  { fontFamily: 'Archivo_500Medium',        fontSize: 15, lineHeight: leading(21) },
  bodyBold: { fontFamily: 'Archivo_700Bold',          fontSize: 15, lineHeight: leading(21) },
  small:    { fontFamily: 'Archivo_400Regular',       fontSize: 13, lineHeight: leading(18) },
  smallMed: { fontFamily: 'Archivo_500Medium',        fontSize: 13, lineHeight: leading(18) },
  smallBold:{ fontFamily: 'Archivo_700Bold',          fontSize: 13, lineHeight: leading(18) },
  tiny:     { fontFamily: 'Archivo_500Medium',        fontSize: 11, lineHeight: leading(15) },
}

/* Spacing. One scale, used everywhere, so gaps are chosen rather than typed. */
export const S = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 }

/* xs is a corner you notice only if you look — the Schedule's tournament
   pills (owner, 2026-09-21), which read as labels rather than buttons and
   lost their shape entirely at `pill`. */
export const R = { xs: 3, sm: 8, md: 12, lg: 16, pill: 999 }

// Apple's minimum. The website follows the same rule, so a control that feels
// right in one client feels right in the other.
export const TOUCH = 44
