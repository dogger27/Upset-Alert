import { useTheme } from '../../store/theme'

/* Slam marks whose ink is too dark to read on a dark card, and the variant that
   replaces it. Measured against the card, not guessed at: US Open navy lands at
   1.37:1, Roland Garros green at 1.6 and Wimbledon purple at 1.92 — the US Open
   wordmark was effectively invisible, which is what prompted this.
   The variants are the same artwork with only LIGHTNESS raised, hue and
   saturation untouched, so each stays its own colour and reaches 4.6:1. Alpha
   is preserved pixel by pixel, so the antialiased edges lift with the rest and
   nothing acquires a halo. Australian (4.88) and the tour marks (6.4) already
   read and are left alone — a variant they do not need is a second file to
   keep in step. */
const SLAM_DARK = new Set([
  '/logos/slams/slam_US.svg.png',
  '/logos/slams/slam_RolandGarros.svg.png',
  '/logos/slams/slam_Wimbledon.svg.png',
])

function slamLogo(name, dark) {
  const n = (name || '').toLowerCase()
  let src = null
  if (n.includes('australian')) src = '/logos/slams/slam_Australian.png'
  else if (n.includes('roland') || n.includes('french')) src = '/logos/slams/slam_RolandGarros.svg.png'
  else if (n.includes('wimbledon')) src = '/logos/slams/slam_Wimbledon.svg.png'
  else if (n.includes('us open')) src = '/logos/slams/slam_US.svg.png'
  if (!src) return null  // will fall back to tour-specific generic
  return dark && SLAM_DARK.has(src) ? src.replace('.png', '-dark.png') : src
}

export function TierBadge({ tour = 'ATP', tier = '500', name = '', size = 'md', style = {} }) {
  const { theme } = useTheme()
  const isATP = String(tour).toUpperCase() === 'ATP'
  const isSlam = /slam|gs|grand/i.test(String(tier))

  // Fixed bounding box per size — constrains wide WTA pills and keeps ATP stamps at the same visual weight
  const boxes = {
    sm: { width: 88, height: 38 },
    md: { width: 108, height: 48 },
    lg: { width: 136, height: 60 },
  }
  const box = boxes[size] || boxes.md

  let src
  if (isSlam) {
    src = slamLogo(name, theme === 'dark') || (isATP ? '/logos/slams/slam_atp.png' : '/logos/slams/slam_wta.svg')
  } else {
    const tierNum = String(tier).replace(/\D/g, '') || '250'
    // The 250 stamp is a flat navy (#050053) — 1.1:1 on a dark card, i.e.
    // invisible. It is the only one that needs a variant: 500 is silver and
    // 1000 is gold, both of which read fine either way. The variant is the
    // same artwork with the navy replaced by --atp-text, so alpha and shape
    // are untouched and it lands at 8.2:1.
    const darkStamp = theme === 'dark' && tierNum === '250' ? '-dark' : ''
    src = isATP
      ? `/logos/categorystamps_${tierNum}${darkStamp}.png`
      : `/logos/${tierNum}k-tag.svg`
  }

  return (
    <img
      src={src}
      alt={`${isATP ? 'ATP' : 'WTA'} ${isSlam ? 'Grand Slam' : tier}`}
      style={{ width: box.width, height: box.height, objectFit: 'contain', objectPosition: 'center', display: 'block', ...style }}
    />
  )
}
