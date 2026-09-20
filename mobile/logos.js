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


/* EVERY PATH BELOW IS `badge/`, WHICH IS THE DISPLAY COPY (owner,
 * 2026-09-20: the badges took too long to load). The tournaments' own
 * downloads are print-resolution — Roland Garros arrives at 1280x1280 and
 * 218 KB for a mark drawn 51pt tall — and the cost that showed was not the
 * bytes but the DECODE: 6.5 million pixels per crest, six crests to a
 * dashboard. tools/gen-badge-crests.py writes each one at the size a badge
 * can draw it; the originals stay in slams/ as its input and the archive.
 * Point these at slams/ again and the delay comes back. */
const SLAM = {
  australian: require('./assets/logos/badge/slam_Australian.png'),
  roland: require('./assets/logos/badge/slam_RolandGarros.svg-dark.png'),
  wimbledon: require('./assets/logos/badge/slam_Wimbledon.svg-dark.png'),
  /* THE FLAME, WITHOUT "us open" UNDER IT. The card's title already says
     which tournament this is, in 19pt type at the other end of the same row,
     so the crest was saying it a second time in a smaller voice. Cut at the
     blank band across the artwork by gen-tier-stamps.py; the original stays
     beside it as that script's input, and it is the only crest with a
     wordmark to separate. */
  us: require('./assets/logos/badge/slam_US-mark.png'),
  atp: require('./assets/logos/badge/slam_atp.png'),
  wta: require('./assets/logos/badge/slam_wta.png'),
}

/* THE TIER STAMPS' ARTWORK IS GONE FROM HERE (owner, 2026-09-20). Six PNGs —
   the ATP's wordmark with its number re-set inline, the WTA's tags stripped to
   their lettering — are now two words in Kanit; tierStamp below returns the
   words. tools/gen-tier-stamps.py still builds the files and the US crest, so
   a revert is one import away, and the tours' original downloads stay where
   they were as its input. */

/* THE SLAM TEST, EXPORTED. TierBadge needs the same answer — the slam crests
   are left exactly as the tournaments draw them, so they take no tour-coloured
   plate (owner, 2026-09-15) — and a second copy of this regex somewhere else
   is a second copy to forget. */
export const isSlamTier = tier => /slam|gs|grand/i.test(String(tier || ''))

/* WHICH OF AN EVENT'S STAMPS ARE DRAWN, in one place.
 *
 * A Slam's crest is the EVENT's mark — the same artwork whichever tour — so a
 * combined Slam draws it once; every other tier stamp names a tour, and a
 * combined week draws both. TourCard had this inline until the schedule's
 * tournament heading needed the same answer (owner, 2026-09-20), and two
 * copies of a rule this quiet is one copy too many.
 *
 * Takes the event's draws (a draw IS a gender) and returns the ones to draw,
 * in the order given.
 */
export function stampsFor(draws) {
  const list = (draws || []).filter(Boolean)
  if (list.length > 1 && isSlamTier(list[0].category)) return list.slice(0, 1)
  return list
}

/* A STAMP IS EITHER A CREST OR A PIECE OF LETTERING.
 *
 * `{ crest }` — a Slam's mark, left exactly as its tournament draws it, in the
 * fixed box it has always had. It is a picture and stays one.
 *
 * `{ mark, num }` — a tier stamp, which is two words: the tour's wordmark and
 * the tier's number. It used to be one PNG per tour per tier, six files built
 * by tools/gen-tier-stamps.py out of the tours' own artwork. It is SET now, in
 * Kanit 900 italic and 300 italic (owner, 2026-09-20) — which takes the last
 * image a card has to fetch and decode before it can paint, and the generated
 * aspect table with it, because text sizes itself.
 *
 * One branch decides which kind a stamp is, so no caller can draw a crest as
 * words or words in a crest's box. */
export function tierStamp({ tour, tier, name }) {
  const isATP = String(tour || 'ATP').toUpperCase() === 'ATP'

  if (isSlamTier(tier)) {
    const n = (name || '').toLowerCase()
    const crest = n.includes('australian') ? SLAM.australian
      : n.includes('roland') || n.includes('french') ? SLAM.roland
      : n.includes('wimbledon') ? SLAM.wimbledon
      : n.includes('us open') ? SLAM.us
      : isATP ? SLAM.atp : SLAM.wta
    return { crest }
  }

  // "ATP 500" -> 500. Anything unrecognised is a 250, matching the web.
  return { mark: isATP ? 'ATP' : 'WTA', num: String(tier || '').replace(/\D/g, '') || '250' }
}
