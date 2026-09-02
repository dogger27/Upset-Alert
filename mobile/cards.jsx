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
import { Image, StyleSheet, Text, View } from 'react-native'
import { leading } from './fontScale.js'
import { tierStamp } from './logos'
import { flagEmoji } from './flags'
import { CardLink } from './ui'
import { textWidth } from './measure.js'
import { nameForms, pairForms } from './names'
import { BADGE, C, R, S, SHADOW, T, TOUR } from './theme'

/* The accent bar: a 4px vertical gradient from the tour's 500 to its 700.
   Six stacked bands rather than a real gradient — expo-linear-gradient is a
   native module and another build, and across four points nobody can tell. */
export function AccentBar({ from, to, width = 4 }) {
  const steps = 6
  return (
    <View style={{ width }}>
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
   and a square ATP stamp carry the same visual weight. */
export function TierBadge({ tour, tier, name, width = 76, height = 32 }) {
  const src = tierStamp({ tour, tier, name })
  if (!src) return null
  return <Image source={src} style={{ width, height }} resizeMode="contain" />
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
export function TourCard({ tour, tier, name, children, footer, href }) {
  const isATP = String(tour || 'ATP').toUpperCase() === 'ATP'
  const body = (
    <>
        <View style={u.titleRow}>
          {/* The tour reads BEFORE the name, not under it: a combined event
              supplies two draws both called "US Open" and the tier stamp
              beside them is the same logo for both, so the badge is the first
              thing that tells them apart and belongs where the eye starts. */}
          <TourBadge gender={isATP ? 'M' : 'F'} />
          <Text style={u.title} numberOfLines={2}>{name}</Text>
          <View style={{ flex: 1 }} />
          <TierBadge tour={tour} tier={tier} name={name} />
        </View>
        {children}
    </>
  )
  return (
    <View style={u.card}>
      <AccentBar from={isATP ? C.atp : C.wta} to={isATP ? C.atpDeep : C.wtaDeep} />
      <View style={u.body}>
        {href
          ? <CardLink href={href} style={u.bodyLink} pressedOpacity={0.75}>{body}</CardLink>
          : <View style={u.bodyLink}>{body}</View>}
        {footer ? <View style={u.footer}>{footer}</View> : null}
      </View>
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
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  // 1.18rem at 16px root = 18.9; lineHeight 1.05; letterSpacing 0.01em.
  title: {
    fontFamily: 'SairaCondensed_700Bold', fontSize: 19, lineHeight: leading(20),
    // No flex:1 — the title now sits in a COLUMN, where flex:1 would stretch it
    // vertically and push the tour badge to the bottom of the card.
    letterSpacing: 0.19, color: C.ink, flexShrink: 1,
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
  badge: {
    width: leading(28), height: leading(18), borderRadius: 3, borderWidth: 1,
    alignItems: 'center', justifyContent: 'center',
  },
  badgeGap: { width: leading(28) },
  flagSlot: { flexDirection: 'row', alignItems: 'center', gap: 3 },
  nameSlot: { flex: 1, minWidth: 0 },
  flagGlyph: { fontSize: 13, lineHeight: leading(16) },
  // Same footprint as a flag, so a name never moves because a country is
  // missing. 4:3, like the flag images the site uses.
  flagEmpty: {
    width: 16, height: 12, borderRadius: 2,
    borderWidth: 1, borderColor: C.borderOn, backgroundColor: 'transparent',
  },
  // .dh-category: 0.65rem/700/uppercase, 0.06em tracking, radius 4, 2px 6px.
  tourBadge: { borderRadius: 4, paddingHorizontal: 6, paddingVertical: 2, alignSelf: 'flex-start' },
  tourText: { fontFamily: 'Archivo_700Bold', fontSize: 10, lineHeight: leading(14), letterSpacing: 0.6 },
  /* The entry chip is CONTENT-WIDTH and therefore does NOT reuse `badge`.
     It was composed as [badge, entryChip] with width:undefined to cancel the
     28pt, and that does not cancel it — "WC" came out as "W..". This is the
     fourth fixed-width cell in this project to truncate or wrap its contents
     rather than grow; the lesson each time is that the override belongs in a
     standalone style, not layered on top of a fixed one. */
  entryChip: {
    height: 18, borderRadius: 3, borderWidth: 1, paddingHorizontal: 5,
    alignItems: 'center', justifyContent: 'center', marginLeft: 6,
  },
  badgeText: { fontFamily: 'Archivo_700Bold', fontSize: 11, lineHeight: leading(13) },
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
export function TourBadge({ gender, style }) {
  const t = TOUR[gender]
  if (!t) return null
  return (
    <View style={[u.tourBadge, { backgroundColor: t.bg }, style]}>
      <Text style={[u.tourText, { color: t.fg }]}>{t.label}</Text>
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
  return (
    <View style={[u.flagSlot, { width: slots * 17 + (slots - 1) * 3 }]}>
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
export function PlayerName({ name, doubles = false, style }) {
  const forms = useMemo(
    () => (doubles ? pairForms(name) : nameForms(name)),
    [name, doubles],
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
    const room = avail - 1
    const fits = forms.find(f => textWidth(f, family, size) <= room)
    if (fits) {
      text = fits
    } else {
      // Every rung is too wide: the shortest one, shrunk — but no further than
      // 60%, past which the ellipsis is the lesser evil.
      text = forms[forms.length - 1]
      const need = textWidth(text, family, size)
      fontSize = Math.max(size * 0.6, (size * room) / need)
    }
  }

  return (
    <View style={u.nameSlot} onLayout={e => setAvail(e.nativeEvent.layout.width)}>
      <Text style={[style, fontSize !== size && { fontSize }]} numberOfLines={1}>
        {text}
      </Text>
    </View>
  )
}
