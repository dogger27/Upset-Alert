function slamLogo(name) {
  const n = (name || '').toLowerCase()
  if (n.includes('australian')) return '/logos/slams/slam_Australian.png'
  if (n.includes('roland') || n.includes('french')) return '/logos/slams/slam_RolandGarros.svg.png'
  if (n.includes('wimbledon')) return '/logos/slams/slam_Wimbledon.svg.png'
  if (n.includes('us open')) return '/logos/slams/slam_US.svg.png'
  return null  // will fall back to tour-specific generic
}

export function TierBadge({ tour = 'ATP', tier = '500', name = '', size = 'md', style = {} }) {
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
    src = slamLogo(name) || (isATP ? '/logos/slams/slam_atp.png' : '/logos/slams/slam_wta.svg')
  } else {
    const tierNum = String(tier).replace(/\D/g, '') || '250'
    src = isATP
      ? `/logos/categorystamps_${tierNum}.png`
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
