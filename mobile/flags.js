/*
 * Country flags, as emoji.
 *
 * The IOC -> ISO2 table is COPIED from frontend/src/utils/flags.js, whose own
 * comment warns that two copies of a country table drift and that the failure
 * is silent — a player simply loses their flag on one screen and keeps it on
 * another. It is copied anyway, deliberately: mobile/ shares no code with
 * frontend/ yet (extraction to a package is explicitly deferred), and the
 * alternative is importing across two build systems. If a code is added there,
 * add it here.
 *
 * Emoji rather than the site's flag-icons sprite: iOS draws regional-indicator
 * pairs natively at any size, so there is no asset to bundle and nothing to
 * rasterise. A missing table row yields NO flag, which is the same thing the
 * site shows for a withheld nationality — so absence is never a wrong flag.
 */
export const IOC_TO_ISO2 = {
  AUS:'AU', USA:'US', GBR:'GB', FRA:'FR', GER:'DE', ESP:'ES', ITA:'IT',
  RUS:'RU', CAN:'CA', JPN:'JP', CHN:'CN', KOR:'KR', ARG:'AR', BRA:'BR',
  SUI:'CH', AUT:'AT', BEL:'BE', NED:'NL', DEN:'DK', NOR:'NO', SWE:'SE',
  FIN:'FI', POL:'PL', CZE:'CZ', SVK:'SK', HUN:'HU', ROU:'RO', BUL:'BG',
  SRB:'RS', CRO:'HR', SLO:'SI', BIH:'BA', MKD:'MK', GRE:'GR', TUR:'TR',
  POR:'PT', GEO:'GE', KAZ:'KZ', UKR:'UA', BLR:'BY', LAT:'LV', LTU:'LT',
  EST:'EE', ISR:'IL', RSA:'ZA', EGY:'EG', MAR:'MA', TUN:'TN', NGR:'NG',
  CHI:'CL', COL:'CO', PER:'PE', URU:'UY', VEN:'VE', ECU:'EC', BOL:'BO',
  PAR:'PY', MEX:'MX', IND:'IN', PAK:'PK', THA:'TH', VIE:'VN', INA:'ID',
  MAS:'MY', PHI:'PH', TPE:'TW', HKG:'HK', NZL:'NZ', BAH:'BS', DOM:'DO',
  HAI:'HT', PUR:'PR', TTO:'TT', JAM:'JM', BAR:'BB', GUA:'GT', CRC:'CR',
  MON:'MC', LUX:'LU', ISL:'IS', IRL:'IE', CYP:'CY', MLT:'MT',
  // Added 2026-08-25: every code our own data carries had to be in here, and
  // these were not — Maria TIMOFEEVA (UZB) sat on the Monterrey order of play
  // beside an outlined empty box, which is the marker for a country the sheet
  // WITHHELD. A missing row in this table says the same thing as a withheld
  // nationality and cannot be told apart on the page.
  UZB:'UZ', ARM:'AM', JOR:'JO', LBN:'LB', QAT:'QA', MNE:'ME', AND:'AD',
  BDI:'BI', ESA:'SV', VAN:'VU', DEU:'DE',
}

export function nationalityIso2(nat) {
  if (!nat) return null
  return IOC_TO_ISO2[nat.toUpperCase()] ?? (nat.length === 2 ? nat.toUpperCase() : null)
}

/* ISO2 -> the two regional indicator symbols that render as that flag.
   'A' is U+1F1E6, so each letter maps by its offset from 'A'. */
export function flagEmoji(nat) {
  const iso = nationalityIso2(nat)
  if (!iso || iso.length !== 2) return ''
  const base = 0x1F1E6
  const a = iso.charCodeAt(0) - 65
  const b = iso.charCodeAt(1) - 65
  if (a < 0 || a > 25 || b < 0 || b > 25) return ''
  return String.fromCodePoint(base + a) + String.fromCodePoint(base + b)
}
