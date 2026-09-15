/*
 * The website's card, rebuilt for React Native.
 *
 * Ported from components/design/TournamentCard.jsx, SurfacePill.jsx and
 * TierBadge.jsx — anatomy and numbers, not an impression of them. The first
 * attempt at this screen used the site's COLOURS but invented its own layout,
 * and the result looked assembled rather than designed. Every measurement here
 * comes from the source.
 */

import { useMemo, useState } from 'react'
import { Image, Pressable, StyleSheet, Text, View } from 'react-native'
import { leading } from './fontScale.js'
import { isSlamTier, tierStamp } from './logos'
import { flagEmoji } from './flags'
import { CardLink } from './ui'
import { textWidth } from './measure.js'
import { nameForms, pairForms } from './names'
import { BADGE, C, R, SHADOW, T, TOUR } from './theme'

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

/* Dot plus label, the site's exact fills. The dot is what makes it a surface
   rather than another grey chip — "(i)" for indoor is stripped, matching the
   web, because indoor hard is still hard. */
export function SurfacePill({ surface }) {
  const key = String(surface || '').toLowerCase().replace(/\s*\(.*?\)/g, '').trim()
  const s = C.surfaces[key] || C.surfaces.hard
  return (
    <View style={[u.pill, { backgroundColor: s.bg }]}>
      <View style={[u.dot, { backgroundColor: s.dot }]} />
      <Text style={[T.tiny, { color: s.fg, letterSpacing: 0.3 }]}>{s.label}</Text>
    </View>
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

export function TierBadge({ tour, tier, name }) {
  const { src, aspect } = tierStamp({ tour, tier, name })
  if (!src) return null
  // A crest keeps the square-ish box it has always had, and no plate: it is
  // the tournament's own mark, not a tier stamp (see logos.js).
  if (!aspect) return <Image source={src} style={CREST} resizeMode="contain" />
  const key = String(tour || 'ATP').toUpperCase() === 'ATP' ? 'M' : 'F'
  return (
    <View style={[u.stamp, { backgroundColor: TOUR[key].plate }]}>
      {/* contain as well as the computed width: the arithmetic is right, and
          if it ever stops being right the artwork letterboxes inside the plate
          instead of stretching, which is the failure you can see. */}
      <Image source={src} style={{ width: aspect * CAP, height: CAP }} resizeMode="contain" />
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
 *   THE TIER AS WORDS, not artwork. The stamp was the tallest thing on a card
 *   that is otherwise a line under a name — 27pt for a tier plate, 51 for a
 *   Slam crest against 19pt of type — so Last Week stood a third taller than
 *   its neighbours on the strength of a picture. Each tour keeps its own ink,
 *   so the label still carries the tour where the plate used to; a combined
 *   Slam says it once, both halves being the same words and it being the
 *   event's tier rather than either draw's.
 *
 *   A TIGHTER BOX. Padding 14 and a 9pt gap are the site's numbers for a card
 *   you can act on; on a two-line card they were a third of its height
 *   (owner, 2026-09-15). Halved, and the horizontal padding left alone so
 *   every card down the column still starts its text at the same x.
 */
export function TourCard({ draws, name, children, footer, href, corner, compact }) {
  const list = (draws || []).filter(Boolean)
  const combined = list.length > 1
  const isATP = list[0]?.gender !== 'F'
  /* A Slam's crest is the EVENT's mark, the same artwork for either tour, so
     stacking it twice would print the same picture twice. Every other tier
     stamp names a tour and both are shown. */
  const oneTier = combined && isSlamTier(list[0]?.category)
  const stamps = oneTier ? list.slice(0, 1) : list
  const tiers = !compact ? null
    : oneTier
      ? [{ id: 'event', text: list[0].category, color: C.muted }]
      : list.filter(d => d.category).map(d => ({
        id: d.id, text: d.category, color: TOUR[d.gender === 'F' ? 'F' : 'M'].text,
      }))
  const skin = combined
    ? { card: C.card, line: C.border, rule: C.border }
    : { card: TOUR[isATP ? 'M' : 'F'].card, line: TOUR[isATP ? 'M' : 'F'].line,
        rule: TOUR[isATP ? 'M' : 'F'].plate }
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
          {tiers ? (
            <View style={u.tierRow}>
              {tiers.map(t => (
                <Text key={t.id} style={[u.tierText, { color: t.color }]} numberOfLines={1}>
                  {t.text}
                </Text>
              ))}
            </View>
          ) : (
            <View style={u.stampStack}>
              {stamps.map(d => (
                <TierBadge key={d.id} tour={d.gender === 'F' ? 'WTA' : 'ATP'}
                           tier={d.category} name={name} />
              ))}
            </View>
          )}
        </View>
        {children}
    </>
  )
  return (
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
        <View style={[u.body, compact && u.bodyTight]}>
          {href
            ? <CardLink href={href} style={[u.bodyLink, compact && u.bodyLinkTight]}
                        pressedOpacity={0.75}>{body}</CardLink>
            : <View style={[u.bodyLink, compact && u.bodyLinkTight]}>{body}</View>}
          {footer ? <View style={[u.footer, { borderTopColor: skin.rule }]}>{footer}</View> : null}
        </View>
      </View>
      {/* box-none, not none: the slot itself must never swallow a tap meant
          for the card under it — the card is a link to the draw, and a hole in
          that target at the corner would be a dead spot nobody could
          explain — but what it HOLDS may be pressable in its own right. */}
      {corner ? <View style={u.corner} pointerEvents="box-none">{corner}</View> : null}
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
// Between two tours' tier words on one line.
const S_TIER_GAP = 8

const TITLE_SIZE = 19
const TITLE_FACE = 'SairaCondensed_700Bold'
// 0.01em, as the style sets it — small, but 35 characters of it is 6pt.
const TITLE_TRACK = TITLE_SIZE * 0.01

function CardTitle({ name }) {
  const [avail, setAvail] = useState(null)
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
      <Text style={[u.title, fontSize !== TITLE_SIZE && {
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
  // '14px 16px 14px 20px' with gap 9, from the source.
  body: { flex: 1, paddingTop: 14, paddingRight: 16, paddingBottom: 14, paddingLeft: 16, gap: 9 },
  bodyLink: { gap: 9 },
  // See `compact` at TourCard. Vertical only: the horizontal padding is what
  // lines every card's text up down the column.
  bodyTight: { paddingTop: 7, paddingBottom: 7, gap: 5 },
  bodyLinkTight: { gap: 5 },
  // Centred ON the corner, so it reads as pinned to the card rather than
  // floating beside it. Half out and half in: the badge's own ring closes the
  // card's border where it crosses it.
  corner: { position: 'absolute', top: -9, right: -9 },
  /* EQUAL ON ALL FOUR SIDES — one number, which is the whole reason the
     artwork is cropped to its ink (see TierBadge). It was 7 and 3, and even
     that understated it: the air either side was mostly inside the PNG.
     The pill's radius, not the card's: this is the pill's replacement, and
     the card's 12 would read as a lozenge on a strip this size. */
  stamp: { borderRadius: 5, padding: 6 },
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
  /* The tier in words, where a week card cannot afford the artwork. No shrink:
     the title beside it is what gives way (CardTitle measures what it is
     given), and a tier abbreviated to "ATP 5…" would be a worse answer than a
     shorter name. */
  tierRow: { flexDirection: 'row', gap: S_TIER_GAP, flexShrink: 0 },
  tierText: { fontFamily: 'Archivo_700Bold', fontSize: 11, letterSpacing: 0.6 },
  // 1.18rem at 16px root = 18.9; lineHeight 1.05; letterSpacing 0.01em.
  title: {
    fontFamily: TITLE_FACE, fontSize: TITLE_SIZE, lineHeight: leading(20),
    letterSpacing: TITLE_TRACK, color: C.ink, flexShrink: 1,
  },
  footer: { borderTopWidth: 1, borderTopColor: C.border, paddingTop: 9, marginTop: 1 },
  pill: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    paddingLeft: 8, paddingRight: 9, paddingVertical: 3, borderRadius: R.pill,
  },
  dot: { width: 7, height: 7, borderRadius: 3.5 },
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
export function EntryChip({ entryType }) {
  if (!entryType) return null
  return (
    <View style={[u.entryChip, { backgroundColor: BADGE.qual.bg, borderColor: BADGE.qual.line }]}>
      <Text style={[u.badgeText, { color: BADGE.qual.fg }]} numberOfLines={1}>
        {String(entryType).toUpperCase()}
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
export function PlayerName({ name, doubles = false, shrinkOnly = false, style, after = null }) {
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

  let text = forms[0]
  let fontSize = size
  if (avail != null) {
    // A point of slack: kerning is not in the tables, and a name that is
    // right on the line should shorten rather than gamble.
    const room = avail - 1 - (after ? AFTER_PX : 0)
    const fits = forms.find(f => textWidth(f, family, size) <= room)
    if (fits) {
      text = fits
    } else {
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
        {text}
      </Text>
      {after}
    </View>
  )
}
