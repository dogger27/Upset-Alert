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
  // Added 2026-08-25: every code our own data carries had to be in here, and
  // these were not — Maria TIMOFEEVA (UZB) sat on the Monterrey order of play
  // beside an outlined empty box, which is the marker for a country the sheet
  // WITHHELD. A missing row in this table says the same thing as a withheld
  // nationality and cannot be told apart on the page.
  UZB:'UZ', ARM:'AM', JOR:'JO', LBN:'LB', QAT:'QA', MNE:'ME', AND:'AD',
  BDI:'BI', ESA:'SV', VAN:'VU', DEU:'DE',
  // Singapore, under both codes: SIN is the IOC's, SGP the ISO one the
  // WTA's own Singapore Open sheet printed for its wildcards (2026-09-19).
  // Neither was here, so a Singaporean flew no flag, and the mobile app —
  // which reads a trailing code as a country only if it is in this table —
  // printed "SGP" as the last word of her name.
  SIN:'SG', SGP:'SG',
  // Added 2026-09-24 with the Tennis Explorer country names the server could
  // not map (doubles specialists flew no flag): every code it now produces.
  MDA:'MD', ALG:'DZ', IRI:'IR', KUW:'KW', ZIM:'ZW', KEN:'KE', BOT:'BW',
  GHA:'GH', CIV:'CI', LIE:'LI', MOZ:'MZ', NCA:'NI', ANG:'AO', ANT:'AG',
  AZE:'AZ', BEN:'BJ', BER:'BM', FIJ:'FJ', LBA:'LY', NAM:'NA', NEP:'NP',
  PAN:'PA', SEN:'SN', SYR:'SY',
  // Folded in from H2HPanel.jsx, which kept its own copy of this table and
  // drifted both ways: it had these ten and lacked Singapore, so the same
  // player flew a flag on one screen and not the other (2026-09-19). The
  // panel imports this table now. Web only: mobile/flags.js doubles as the
  // app's test for "is this last word a country" (names.js sheetName), and
  // HON/PAN are surnames there — "Priscilla HON" would lose hers.
  ALG:'DZ', MDA:'MD', AZE:'AZ', KGZ:'KG', TJK:'TJ', TKM:'TM', BIZ:'BZ',
  PAN:'PA', NCA:'NI', HON:'HN',
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

  // A WHOLE TEAM IN ONE STRING. An unresolved doubles side offers a choice
  // between two pairs, and each pair reaches us as a single printed name:
  // "[1] ARRIBAGE FRA / GUINARD FRA". Read as one person it is nonsense — the
  // country strip only ever reaches the END of the string, so Winston-Salem
  // 2026-08-26 published "ARRIBAGE FRA / GUINARD", with Arribage's nationality
  // marooned inside his partner's name and Guinard's flag flown for the pair.
  // Everything below assumes one person, so split first and let each partner
  // answer for themselves — the same per-segment rule the backend uses.
  //
  // `nat` is deliberately null for a team: two people, and a side can carry
  // one flag. Better none than one partner's flown for both.
  if (s.includes('/')) {
    const parts = s.split('/').map(x => x.trim()).filter(Boolean)
    if (parts.length > 1) {
      const members = parts.map(p => splitPlayerName(p))
      return {
        seed,
        first: '',
        last: members.map(m => m.last || m.first).filter(Boolean).join(' / '),
        nat: null,
        members,
      }
    }
  }

  // A trailing three-letter capital is only a country when a SURNAME precedes
  // it, because the format is "Firstname SURNAME NAT" and the surname is in
  // caps too. Shape alone cannot tell "Orlando LUZ" from "Nuno BORGES POR",
  // and reading LUZ as a country leaves the player called "Orlando".
  //
  // Tested structurally rather than against IOC_TO_ISO2, which is a flag table
  // and holds only the countries that have one — matching on it would strand
  // "BDI" and "MNE" inside the names of the players it cannot draw.
  //
  // STRIP EVERY ONE OF THEM, not just the last. A Winston-Salem sheet printed
  // "[6] Dhakshineswar SURESH IND ANY"; taking one token read ANY as the
  // country — which draws no flag — and left the name as "SURESH IND". The
  // country is the one nearest the name, so the last strip wins.
  let nat = null
  for (;;) {
    const natMatch = s.match(/\s([A-Z]{3})$/)
    if (!natMatch) break
    const before = s.slice(0, natMatch.index).split(/\s+/).filter(Boolean)
    if (!before.some(w => w === w.toUpperCase() && /[A-Z]/.test(w))) break
    nat = natMatch[1]
    s = before.join(' ')
  }

  const words = s.split(/\s+/).filter(Boolean)
  // AN INITIAL IS UPPERCASE WITHOUT BEING A SURNAME. The WTA abbreviates the
  // teams in an unresolved doubles slot — "C. Bucsa / N. Melichar-Martinez OR
  // S. Cabezas Dominguez / M. Gomez Pezuela Cano" — and "C." passes a bare
  // caps test, so the whole "C. Bucsa" came back as the surname. The "or" line
  // meant to print four surnames printed all four printed names instead, and
  // Guadalajara 2026-09-16 ran it off the right edge of the card at both widths
  // ("…Gomez Pezuela Can"). Same exception the backend's readers already make
  // (sofascore_doubles._sheet_people: "H. Nys"): a surname has two letters and
  // is not a run of initials.
  const isSurname = w => w === w.toUpperCase() && /[A-Z]/.test(w)
    && (w.match(/\p{L}/gu) || []).length >= 2 && !/^(?:\p{Lu}\.-?)+$/u.test(w)
  const lastIdx = words.findIndex(isSurname)
  if (lastIdx === -1) {
    // NO CAPITALISED SURNAME, so this is not a sheet name. A slot resolved from
    // the bracket carries the draw's spelling — "Frances Tiafoe", not the
    // sheet's "Frances TIAFOE" — and returning the whole string as the surname
    // left `first` empty, which quietly disabled the initial rung of the name
    // ladder: full, initial and surname were all the same string, so a name too
    // long for its column went straight to shrinking the type. That is why
    // Tiafoe was set smaller than Gauff beside him with room to spare.
    // Last word is the surname, the same reading the backend uses.
    if (words.length > 1) {
      return { seed, first: words.slice(0, -1).join(' '), last: words[words.length - 1], nat }
    }
    return { seed, first: '', last: s, nat }
  }

  return {
    seed,
    first: words.slice(0, lastIdx).join(' '),
    last: words.slice(lastIdx).join(' '),
    nat,
  }
}

/**
 * The mark written after a name: its seeding, and how the player ENTERED.
 *
 * A seed sent as a field beats the sheet's digits (a resolved name comes from
 * the bracket and has no brackets to parse), but the field is only a NUMBER.
 * Letting it replace the whole printed mark threw away everything else the
 * sheet said: Korea Open 2026-09-22 printed "[WC] [1] Jelena OSTAPENKO LAT"
 * and the card read "OSTAPENKO [1]" (Fernandez's "[WC] [6]" went the same way
 * the day before). So every printed tag that is not a number survives, and
 * the field supplies the number.
 */
export function seedMark(printed, seedField) {
  if (seedField == null) return printed || null
  const tags = (printed || '').match(/\[[^\]]*\]/g) || []
  const words = tags.filter(t => !/^\[\s*\d+\s*\]$/.test(t))
  return [...words, `[${seedField}]`].join(' ')
}
