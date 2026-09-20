/*
 * The website's card, rebuilt for React Native.
 *
 * Ported from components/design/TournamentCard.jsx, SurfacePill.jsx and
 * TierBadge.jsx — anatomy and numbers, not an impression of them. The first
 * attempt at this screen used the site's COLOURS but invented its own layout,
 * and the result looked assembled rather than designed. Every measurement here
 * comes from the source.
 */

import { createContext, useContext, useMemo, useState } from 'react'
import { Image, Pressable, StyleSheet, Text, View } from 'react-native'
import { leading } from './fontScale.js'
import { stampsFor, tierStamp } from './logos'
import { CAP as CAP_RATIO } from './fontMetrics.js'
import { flagEmoji } from './flags'
import { CardLink } from './ui'
import { textWidth } from './measure.js'
import { nameForms, pairForms } from './names'
import { BADGE, C, R, SHADOW, T, TOUR } from './theme'

/* THE INK OF WHATEVER CARD YOU ARE INSIDE.
 *
 * A context rather than a prop because of WHO decides and WHO renders. The
 * card decides its surface — TourCard alone knows whether an event is one
 * tour or two, and therefore whether the card is tinted or neutral — while the
 * things that have to match that surface are supplied by the CALLER, as
 * `children` and `footer`: the city, the dates, the standing, the order of
 * play. Threading an ink set through every call site would make each of them
 * restate a decision they do not own, and the one that forgot would go black
 * on a coloured card, silently, which is the failure theme.test.mjs exists
 * for. Provided once by the card; read by whatever ends up inside it.
 *
 * DEFAULTS TO THE NEUTRAL RAMP, so a component that uses this outside a
 * TourCard — the schedule's rows, a plain Card — is unchanged.
 */
/* `control`/`controlInk` are the AVAILABLE state of a control on this card —
   the pill's fill and the label on it. Named by role rather than by where they
   came from: on a tinted card they are the dark its tier stamp sits on and the
   tour's own light ink, and on the neutral card the page and the off-white.
   A control that can be pressed is a RECESSED DARK CHIP and one that cannot is
   barely lifted off the card, which is the polarity the owner asked for and
   which stays harmonious on both tints — see the note at OrderOfPlay. */
const NEUTRAL_SKIN = {
  ink: C.ink, inkBody: C.inkBody, muted: C.muted, faint: C.faint,
  card: C.card, line: C.border, control: C.bg, controlInk: C.ink, quiet: false,
  // No tour, so no tour colour to accent with — see `accent` below.
  accent: C.ink,
}
const CardSkinContext = createContext(NEUTRAL_SKIN)
export const useCardSkin = () => useContext(CardSkinContext)

/* The accent bar: a 4px vertical gradient from the tour's 500 to its 700.
   Six stacked bands rather than a real gradient — expo-linear-gradient is a
   native module and another build, and across four points nobody can tell. */
export function AccentBar({ from, to, width = 4, style }) {
  const steps = 6
  return (
    <View style={[{ width }, style]}>
      {Array.from({ length: steps }, (_, i) => (
        <View key={i} style={{ flex: 1, backgroundColor: mix(from, to, i / (steps - 1)) }} />
      ))}
    </View>
  )
}

function mix(a, b, t) {
  const pa = parseInt(a.slice(1), 16), pb = parseInt(b.slice(1), 16)
  const ch = (p, sh) => (p >> sh) & 255
  const r = Math.round(ch(pa, 16) + (ch(pb, 16) - ch(pa, 16)) * t)
  const g = Math.round(ch(pa, 8) + (ch(pb, 8) - ch(pa, 8)) * t)
  const bl = Math.round(ch(pa, 0) + (ch(pb, 0) - ch(pa, 0)) * t)
  return `#${((r << 16) | (g << 8) | bl).toString(16).padStart(6, '0')}`
}

/* THE SURFACE, AS PLAIN TYPE.
 *
 * It was the site's chip — a tinted pill with a coloured dot — and on a card
 * whose every other fact is set in type it read as a control among labels
 * (owner, 2026-09-15). The words are the fact; the dot was decoration with a
 * colour key nobody was given.
 *
 * What the component is still FOR is the two bits of knowledge in it: "(i)"
 * for indoor is stripped, matching the web, because indoor hard is still hard;
 * and the label comes from the palette's own table, so "Hard" is spelled the
 * same here as everywhere else. */
export function SurfaceText({ surface, style }) {
  const key = String(surface || '').toLowerCase().replace(/\s*\(.*?\)/g, '').trim()
  const s = C.surfaces[key] || C.surfaces.hard
  const inks = useCardSkin()
  return (
    <Text style={[T.tiny, { color: inks.muted }, style]} numberOfLines={1}>{s.label}</Text>
  )
}

/* The real artwork, at the site's `sm` box (88×38). contain, so a wide WTA tag
   and a square ATP stamp carry the same visual weight.
 *
 * ON A PLATE IN THE TOUR'S COLOUR, which is where the ATP/WTA pill's dark pink
 * and navy went when the pill came off the card (owner, 2026-09-15). The stamp
 * says the tier and the plate says the tour, in one object instead of two at
 * opposite ends of the row — and since the plate's colour is a token, the tier
 * artwork no longer has to carry a background of its own (see logos.js).
 *
 * EXCEPT A SLAM. The four crests are each tournament's own mark, drawn the way
 * that tournament draws it, and they are left alone — no plate, nothing
 * recoloured (owner, 2026-09-15). They carry the event, not the tier.
 */
/* THE STAMP IS SIZED BY ITS OWN SHAPE, not fitted into a box.
 *
 * A fixed box and `contain` cannot give equal type AND an even margin, and
 * chasing both through three attempts is what finally made the reason plain:
 * `contain` fits by whichever side runs out first — the width, for every one
 * of these — so the lettering's rendered height is set by its aspect ratio,
 * and every stamp in one box must therefore share one canvas width. A shared
 * canvas is as wide as the WIDEST line, so the narrower ones float in it: ~26pt
 * of air either side of a WTA line against ~6pt above and below (owner,
 * 2026-09-15).
 *
 * So the box goes. gen-tier-stamps.py crops each stamp to its lettering at a
 * known cap height, which is all the badge needs: draw the artwork at CAP tall
 * and its own aspect wide, and let the plate's padding — one number, therefore
 * equal on all four sides — be the margin. Every stamp then has the same type
 * size and the same even border, and the plate is as wide as what it holds.
 *
 * CAP is in points and deliberately does not scale with the reader's text
 * size: it is artwork, and the title beside it is what gives way when the
 * type grows (see CardTitle).
 */
const CAP = 15
/* A WEEK CARD'S STAMP. The artwork is back — words said the tier but a stamp
   says it faster, and it is most of what makes these read as cards rather
   than list rows — at a size that fits a two-line box: the caps land near the
   type beside them instead of towering over it.

   9pt was the first answer and read as too small (owner, 2026-09-15); this is
   that times 1.5, which lands between it and the full 15. Read as the scale it
   is, rather than as a number, because the plate's padding and the crest below
   are the same multiple of what they were — a stamp that grows while its own
   margin does not is a stamp in a tighter box, not a bigger one. */
const SMALL = 1.5
const CAP_SMALL = 9 * SMALL
/* A CREST IS NOT A TIER STAMP, so it is not held to the tier stamps' height.
   These are the tournaments' own marks, mostly square where a tier stamp is a
   6:1 strip, so the strip's 15pt left them a third the size of the type beside
   them. A Slam is allowed to tower over the week's 250, and the row grows to
   hold it.

   96x64 was the first size that satisfied "bigger", and 20% off it was the
   answer (owner, 2026-09-15) — the box is scaled, not redrawn, so both kinds
   of crest come down by the same fifth: a square mark (Wimbledon, Roland
   Garros) fits by height at 51pt, and the US Open's flame, which is 2.09:1
   since it lost its wordmark, fits by width and lands at ~37pt tall. Width is
   the real cap on any of them: much past this the crest starts taking room
   from the tournament's name. */
const CREST = { width: 77, height: 51 }
/* A crest at a week card's scale. Wider than it is tall by more than the
   square crests are, so a square one (Wimbledon, Roland Garros) fits by HEIGHT
   and the US Open's 2.09:1 flame by width — both close enough to the small
   tier plate that a Slam barely changes the row's height.

   A FURTHER STEP DOWN from the tier plates' scale, and its own constant
   because the two move independently: a crest is a square-ish picture where a
   tier plate is a 6:1 strip, so it pays for scale in HEIGHT — the shared 1.5
   took the plates from 58pt to 60 and the Slam from 71 to 84. Dividing by 1.25
   gives that height back without touching the plates (owner, 2026-09-15).

   1.5625 NOW, WHICH IS 1.25 / 0.8 — the week crest at 80% of what it was
   (owner, 2026-09-16). Expressed as the divisor rather than as a new pair of
   numbers so the one thing this constant means stays true: it is how much
   SMALLER a week card's crest is than a full card's, and every size below is
   still derived from the 44x26 box the full cards use.

   The box goes 52.8x31.2 -> 42.2x25.0, so a square crest (Wimbledon, Roland
   Garros) comes down from 31.2pt tall to 25.0 and the US Open's flame from
   52.8x25.3 to 42.2x20.2 — `contain` fits a square one by height and the
   2.09:1 flame by width, which is why the two land differently. 25.0 is now
   just under the small tier plate's 25.5, so a Slam no longer sets the row's
   height at all. */
const CREST_SHRINK = 1.5625
const CREST_SMALL = {
  width: (44 * SMALL) / CREST_SHRINK,
  height: (26 * SMALL) / CREST_SHRINK,
}

/* Kanit's cap height over its em, from the font's own metric — every weight
   of the family shares it (fontMetrics.js CAP, generated). The badge is
   specified in CAP HEIGHT, as the artwork was: `cap` tall, whatever the face.
   So the font size is the cap the badge wants divided by this. */
const KANIT_CAP = CAP_RATIO.Kanit_900Black_Italic

export function TierBadge({ tour, tier, name, small }) {
  const { crest, mark, num } = tierStamp({ tour, tier, name })
  // A crest keeps the square-ish box it has always had, and no plate: it is
  // the tournament's own mark, not a tier stamp (see logos.js).
  if (crest) {
    return <Image source={crest} style={small ? CREST_SMALL : CREST} resizeMode="contain" />
  }
  if (!mark) return null
  const key = String(tour || 'ATP').toUpperCase() === 'ATP' ? 'M' : 'F'
  const cap = small ? CAP_SMALL : CAP
  const size = Math.round((cap / KANIT_CAP) * 10) / 10
  /* THE NUMBER IS LIGHT AND THE WORDMARK IS BLACK (owner, 2026-09-20: "the
     ATP / WTA part needs to be a lot more bold than the number part", then
     "let's go 900 / 300"), which is the contrast the artwork had.

     ONE LINE HEIGHT FOR BOTH, and it is the cap plus a couple of points
     rather than the face's natural leading: the plate is built around the
     lettering's cap height, so a 1.3-em line box would have made the badge a
     third taller than the artwork's. The two words share a size, so they
     share a baseline without being asked to. */
  const line = { fontSize: size, lineHeight: leading(cap + 2), color: TOUR[key].text }
  return (
    <View style={[u.stamp, u.stampSet, small && u.stampSmall, { backgroundColor: TOUR[key].plate }]}>
      <Text style={[u.stampMark, line]} allowFontScaling={false}>{mark}</Text>
      <Text style={[u.stampNum, line, { marginLeft: size * 0.06 }]} allowFontScaling={false}>{num}</Text>
    </View>
  )
}

/* A status chip. The website gives these their own tinted backgrounds rather
   than colouring bare text, which is most of why its footers read as a row of
   states rather than a sentence. */
export function StatusChip({ tone = 'muted', children }) {
  const tones = {
    good: { bg: '#102b18', fg: '#6fd18a' },
    warn: { bg: '#33200f', fg: '#e0a06a' },
    bad: { bg: '#3a1520', fg: '#f0908f' },
    muted: { bg: C.control, fg: C.muted },
  }
  const t = tones[tone] || tones.muted
  return (
    <View style={[u.chip, { backgroundColor: t.bg }]}>
      <Text style={[T.tiny, { color: t.fg }]}>{children}</Text>
    </View>
  )
}

/* The card shell: 1px border, radius 12 (--radius-md), shadow-sm, the accent
   bar down the left, and the site's asymmetric padding — 20 on the left so the
   text clears the bar, 16 on the right. */
/* `href` makes the card's BODY the link — title, stamp and meta — and leaves
   the footer as a sibling inside the same frame. The footer carries its own
   links (Order of Play), and a link inside a link is invalid HTML on the web
   build and a tap-ownership fight on native. Wrapping the whole card was the
   nesting the site's own TournamentCard has, and the harness flagged it here
   the day after I flagged it there. */
/* `corner`: a mark pinned to the card's top-right corner, straddling its
   border — a state that belongs to the whole card rather than to any row in
   it (the Competing star). It is a SIBLING of the card, not a child: the card
   clips its own overflow so the accent bar keeps the corner radius, and a
   child would be cut off at exactly the edge the mark is meant to sit on. */
/* ONE CARD PER EVENT, not per draw.
 *
 * `draws` is the event's draws — one, or the two of a combined event (men
 * first; drawsByTournament settles that). Two of them used to mean two cards
 * with the same name, the same city, the same dates and the same crest,
 * distinguished by their tint (owner, 2026-09-15). Now they are one card, and
 * the things that differ per tour — the tier stamp, and whatever the caller
 * puts in the footer — are what appears twice inside it.
 *
 * A combined card is NEUTRAL. The tint says which tour a card belongs to and
 * this one belongs to both, so it goes back to the palette's own card colour;
 * the accent bar carries both tours instead, split down the middle, which is
 * the one place a tour colour still means something here.
 */
/* `compact`: a card for a week that is not this one.
 *
 * Two things, because they are one idea — this card is worth less room:
 *
 *   A SMALL STAMP. The full-size one was the tallest thing on a card that is
 *   otherwise a line under a name (27pt for a tier plate, 51 for a Slam crest
 *   against 19pt of type), so Last Week stood a third taller than its
 *   neighbours on the strength of a picture. Printing the tier in words fixed
 *   the height and lost the picture; scaling the picture keeps both (owner,
 *   2026-09-15).
 *
 *   A TIGHTER BOX. Padding 14 and a 9pt gap are the site's numbers for a card
 *   you can act on; on a two-line card they were a third of its height.
 *   Halved, and the horizontal padding left alone so every card down the
 *   column still starts its text at the same x.
 */
export function TourCard({ draws, name, children, footer, href, corner, compact }) {
  const list = (draws || []).filter(Boolean)
  const combined = list.length > 1
  const isATP = list[0]?.gender !== 'F'
  /* A Slam's crest is the EVENT's mark, the same artwork for either tour, so
     stacking it twice would print the same picture twice. Every other tier
     stamp names a tour and both are shown. logos.js::stampsFor — the
     schedule's tournament heading asks the same question. */
  const stamps = stampsFor(list)
  /* ONE DECISION, TWO HALVES. The surface and the ink that has to read on it
     are chosen together and in one place — see CardSkinContext above and the
     ramp's derivation in theme.js. `rule` is the footer's hairline: it lifts
     off the card it draws on, whichever card that is, which was not true
     while the tinted cards borrowed `plate` for it. */
  const tour = combined ? null : TOUR[isATP ? 'M' : 'F']
  const skin = tour
    ? { card: tour.card, line: tour.line, rule: tour.rule }
    : { card: C.card, line: C.border, rule: C.border }
  /* THE SURFACE RIDES ALONG WITH THE INK. The corner star's disc has to be
     the CARD's colour — it sits half off the edge and closes the border it
     crosses, so a fixed C.card is a near-black blob on a tinted card. */
  /* `quiet` IS THE SECTION, NOT THE STATE, and the two are independent.
     Whether a control can be pressed is one axis — a sheet exists or it does
     not — and how much the card it sits on is worth is another: Open and
     Active are this week, next and last week are context. `compact` already
     carries exactly that (it is what the week cards pass), so the control
     reads it here rather than the section re-deciding it. Spread last so it
     reaches the neutral skin too — the Last week card is combined AND
     compact, which is the case a tour-only branch would miss. */
  const inks = {
    ...(tour
      ? { ink: tour.ink, inkBody: tour.inkBody, muted: tour.muted, faint: tour.faint,
          card: tour.card, line: tour.line, control: tour.plate, controlInk: tour.text,
          /* `accent` — A DISGUISED ACCENT, for the rare label that should read
             as tinted rather than as more of the ramp (owner, 2026-09-16). The
             tour's own ink pulled 40% toward the card's near-white one: 3.4x
             the ramp's chroma on the WTA card and 4.1x on the ATP, so it is
             visibly coloured beside a city name, at 5.8:1 and 5.0:1, so it is
             still a label rather than a decoration.

             WHY NOT THE TOUR'S INK ITSELF, which is the obvious answer: at
             11pt BOLD nothing here counts as large text, so the floor is
             4.5:1 and the raw ink measures 4.01 on the ATP card. Nor a fixed
             accent — clayLight is 4.01 and gold 4.17 on that same card, and
             both are near-complementary to it besides (the Schedule button
             spent an afternoon on that lesson). Blending toward the ramp is
             the one move that raises the contrast and keeps the hue.

             DERIVED RATHER THAN TWO MORE HEXES, so it follows if either token
             moves, and mix() is already here for the accent bar. */
          accent: mix(tour.text, tour.ink, 0.4) }
      : NEUTRAL_SKIN),
    quiet: !!compact,
  }
  const body = (
    <>
        <View style={u.titleRow}>
          {/* NO TOUR PILL HERE ANY MORE (owner, 2026-09-15). It was on this
              row because a combined event supplies two draws both called
              "US Open" whose tier stamp is the same logo for both, so
              something had to tell them apart. The whole card is now tinted by
              tour — pink or blue, edge to edge — which separates those two
              cards across the room, where a 40pt pill needed reading. The
              pill's own colour did not go away: it is the plate under the
              tier stamp. */}
          <CardTitle name={name} />
          <View style={[u.stampStack, compact && u.stampStackTight]}>
            {stamps.map(d => (
              <TierBadge key={d.id} tour={d.gender === 'F' ? 'WTA' : 'ATP'}
                         tier={d.category} name={name} small={compact} />
            ))}
          </View>
        </View>
        {children}
    </>
  )
  return (
    <CardSkinContext.Provider value={inks}>
    <View>
      {/* SHADED BY TOUR, edge to edge: the site's own answer for a card that
          belongs to one tour (it tints this card on hover with exactly these
          values). The border and the footer's rule come along — a pink card
          with the palette's grey-green edge reads as an unfinished state, not
          a colour choice. */}
      <View style={[u.card, { backgroundColor: skin.card, borderColor: skin.line }]}>
        {combined ? (
          // Both tours, split down the bar. Men above, as everywhere else.
          <View style={{ width: 4 }}>
            <AccentBar from={C.atp} to={C.atpDeep} style={{ flex: 1 }} />
            <AccentBar from={C.wta} to={C.wtaDeep} style={{ flex: 1 }} />
          </View>
        ) : (
          <AccentBar from={isATP ? C.atp : C.wta} to={isATP ? C.atpDeep : C.wtaDeep} />
        )}
        {/* THE COLUMN AND THE `nav` SLOT ARE GONE (owner, 2026-09-16). They
            existed so a full-bleed band could sit flush to the card's bottom
            edge, outside the body's padding; the band is now three plates the
            caller puts on a row of its own choosing, so the body is the whole
            card again. */}
        <View style={[u.body, compact && u.bodyTight]}>
          {href
            ? <CardLink href={href} style={[u.bodyLink, compact && u.bodyLinkTight]}
                        pressedOpacity={0.75}>{body}</CardLink>
            : <View style={[u.bodyLink, compact && u.bodyLinkTight]}>{body}</View>}
          {footer ? (
            <View style={compact ? u.footerPlain
                                 : [u.footer, { borderTopColor: skin.rule }]}>
              {footer}
            </View>
          ) : null}
        </View>
      </View>
      {/* box-none, not none: the slot itself must never swallow a tap meant
          for the card under it — the card is a link to the draw, and a hole in
          that target at the corner would be a dead spot nobody could
          explain — but what it HOLDS may be pressable in its own right. */}
      {corner ? <View style={u.corner} pointerEvents="box-none">{corner}</View> : null}
    </View>
    </CardSkinContext.Provider>
  )
}

/* THE CARD'S THREE DESTINATIONS, AS A BROADCAST LOWER-THIRD.
 *
 * Built to design/card-nav/livery-spec.md — the "Livery" direction, chosen
 * from four (design/card-nav/Card Nav Options.html) and rendered in
 * Livery.html. Points, states and touch targets are the spec's; every colour
 * is an existing theme.js token read through useCardSkin(), so this adds no
 * dependency and no new value to the palette.
 *
 * THE IDEA: the plates a broadcaster drops over the bottom of the picture,
 * leaning the tier marks' own 8 degrees. It earns the slant honestly — the ATP
 * and WTA tier artwork on this same card is oblique and nothing else in the
 * app leans — and it puts the three destinations on the same material as the
 * tier stamp without needing to shout: the type stays 13pt semibold at the
 * BODY step, quieter than the four passes before it (which reached 17pt caps
 * before the owner called it).
 *
 * WHAT IT HAS SHED, in two asks and in this order. The gloss sweep first — a
 * 44pt band crossing the nav every 5.5s, and with it an Animated loop per
 * card, a layout listener, a reduced-motion subscription and a stagger index.
 * Then the BAND itself (owner, 2026-09-16): the full-bleed field, its top
 * hairline, its padding and the four speed lines that trailed off to the left.
 * What is left is the idea's core — three leaning plates — small enough to sit
 * on a row beside the city rather than occupying a storey of its own.
 *
 * SO THIS IS A ROW, NOT A BAND, and the caller places it. It appears on Last
 * week alone; Open and Active carry no destinations at all, because a card you
 * can act on is worth its whole height to the acting.
 */
export function CardNav({ items }) {
  const skin = useCardSkin()
  /* The label sits at the BODY step, not the loud one — the spec's own choice,
     and the plate behind it is what carries the weight. */
  const label = skin.quiet ? skin.muted : skin.inkBody
  return (
      <View style={u.navPlates}>
        {items.map(it => {
          const live = !!it.href
          const plate = [u.navPlate, { backgroundColor: skin.control }]
          if (live) {
            return (
              <CardLink key={it.label} href={it.href} hitSlop={NAV_SLOP}
                        accessibilityLabel={it.a11y} style={plate}
                        pressedStyle={{ backgroundColor: skin.controlInk + '47' }}>
                {({ pressed }) => (
                  <Text style={[u.navText, { color: pressed ? skin.ink : label }]}
                        numberOfLines={1}>{it.label}</Text>
                )}
              </CardLink>
            )
          }
          /* NOTHING TO OPEN YET — the plate stays and goes translucent. It
             never disappears: a band that loses a plate changes shape from
             card to card, which is the one thing a nav must not do. */
          return (
            <View key={it.label} style={[plate, u.navPlateDead]}
                  accessibilityRole="text"
                  accessibilityLabel={`${it.a11y} — nothing published yet`}>
              <Text style={[u.navText, { color: skin.faint }]} numberOfLines={1}>
                {it.label}
              </Text>
            </View>
          )
        })}
      </View>
  )
}

/* 9 top and bottom takes the 26pt plate past 44; 2 a side rather than more,
   because the plates are only 3pt apart and a wider slop would let one steal
   the neighbour's centre (the spec's numbers, and its reasoning). */
const NAV_SLOP = { top: 9, bottom: 9, left: 2, right: 2 }

/* ONE LINE, SHRUNK TO FIT — the general case of what CardTitle does for a
 * tournament name and PlayerName does for a surname.
 *
 * MEASURED, NOT ELLIPSISED. The slot reports how much room it HAS (flex: 1 on
 * a wrapper is what makes onLayout report the room rather than the text's own
 * width), the string is measured in the face it is actually set in, and the
 * type shrinks by exactly the ratio needed. No "…", which is the house rule
 * everywhere text is fitted here: a cut word is a word nobody can read.
 *
 * THE SIZE IS COMPUTED IN UNSCALED POINTS while the measurement is scaled, so
 * the answer holds at any Dynamic Type setting — a floor in unscaled points
 * would let the text overflow again on a large-text phone, which is the bug
 * this pattern exists to prevent.
 */
/* `wrapAtFloor`: when even `min` cannot fit the text, wrap it instead of
   cutting it — the schedule's compact rows, where a five-set score can leave
   a name 20pt on a small phone. Off by default: a title that wraps is a
   different design from one that shrinks, and every other caller chose the
   shrink. */
export function FitText({ children, style, min = 8, track = 0, wrapAtFloor = false, align = 'left', alt = null }) {
  const [avail, setAvail] = useState(null)
  const flat = StyleSheet.flatten(style) || {}
  const family = flat.fontFamily || 'Archivo_500Medium'
  const size = flat.fontSize || 13
  /* `alt`: a SHORTER NAME for the same thing, used only when the real one
     cannot fit above the floor — the tournament's short name, set by an
     admin. It is the name ladder's rule in one more place: shrink first, and
     shorten rather than clip, because below `min` the backstop starts
     truncating and this project does not print "…"
     (feedback_name_shortening_ladder). A caller with no short name passes
     nothing and gets the old behaviour. */
  let text = String(children ?? '')
  let fontSize = size
  let floored = false
  const fit = (str) => {
    const need = textWidth(str, family, size) + str.length * track
    // A point of slack: kerning is not in the tables, and a string right on
    // the line should shrink rather than gamble.
    const room = avail - 1
    if (need <= room) return { size, floored: false }
    const want = (size * room) / need
    return { size: Math.max(min, want), floored: want < min }
  }
  if (avail != null) {
    let got = fit(text)
    if (got.floored && alt && String(alt) !== text) {
      const shorter = fit(String(alt))
      // Only if the short name actually buys something: a short name as long
      // as the real one is not a shortening, it is a second spelling.
      if (!shorter.floored || shorter.size > got.size) {
        text = String(alt)
        got = shorter
      }
    }
    fontSize = got.size
    floored = got.floored
  }
  const wrap = wrapAtFloor && floored
  return (
    <View style={[u.fitSlot, align === 'center' && u.fitCenter, align === 'right' && u.fitRight]} onLayout={e => setAvail(e.nativeEvent.layout.width)}>
      {/* adjustsFontSizeToFit is the backstop for where iOS measures the face
          a hair wider than the tables do — it takes the last step rather than
          an ellipsis. The box must never have slack when it is on, or iOS
          shrinks to its floor regardless; the arithmetic above guarantees the
          text is at or over the width. */}
      {/* TRACKING SHRINKS WITH THE TYPE. `track` is a fixed add-on per
          character, so a font shrunk by ratio r would still carry the full
          tracking and overflow by (1 - r) of it — 16pt on a 30-letter court
          name. Scaled with the size, width is proportional and the ratio
          above is exact; it is also the eyebrow's own rule (tracking in
          proportion to its size). */}
      <Text style={[style, align === 'center' && { textAlign: 'center' }, align === 'right' && { textAlign: 'right' }, fontSize !== size && { fontSize, ...(track ? { letterSpacing: track * (fontSize / size) } : null) }]}
            numberOfLines={wrap ? undefined : 1} adjustsFontSizeToFit={!wrap} minimumFontScale={0.5}>
        {text}
      </Text>
    </View>
  )
}

/* THE TOURNAMENT NAME, ON ONE LINE — shrunk to fit, never wrapped.
 *
 * "Guadalajara Open" broke across two lines on the dashboard (owner,
 * 2026-09-15) and the reason was the reader's text size, not the name: at 19pt
 * it measures 122pt against ~180pt of room, but every point of Dynamic Type
 * scales the glyphs while the tier stamp beside it stays 76pt wide, so past
 * about 1.3x the longer names run out of row and wrap. A two-line title pushes
 * the card's meta row down and leaves the tour badge stranded beside a
 * half-empty second line.
 *
 * MEASURED, the same way player names are (measure.js): the slot reports how
 * much room it HAS, the name is measured in the face it is actually set in, and
 * the type shrinks by exactly the ratio needed. Two details that matter:
 *
 * - The size is computed in UNSCALED points while the measurement is scaled,
 *   so the answer holds at any text size — a floor in unscaled points would
 *   let the name overflow again on a large-text phone, which is the bug.
 * - No ellipsis. A cut tournament name is the same loss as a cut surname, and
 *   the house rule rules it out (see PlayerName below).
 */
const TITLE_SIZE = 19
const TITLE_FACE = 'SairaCondensed_700Bold'
// 0.01em, as the style sets it — small, but 35 characters of it is 6pt.
const TITLE_TRACK = TITLE_SIZE * 0.01

function CardTitle({ name }) {
  const [avail, setAvail] = useState(null)
  const inks = useCardSkin()
  let fontSize = TITLE_SIZE
  if (avail != null) {
    const need = textWidth(name, TITLE_FACE, TITLE_SIZE)
      + String(name ?? '').length * TITLE_TRACK
    // A point of slack: kerning is not in the tables.
    const room = avail - 1
    if (need > room) fontSize = Math.max(8, (TITLE_SIZE * room) / need)
  }
  return (
    /* A ROW, so the Text is sized by its content rather than stretched to the
       slot. adjustsFontSizeToFit below is the backstop for where iOS measures
       the face a hair wider than the tables do — and given a box with slack it
       shrinks to its floor regardless of whether the text fits (the seed badge
       became a speck that way), so it must never be handed one. */
    <View style={u.titleSlot} onLayout={e => setAvail(e.nativeEvent.layout.width)}>
      <Text style={[u.title, { color: inks.ink }, fontSize !== TITLE_SIZE && {
        fontSize, lineHeight: leading(fontSize + 1),
      }]} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.5}>
        {name}
      </Text>
    </View>
  )
}

const u = StyleSheet.create({
  card: {
    backgroundColor: C.card,
    borderWidth: 1, borderColor: C.border, borderRadius: R.md,
    flexDirection: 'row', overflow: 'hidden', ...SHADOW,
  },
  /* The HORIZONTAL padding is the website's — '14px 16px 14px 20px' with gap
     9, from the source — and it stays, because it is what lines every card's
     text up down the screen.
     THE VERTICAL IS OURS NOW: 10 and a gap of 7, down from 14 and 9 (owner,
     2026-09-16), which takes a full card from 88pt to 78. The site's 14 was
     drawn for a card with four rows in it; this one has two, and the tier
     plate that sets the first row is 31pt of artwork that does not need 14pt
     of air above it to read. */
  body: { flex: 1, paddingTop: 10, paddingRight: 16, paddingBottom: 10, paddingLeft: 16, gap: 7 },
  bodyLink: { gap: 9 },
  /* See `compact` at TourCard. Vertical only: the horizontal padding is what
     lines every card's text up down the column.
     3 AND 3, DOWN FROM 7 AND 5 IN TWO PASSES (owner, 2026-09-16), which takes
     a week card from 64.5pt to 54.5.
     THIS IS THE FLOOR, and the arithmetic says why: of the 52.5pt inside the
     border, 25.5 is the tier plate and 18 is the city's line, so 9 is all the
     air there is and 3 of it sits above a stamp that is artwork against the
     card's own edge. Anything further has to come off the stamp — CAP_SMALL
     and SMALL in this file — or off the type, not off the spacing. */
  bodyTight: { paddingTop: 3, paddingBottom: 3, gap: 3 },
  bodyLinkTight: { gap: 3 },
  // Centred ON the corner, so it reads as pinned to the card rather than
  // floating beside it. Half out and half in: the badge's own ring closes the
  // card's border where it crosses it.
  corner: { position: 'absolute', top: -9, right: -9 },
  /* EQUAL ON ALL FOUR SIDES — one number, which is the whole reason the
     artwork is cropped to its ink (see TierBadge). It was 7 and 3, and even
     that understated it: the air either side was mostly inside the PNG.
     The pill's radius, not the card's: this is the pill's replacement, and
     the card's 12 would read as a lozenge on a strip this size. 8 is the step
     between (owner, 2026-09-16, "round the pill corners a bit more"), and it
     is still short of the card's, so the plate reads as a tag on the card
     rather than a second card inside it.

     PADDING 8, UP FROM 6, at the same ask. One number is one number: widening
     the margin widens and heightens the plate by the same 4pt, which is what
     "on both width and height" means once the artwork is cropped to its ink
     and the plate is only as big as what it holds. */
  stamp: { borderRadius: 8, padding: 8 },
  /* THE SET STAMP is a row of two words, and its padding is NOT symmetric.
     Symmetric padding centres the text's BOX; what a reader sees is its INK,
     and an italic's ink is not centred in its box — the wordmark's W leans
     off its left bearing, the number's 0 carries a right one, and the line
     box places the baseline nearer its top than its bottom.

     Measured on the rendered badge with symmetric padding (7 and 9): ink
     8.5pt from the top against 7.0 from the bottom, and 11.0 from the left
     against 9.5 from the right. These four numbers move each pair to its
     own average — 7.75 and 10.25 — and hold the plate at the 31pt the image
     badge was, so nothing around it shifts.

     The horizontal pair is font metrics and travels; the vertical pair is
     baseline placement inside a line box, which iOS and react-native-web do
     not agree on to the point. If the caps look high or low on a phone, the
     two numbers to move are here and they still have to sum to 14. */
  stampSet: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingTop: 6.25,
    paddingBottom: 7.75,
    paddingLeft: 8.25,
    paddingRight: 9.75,
  },
  stampMark: { fontFamily: 'Kanit_900Black_Italic' },
  stampNum: { fontFamily: 'Kanit_300Light_Italic' },
  // Padding scales with the lettering, and with it: 6pt of air around 9pt of
  // caps is a border, not a margin, and 3 around 13.5 is the same mistake
  // inverted. So the base number moves with the full-size one — 3 -> 4, times
  // SMALL — rather than being retuned on its own.
  stampSmall: { borderRadius: 6, padding: 4 * SMALL },
  // As titleSlot, for FitText: the flex is what makes onLayout report the
  // room there IS rather than the room the text took.
  fitSlot: { flex: 1, minWidth: 0, flexDirection: 'row', alignItems: 'center' },
  fitCenter: { justifyContent: 'center' },
  fitRight: { justifyContent: 'flex-end' },
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  // The spare width of the title row, which is what CardTitle measures to know
  // how much the name may use. It replaced a flex:1 spacer that sat AFTER the
  // name: that pushed the tier stamp to the right edge just the same, but it
  // left the name content-sized, so onLayout could only report how much room
  // the name had taken — never how much there was.
  titleSlot: { flex: 1, minWidth: 0, flexDirection: 'row', alignItems: 'center' },
  // Stacked, and right-aligned so the two tours' plates share an edge — they
  // are different widths (a 250's line is shorter than a 1000's) and a
  // centred pair would read as two things rather than one block.
  stampStack: { gap: 4, alignItems: 'flex-end' },
  // Two small plates on a combined week card: the gap scales with them, or the
  // air between reads as wider than either plate is tall.
  stampStackTight: { gap: 2 },
  // 1.18rem at 16px root = 18.9; lineHeight 1.05; letterSpacing 0.01em.
  title: {
    fontFamily: TITLE_FACE, fontSize: TITLE_SIZE, lineHeight: leading(20),
    letterSpacing: TITLE_TRACK, color: C.ink, flexShrink: 1,
  },
  footer: { borderTopWidth: 1, borderTopColor: C.border, paddingTop: 9, marginTop: 1 },
  /* THE PLATES, AND NOTHING AROUND THEM. The band they used to sit in is gone
     (see CardNav), so this is the component's root: a row the caller drops
     where it likes. `flex: none` because it goes on a row beside text that
     shrinks — the plates are a fixed width and the WORDS give way, never the
     controls. */
  navPlates: { flexDirection: 'row', gap: 3, flexShrink: 0 },
  /* A PLATE, leaning the tier marks' 8 degrees. Radius 3 rather than the
     stamp's 8: a skewed rounded rectangle reads as a wobble past a few points,
     and a lower-third's plates are cut square. The label is a CHILD of this
     view, so it inherits the lean instead of being skewed on its own — which
     is what keeps the word's baseline true to its plate.
     leading() ON THE HEIGHT, so the plate grows with the reader's type rather
     than cropping it — the same rule `badge` follows, and the other half of
     the centring fix at navText. */
  navPlate: {
    height: leading(26), paddingHorizontal: 13, borderRadius: 3,
    alignItems: 'center', justifyContent: 'center',
    transform: [{ skewX: '-8deg' }],
  },
  navPlateDead: { opacity: 0.55 },
  /* 13pt SEMIBOLD at the body step, sentence case, NO letterSpacing: tracking
     is what made the previous pass shout, and a leaning word wants its letters
     close or the slant reads as a wobble. No skew here — the plate carries it.
     AND NO lineHeight, which is what was pushing the word low in its plate
     (owner, 2026-09-16). This is the lesson `badgeText` already carries forty
     lines down, and the spec's `leading(17)` walked straight into it: on iOS a
     lineHeight sinks the glyphs toward the bottom of their line box, so a
     flex-centred box centres the BOX and the ink still sits low. Dropped, the
     font's own line is what the box centres, and the word sits on the middle.
     The plate's leading() height is what keeps Dynamic Type safe instead. */
  navText: {
    fontFamily: 'SairaCondensed_600SemiBold', fontSize: 13,
  },
  /* A compact card's second row is a footer only in the structural sense — it
     sits beside the body's link rather than inside it (see the note at the
     call site) — so it takes no rule and no padding of its own: the body's own
     gap is the space, and the card reads as one block. */
  footerPlain: {},
  chip: {
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: R.pill,
    alignSelf: 'flex-start',
  },
  /* 26x17 with radius 3, from .pos-badge. The fixed width is the point — but
     it has to be fixed IN THE READER'S UNITS, not in ours. At a larger text
     size the digits grow and 28pt stopped holding three of them, so a rank of
     108 came out as "1…" — which is not a smaller number, it is a different
     one. The box scales with the type it contains. */
  /* 26×17 — a step down from the site's 26×17-at-desktop equivalent the
     app had grown to (28×18), at the owner's ask. The entry chip below
     takes the SAME height rule, so the two never differ by a point. */
  badge: {
    width: leading(26), height: leading(16), borderRadius: 3, borderWidth: 1,
    paddingVertical: 0, alignItems: 'center', justifyContent: 'center',
  },
  badgeGap: { width: leading(26) },
  flagSlot: { flexDirection: 'row', alignItems: 'center', gap: leading(3) },
  nameSlot: { flex: 1, minWidth: 0, flexDirection: 'row', alignItems: 'center', gap: 4 },
  flagGlyph: { fontSize: 13, lineHeight: leading(16) },
  // Same footprint as a flag, so a name never moves because a country is
  // missing. 4:3, like the flag images the site uses.
  flagEmpty: {
    width: leading(16), height: leading(12), borderRadius: 2,
    borderWidth: 1, borderColor: C.borderOn, backgroundColor: 'transparent',
  },
  // .dh-category: 0.65rem/700/uppercase, 0.06em tracking, radius 4, 2px 6px.
  tourBadge: { borderRadius: 4, paddingHorizontal: 6, paddingVertical: 2, alignSelf: 'flex-start' },
  /* The pair, as one control: segments butted together in a rounded shell,
     the live one filled with its tour's tint and the other outlined. */
  tourSwitch: { flexDirection: 'row', borderRadius: R.pill, overflow: 'hidden', borderWidth: 1, borderColor: C.borderOn },
  tourSeg: { paddingHorizontal: 8, paddingVertical: 3, alignItems: 'center', justifyContent: 'center' },
  tourSegOff: { backgroundColor: 'transparent' },
  tourText: { fontFamily: 'Archivo_700Bold', fontSize: 10, lineHeight: leading(14), letterSpacing: 0.6 },
  /* The entry chip is CONTENT-WIDTH and therefore does NOT reuse `badge`.
     It was composed as [badge, entryChip] with width:undefined to cancel the
     28pt, and that does not cancel it — "WC" came out as "W..". This is the
     fourth fixed-width cell in this project to truncate or wrap its contents
     rather than grow; the lesson each time is that the override belongs in a
     standalone style, not layered on top of a fixed one. */
  /* THE SAME BOX AS `badge`, bar its width. It shares badgeText already, so
     the only thing that made a "Q" render unlike a seed was this height: a
     FIXED 18 against badge's leading(18). The text inside scales with the
     reader's setting and the box did not, so past ~1.1 the glyph was
     squeezed and sat off its line while the seed beside it stayed perfect.
     Padding scales for the same reason — a chip that grows taller but not
     wider crowds its own letters. Width stays content-driven, which is the
     one difference from `badge` and the reason this style exists. */
  entryChip: {
    height: leading(16), borderRadius: 3, borderWidth: 1,
    paddingHorizontal: leading(5), paddingVertical: 0,
    alignItems: 'center', justifyContent: 'center', marginLeft: leading(6),
  },
  /* NO lineHeight: on iOS a lineHeight sinks the digits toward the bottom
     of the box (the draw's pills taught this); the font's own line, centred
     by the box, puts them on its middle. */
  badgeText: { fontFamily: 'Archivo_700Bold', fontSize: 11 },
  // A three-letter code at the size that keeps its pill as wide as a WC's.
  badgeTextWide: { fontSize: 9.5 },
})


/* The bracket's position badge — and the entry chip beside it.
 *
 * TWO BADGES, NOT ONE. The site shows a qualifier as `114` `Q`: the position
 * badge always carries a NUMBER, and the entry type is a separate chip. The
 * first version of this collapsed them, printing `Q` INSTEAD of the number,
 * which quietly deleted the ranking of every qualifier in the draw.
 *
 * The number is the player's rank WITHIN THIS FIELD (see drawRanks.js) — seeds
 * keep their seed, everyone else is numbered after them. It is NOT the world
 * ranking, which is a different and larger number.
 *
 * Fixed footprint so a two- and a three-digit number leave the name starting at
 * the same x down the whole column — most of what makes a bracket scan.
 */
export function PosBadge({ seed, drawRank }) {
  const text = seed != null ? String(seed) : drawRank != null ? String(drawRank) : ''
  if (!text) return <View style={u.badgeGap} />
  const t = seed != null ? BADGE.seeded : BADGE.unseeded
  return (
    <View style={[u.badge, { backgroundColor: t.bg, borderColor: t.line }]}>
      {/* A NUMBER IS NEVER ELLIPSISED. "1…" could be anything from 100 to 199,
          so it misinforms rather than abbreviates — shrink instead, which is
          the same rule the name ladder follows for the same reason. */}
      {/* No adjustsFontSizeToFit: on iOS it shrinks to its floor whenever the
          box has any slack, and the digits became a speck in an empty box.
          The box already scales with the type (leading), and three digits
          measure 19.7pt against its 26pt interior, so nothing needs to give. */}
      <Text style={[u.badgeText, { color: t.fg }]} numberOfLines={1}>{text}</Text>
    </View>
  )
}

/* Q for a qualifier, WC for a wildcard, LL for a lucky loser — whatever the
   feed says, rendered only when there is one. Sits AFTER the name, as on the
   site, so it never pushes the names out of alignment. */
/* THE SHEET'S CODES, AS IT PRINTS THEM — WC, Q, PR, LL, SE — with one
   exception. "A" is ALTERNATE, and a bare letter reads as an initial rather
   than as a status (owner, 2026-09-20). Spelled out, and only that one:
   every other code is two letters and already says itself.

   A three-letter label is set a size down so its pill stays the width of the
   two-letter ones beside it, which was the owner's condition. Measured
   rather than eyeballed: "ALT" at 9.5pt is 18.6pt wide against "WC" at 11pt
   at 18.7pt, so the pair is as near identical as the face allows. */
const ENTRY_LABEL = { A: 'ALT' }

export function EntryChip({ entryType }) {
  if (!entryType) return null
  const code = String(entryType).toUpperCase()
  const label = ENTRY_LABEL[code] || code
  return (
    <View style={[u.entryChip, { backgroundColor: BADGE.qual.bg, borderColor: BADGE.qual.line }]}>
      <Text style={[u.badgeText, label.length > 2 && u.badgeTextWide, { color: BADGE.qual.fg }]} numberOfLines={1}>
        {label}
      </Text>
    </View>
  )
}


/* ATP or WTA, as a badge.
 *
 * NOT COSMETIC. A combined event puts two draws called exactly "US Open" in the
 * same list, and without this the only thing separating them is a 5pt accent
 * stripe — so the dashboard, the leagues list and a league's draw list each
 * showed two identical rows and left you to guess which was the men's. The site
 * never has this problem because it prints the tour on every card.
 *
 * Gender is 'M' or 'F' in the API; anything else renders nothing rather than
 * guessing a tour.
 */
/* THE TIER, SHORT ENOUGH TO SIT IN A PILL. `category` is "WTA 500",
   "ATP 250" or "Grand Slam"; the tour half is already the badge, so only the
   level is left to say. A Slam has no number and "Grand Slam" is wider than
   the name of most tournaments, so it contracts to GS — the abbreviation the
   sport itself uses. Anything unrecognised returns null and the badge reads
   exactly as it did. */
export function levelLabel(category) {
  const c = (category || '').trim()
  if (!c) return null
  if (/grand\s*slam/i.test(c)) return 'GS'
  const n = c.match(/(\d{3,4})\s*$/)
  return n ? n[1] : null
}

export function TourBadge({ gender, tour, discipline, level, style }) {
  /* GENDER COMES FROM THE DRAW, AND DOUBLES HAS NO DRAW. A doubles schedule
     row carries draw_id null — we hold no doubles bracket — so `gender` is
     null and this rendered nothing at all: the US Open doubles final sat on
     the schedule with no tour on it while the singles beside it had a pill
     (owner, 2026-09-12). The row's own `tour` says ATP or WTA, and mixed
     doubles is neither, which is what `discipline` is for. */
  const key = discipline === 'mixed' ? 'X'
    : gender || (tour === 'WTA' ? 'F' : tour === 'ATP' ? 'M' : null)
  const t = TOUR[key]
  if (!t) return null
  return (
    <View style={[u.tourBadge, { backgroundColor: t.bg }, style]}>
      <Text style={[u.tourText, { color: t.fg }]}>{level ? `${t.label} ${level}` : t.label}</Text>
    </View>
  )
}


/* THE TWO HALVES OF ONE EVENT, as a switch.
 *
 * A Grand Slam is two draws under one name, and a reader looking at the men's
 * standings usually wants the women's next. Where TourBadge states which
 * draw this is, this offers the other one: the current tour reads as the
 * badge does, the other as an outline waiting to be pressed.
 *
 * `draws` is the pair (either order); the switch sorts men first so it never
 * swaps sides between events. With fewer than two it renders the plain badge,
 * because there is nothing to switch to.
 *
 * `style` reaches BOTH shapes. TourBadge carries alignSelf:'flex-start' for
 * the stacked layouts it usually sits in, so a caller placing it on a row's
 * centre line has to override that — and would otherwise find the override
 * silently dropped on the one-draw event, which is the case least likely to
 * be the one on screen while the code is being written.
 */
/* THE NAV BAR'S OWN RULES ARE NOT THIS APP'S. A header button on iOS 26 is
   drawn inside a system capsule — the same one behind "Back" — and with the
   pill hard against the screen's right edge that capsule ran off the display
   (owner, 2026-09-14).

   THE MARGIN IS SPLIT, and that is the whole of the second correction. The
   capsule is drawn around our view INCLUDING its margin, so a right-only
   margin does not move the capsule off the edge — it moves the pill left
   inside it, by exactly the margin. Four a side buys the same room and leaves
   the pill where the capsule centres it.

   The radius matches the capsule rather than fighting it: one rounded shape
   inside another, not a square-ish tag inside a capsule.

   Exported because two screens put a tour pill in a header and a third will;
   a copy in each is a copy to forget. */
export const headerTour = { marginHorizontal: 4, borderRadius: 999 }

/* `pairLevel`: does the level ride along when there are TWO pills?
 *
 * On its own a pill is the only place the tier can read — the standings header
 * asked for "WTA 500" there outright (owner, 2026-09-12). Doubled it says
 * nothing it did not already say: "ATP GS" beside "WTA GS" spends ~22pt a side
 * repeating the one fact both halves share, and on the draw's header that is
 * width taken straight out of the tournament's name, which was reading
 * "US Op…" (owner, 2026-09-15). The tours differ; the tier does not.
 *
 * Default true, so the screens that asked for the level keep it. The switch
 * still decides what "a pair" IS — the caller states the policy, not the
 * arithmetic, or the two drift apart on an event with a malformed sibling.
 */
export function TourSwitch({ draws, currentId, onPick, showLevel, pairLevel = true, style }) {
  const pair = [...(draws || [])]
    .filter(d => d && TOUR[d.gender])
    .sort((a, b) => (a.gender === 'M' ? 0 : 1) - (b.gender === 'M' ? 0 : 1))
  if (pair.length < 2) {
    const only = pair[0] ?? (draws || [])[0]
    return <TourBadge gender={only?.gender} style={style}
                      level={showLevel ? levelLabel(only?.category) : null} />
  }
  return (
    <View style={[u.tourSwitch, style]}>
      {pair.map(d => {
        const t = TOUR[d.gender]
        const on = d.id === currentId
        return (
          <Pressable key={d.id} onPress={on ? undefined : () => onPick?.(d)} hitSlop={6}
                     accessibilityRole="button" accessibilityState={{ selected: on }}
                     accessibilityLabel={`${t.label} draw`}
                     style={[u.tourSeg, on ? { backgroundColor: t.bg } : u.tourSegOff]}>
            <Text style={[u.tourText, { color: on ? t.fg : C.muted }]}>
              {showLevel && pairLevel && levelLabel(d.category)
                ? `${t.label} ${levelLabel(d.category)}` : t.label}
            </Text>
          </Pressable>
        )
      })}
    </View>
  )
}

/* A country flag in a FIXED slot — or an empty box when there isn't one.
 *
 * The box is not decoration: a withheld nationality is meaningful. Neutral
 * athletes carry no flag, and the order of play drops the country whenever
 * space is tight, so "no flag" is a state the row has to be able to show. An
 * outlined empty box says "no country here" the way the site does; rendering
 * nothing at all would instead shift every name after it out of line.
 *
 * `slots` is the number of flags this ENTRY needs — a doubles pair needs two —
 * and both players in a match are given the same value so their names still
 * start at the same x.
 */
export function FlagSlot({ codes, slots = 1 }) {
  const list = (codes && codes.length ? codes : [null]).slice(0, slots)
  while (list.length < slots) list.push(null)
  // Widths scale with the reader's text size, as the glyph does: fixed points
  // here let a large-text phone draw the second flag over the gap and hard
  // against the name.
  return (
    <View style={[u.flagSlot, { width: slots * leading(17) + (slots - 1) * leading(3) }]}>
      {list.map((c, i) => {
        const glyph = flagEmoji(c)
        return glyph
          ? <Text key={i} style={u.flagGlyph}>{glyph}</Text>
          : <View key={i} style={u.flagEmpty} />
      })}
    </View>
  )
}


/* A player's name, shortened in the order a person would shorten it.
 *
 * "…" IS THE LAST RESORT, not the first. Truncation destroys the part that
 * identifies the player — "Juan Manuel Cerú…" says less than "Cerúndolo" does,
 * in more space — so the rungs are walked in order and shrinking only starts
 * once the words have run out:
 *
 *   1. initials for the given names   2. surname alone
 *   3. shrink the type                4. and only then, ellipsis
 *
 * MEASURED, NOT ASKED. The first version leaned on onTextLayout to notice a
 * truncation and step down a rung; on iOS it never noticed, and "Nishesh B…"
 * shipped. This one measures every rung from the font's own metrics
 * (measure.js) against the width the row actually gave it, and picks the
 * longest that fits. The same arithmetic runs on iOS and in the web harness,
 * so what is checked here is what ships.
 *
 * The wrapper takes the row's spare width (flex: 1) precisely so onLayout
 * reports how much room there IS, not how much the text happened to use.
 */
/* `after`: a mark that rides immediately after the name — the pick's 🤞 —
   inside the slot, so it follows the name rather than drifting to the row's
   far edge. Its width comes off what the name may use. */
const AFTER_PX = 24
/* `flags`: a doubles pair's two countries, one BEFORE EACH NAME (owner,
   2026-09-17) - "🇺🇸 Stearns / 🇺🇸 Stephens" - rather than two flags side by
   side ahead of the pair. The glyphs are not in the metric tables, so each
   takes a fixed allowance off the room before the rungs are measured. */
const FLAG_PX = 20
/* "A / B" with each side's flag ahead of its name; a side with no country
   keeps its name alone. pairForms joins with " / ", so the split is exact. */
export function withFlags(text, glyphs) {
  const parts = String(text).split(' / ')
  return parts.map((part, i) => (glyphs[i] ? `${glyphs[i]} ${part}` : part)).join(' / ')
}
export function PlayerName({ name, doubles = false, shrinkOnly = false, style, after = null, flags = null }) {
  /* shrinkOnly: a USERNAME. It cannot be initialised or reduced to a surname —
     "koounderpressure" has neither — but the last two rungs still apply:
     shrink first, and only then "…". Truncating a handle is the same loss as
     truncating a surname; it is the identifier. */
  const forms = useMemo(
    () => (shrinkOnly ? [String(name || '')] : doubles ? pairForms(name) : nameForms(name)),
    [name, doubles, shrinkOnly],
  )
  const [avail, setAvail] = useState(null)
  const flat = StyleSheet.flatten(style) || {}
  const family = flat.fontFamily || 'Archivo_500Medium'
  const size = flat.fontSize || 15

  const glyphs = doubles && flags ? flags.map(c => flagEmoji(c)) : []
  let text = forms[0]
  let fontSize = size
  let flagged = glyphs.length > 0
  if (avail != null) {
    // A point of slack: kerning is not in the tables, and a name that is
    // right on the line should shorten rather than gamble.
    const room = avail - 1 - (after ? AFTER_PX : 0)
    /* THE FLAGS GO BEFORE THE TYPE SHRINKS (owner, 2026-09-17): every rung
       is tried wearing the flags, then every rung without them, and only
       then does the shortest rung shrink. A flag is decoration; a name that
       cannot be read is not a name. */
    const flagW = glyphs.filter(Boolean).length * FLAG_PX * (size / 15)
    const rungs = glyphs.length
      ? [...forms.map(f => ({ f, flagged: true })), ...forms.map(f => ({ f, flagged: false }))]
      : forms.map(f => ({ f, flagged: false }))
    const fits = rungs.find(r => textWidth(r.f, family, size) + (r.flagged ? flagW : 0) <= room)
    if (fits) {
      text = fits.f
      flagged = fits.flagged
    } else {
      flagged = false
      // Every rung is too wide: the shortest one, shrunk TO FIT. No floor and
      // never "…" — a cut name is a name nobody can read, and the user ruled
      // it out outright (2026-09-04, "Auger-Aliassi…" on a four-set row).
      text = forms[forms.length - 1]
      const need = textWidth(text, family, size)
      fontSize = Math.max(6, (size * room) / need)
    }
  }

  return (
    <View style={u.nameSlot} onLayout={e => setAvail(e.nativeEvent.layout.width)}>
      {/* adjustsFontSizeToFit is the backstop: the arithmetic above uses our
          own metrics tables, and where iOS measures the face a hair wider the
          native shrink takes the last step rather than an ellipsis. */}
      <Text style={[style, { flexShrink: 1 }, fontSize !== size && { fontSize }]} numberOfLines={1}
            adjustsFontSizeToFit minimumFontScale={0.3}>
        {flagged ? withFlags(text, glyphs) : text}
      </Text>
      {after}
    </View>
  )
}
