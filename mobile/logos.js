/*
 * The tier and slam stamps, ported from the website's TierBadge.
 *
 * These are real artwork, and they are most of why the site's cards look
 * designed rather than assembled. RN requires static require() paths — the
 * bundler resolves them at build time — so this is a lookup table rather than
 * the string concatenation the web does.
 *
 * The WTA tags and the WTA slam mark were SVG on the web; rasterised at 3x for
 * a retina phone.
 */

import ASPECT from './tierStampAspect.js'

const SLAM = {
  australian: require('./assets/logos/slams/slam_Australian.png'),
  roland: require('./assets/logos/slams/slam_RolandGarros.svg-dark.png'),
  wimbledon: require('./assets/logos/slams/slam_Wimbledon.svg-dark.png'),
  us: require('./assets/logos/slams/slam_US.svg-dark.png'),
  atp: require('./assets/logos/slams/slam_atp.png'),
  wta: require('./assets/logos/slams/slam_wta.png'),
}

/* NUMBER INLINE, not stacked under the wordmark. The ATP ships these with the
   tier number on a second line below "ATP"; the WTA tag beside it on the same
   dashboard sets the two side by side at one height, and two stamps built to
   different rules read as a mistake rather than as two brands (owner,
   2026-09-15). tools/gen-tier-stamps.py takes each apart at the blank band
   between the rows and re-sets the number to the right of the wordmark, at its
   cap height and on its baseline.

   "MASTERS" comes off the 1000 in the process. Inline it runs 7:1, which
   `contain` would then shrink until its wordmark was half the size of the
   250's beside it — and "WTA 1000" does not spell out its tier either.

   The 250 is built from the -dark variant: the shipped 250 is flat navy
   (#050053), 1.1:1 on a dark card, i.e. invisible. It is the only one needing
   one; 500 is silver and 1000 gold, both of which read either way. Same
   reasoning, same artwork, as the web. Originals stay put as the generator's
   input. */
const ATP = {
  250: require('./assets/logos/atp-250-inline.png'),
  500: require('./assets/logos/atp-500-inline.png'),
  1000: require('./assets/logos/atp-1000-inline.png'),
}

/* LETTERING ONLY. The tags as shipped are opaque rounded rectangles in the
   WTA's own tier colours — purple, teal, gold — and the dashboard now paints
   the tour's colour behind every stamp, so a baked-in tier colour was the one
   thing on the card arguing with it. tools/gen-tour-tag-plates.py strips each
   tag to its wordmark and number (alpha = how much of the pixel the letters
   covered) on the same canvas, so the plate colour comes from theme.js and the
   tag keeps the margin that holds it to the ATP stamps' size. Originals kept
   beside them: they are the generator's input. */
const WTA = {
  250: require('./assets/logos/250k-tag-plate.png'),
  500: require('./assets/logos/500k-tag-plate.png'),
  1000: require('./assets/logos/1000k-tag-plate.png'),
}

/* THE SLAM TEST, EXPORTED. TierBadge needs the same answer — the slam crests
   are left exactly as the tournaments draw them, so they take no tour-coloured
   plate (owner, 2026-09-15) — and a second copy of this regex somewhere else
   is a second copy to forget. */
export const isSlamTier = tier => /slam|gs|grand/i.test(String(tier || ''))

/* `{ src, aspect }`, not just the source. The tier artwork is cropped to its
   lettering, so the badge sizes it by its own shape (TierBadge) rather than
   fitting it into a box — and the aspect ratios are generated beside the
   artwork, because Image.resolveAssetSource can answer this on iOS but does
   not exist in react-native-web, where asking red-boxed the visual harness.

   A crest has no aspect: it is left as its tournament draws it and keeps the
   fixed box it always had. One branch decides which of the two a stamp is, so
   the source and the way it is measured can never disagree. */
export function tierStamp({ tour, tier, name }) {
  const isATP = String(tour || 'ATP').toUpperCase() === 'ATP'

  if (isSlamTier(tier)) {
    const n = (name || '').toLowerCase()
    const crest = n.includes('australian') ? SLAM.australian
      : n.includes('roland') || n.includes('french') ? SLAM.roland
      : n.includes('wimbledon') ? SLAM.wimbledon
      : n.includes('us open') ? SLAM.us
      : isATP ? SLAM.atp : SLAM.wta
    return { src: crest, aspect: null }
  }

  // "ATP 500" -> 500. Anything unrecognised is a 250, matching the web.
  const num = String(tier || '').replace(/\D/g, '') || '250'
  const table = isATP ? ATP : WTA
  const tour_ = isATP ? 'atp' : 'wta'
  return {
    src: table[num] || table['250'],
    aspect: ASPECT[tour_][num] ?? ASPECT[tour_]['250'],
  }
}
