// IOC 3-letter → ISO 2-letter, for flag-icons class names.
//
// Lived inside BracketView until the schedule page needed it too. Kept in one
// place deliberately: two copies of a country table drift, and the failure is
// silent — a player simply loses their flag on one screen and keeps it on
// another.
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
}

export function nationalityIso2(nat) {
  if (!nat) return null
  return IOC_TO_ISO2[nat.toUpperCase()] ?? (nat.length === 2 ? nat.toUpperCase() : null)
}

/**
 * Split "Nuno BORGES POR" / "[13] Andrey RUBLEV" into its parts.
 *
 * The sheets print "Firstname SURNAME NAT", with the surname in caps and the
 * nationality as a trailing IOC code — so the caps are what identify the
 * surname, not word position. Names like "David VEGA HERNANDEZ" and
 * "Nicole MELICHAR-MARTINEZ" have multi-word surnames, which is why this takes
 * every trailing capitalised token rather than just the last one.
 */
export function splitPlayerName(raw) {
  if (!raw) return { seed: null, first: '', last: '', nat: null }
  let s = raw.trim()

  const seedMatch = s.match(/^((?:\[[^\]]*\]\s*)+)/)
  const seed = seedMatch ? seedMatch[1].trim() : null
  if (seedMatch) s = s.slice(seedMatch[0].length).trim()

  // A trailing three-letter capital is only a country when a SURNAME precedes
  // it, because the format is "Firstname SURNAME NAT" and the surname is in
  // caps too. Shape alone cannot tell "Orlando LUZ" from "Nuno BORGES POR",
  // and reading LUZ as a country leaves the player called "Orlando".
  //
  // Tested structurally rather than against IOC_TO_ISO2, which is a flag table
  // and holds only the countries that have one — matching on it would strand
  // "BDI" and "MNE" inside the names of the players it cannot draw.
  let nat = null
  const natMatch = s.match(/\s([A-Z]{3})$/)
  if (natMatch) {
    const before = s.slice(0, natMatch.index).split(/\s+/).filter(Boolean)
    if (before.some(w => w === w.toUpperCase() && /[A-Z]/.test(w))) {
      nat = natMatch[1]
      s = before.join(' ')
    }
  }

  const words = s.split(/\s+/).filter(Boolean)
  const lastIdx = words.findIndex(w => w === w.toUpperCase() && /[A-Z]/.test(w))
  if (lastIdx === -1) return { seed, first: '', last: s, nat }

  return {
    seed,
    first: words.slice(0, lastIdx).join(' '),
    last: words.slice(lastIdx).join(' '),
    nat,
  }
}
