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

const SLAM = {
  australian: require('./assets/logos/slams/slam_Australian.png'),
  roland: require('./assets/logos/slams/slam_RolandGarros.svg-dark.png'),
  wimbledon: require('./assets/logos/slams/slam_Wimbledon.svg-dark.png'),
  us: require('./assets/logos/slams/slam_US.svg-dark.png'),
  atp: require('./assets/logos/slams/slam_atp.png'),
  wta: require('./assets/logos/slams/slam_wta.png'),
}

// The 250 stamp is flat navy (#050053) — 1.1:1 on a dark card, i.e. invisible.
// It is the only one needing a variant; 500 is silver and 1000 gold, both of
// which read fine either way. Same reasoning, same artwork, as the web.
const ATP = {
  250: require('./assets/logos/categorystamps_250-dark.png'),
  500: require('./assets/logos/categorystamps_500.png'),
  1000: require('./assets/logos/categorystamps_1000.png'),
}

const WTA = {
  250: require('./assets/logos/250k-tag.png'),
  500: require('./assets/logos/500k-tag.png'),
  1000: require('./assets/logos/1000k-tag.png'),
}

export function tierStamp({ tour, tier, name }) {
  const isATP = String(tour || 'ATP').toUpperCase() === 'ATP'
  const isSlam = /slam|gs|grand/i.test(String(tier || ''))

  if (isSlam) {
    const n = (name || '').toLowerCase()
    if (n.includes('australian')) return SLAM.australian
    if (n.includes('roland') || n.includes('french')) return SLAM.roland
    if (n.includes('wimbledon')) return SLAM.wimbledon
    if (n.includes('us open')) return SLAM.us
    return isATP ? SLAM.atp : SLAM.wta
  }

  // "ATP 500" -> 500. Anything unrecognised is a 250, matching the web.
  const num = String(tier || '').replace(/\D/g, '') || '250'
  const table = isATP ? ATP : WTA
  return table[num] || table['250']
}
