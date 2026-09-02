/* "GS" / "1000" / "500" / "250" — the site's categoryShort, verbatim, so the
   app names a tier the same way the site's draw nav and history page do. */
export function categoryShort(cat) {
  if (!cat) return ''
  if (cat.includes('Slam') || cat.includes('slam')) return 'GS'
  if (cat.includes('1000')) return '1000'
  if (cat.includes('500')) return '500'
  return '250'
}
export const tourLabel = (t) => `${t?.gender === 'M' ? 'ATP' : 'WTA'}${categoryShort(t?.category) ? ' ' + categoryShort(t?.category) : ''}`
