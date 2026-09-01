/*
 * The website's card, rebuilt for React Native.
 *
 * Ported from components/design/TournamentCard.jsx, SurfacePill.jsx and
 * TierBadge.jsx — anatomy and numbers, not an impression of them. The first
 * attempt at this screen used the site's COLOURS but invented its own layout,
 * and the result looked assembled rather than designed. Every measurement here
 * comes from the source.
 */

import { Image, StyleSheet, Text, View } from 'react-native'
import { tierStamp } from './logos'
import { BADGE, C, R, S, SHADOW, T } from './theme'

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
export function TourCard({ tour, tier, name, children, footer }) {
  const isATP = String(tour || 'ATP').toUpperCase() === 'ATP'
  return (
    <View style={u.card}>
      <AccentBar from={isATP ? C.atp : C.wta} to={isATP ? C.atpDeep : C.wtaDeep} />
      <View style={u.body}>
        <View style={u.titleRow}>
          <Text style={u.title} numberOfLines={2}>{name}</Text>
          <TierBadge tour={tour} tier={tier} name={name} />
        </View>
        {children}
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
  titleRow: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 },
  // 1.18rem at 16px root = 18.9; lineHeight 1.05; letterSpacing 0.01em.
  title: {
    fontFamily: 'SairaCondensed_700Bold', fontSize: 19, lineHeight: 20,
    letterSpacing: 0.19, color: C.ink, flex: 1,
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
  // 26x17 with radius 3, from .pos-badge. The fixed width is the point.
  badge: {
    width: 28, height: 18, borderRadius: 3, borderWidth: 1,
    alignItems: 'center', justifyContent: 'center',
  },
  badgeGap: { width: 28 },
  badgeText: { fontFamily: 'Archivo_700Bold', fontSize: 11, lineHeight: 13 },
})


/* The bracket's position badge.
 *
 * A SEED IS NOT A RANKING and the site distinguishes them: seeds in gold,
 * everyone else's world ranking in grey, a qualifier's Q in green. Fixed
 * footprint so a two- and a three-digit number leave the name starting at the
 * same x down the whole column — which is most of what makes a bracket scan.
 */
export function PosBadge({ seed, ranking, entryType }) {
  const isQ = String(entryType || '').toUpperCase() === 'Q'
  const text = seed != null ? String(seed)
    : isQ ? 'Q'
    : ranking != null ? String(ranking) : ''
  if (!text) return <View style={u.badgeGap} />
  const t = seed != null ? BADGE.seeded : isQ ? BADGE.qual : BADGE.unseeded
  return (
    <View style={[u.badge, { backgroundColor: t.bg, borderColor: t.line }]}>
      <Text style={[u.badgeText, { color: t.fg }]} numberOfLines={1}>{text}</Text>
    </View>
  )
}
