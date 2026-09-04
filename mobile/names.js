/*
 * Shortening a player's name to fit, in the order a person would do it.
 *
 * THE LADDER — and there is NO ellipsis rung (user, 2026-09-04):
 *   1. initials for the given names   "Juan Manuel Cerúndolo" -> "J. M. Cerúndolo"
 *   2. drop the given names entirely  -> "Cerúndolo"
 *   3. shrink the type, as far as it has to go
 *
 * Truncation is never an option because it destroys the one part of the name
 * that identifies the player — "Juan Manuel Cerú…" tells you less than
 * "Cerúndolo" does, in more space.
 *
 * WHERE THE SURNAME STARTS is a guess, and there is no rule that is right for
 * every name. The one used here: the surname is the final token, plus any
 * lowercase particle run immediately before it ("van de", "de la", "von").
 * Everything earlier is a given name.
 *
 *   "Botic van de Zandschulp" -> B. van de Zandschulp -> van de Zandschulp
 *   "Juan Manuel Cerúndolo"   -> J. M. Cerúndolo      -> Cerúndolo
 *   "Facundo Díaz Acosta"     -> F. D. Acosta         -> Acosta
 *
 * The last is imperfect — the family name is really "Díaz Acosta" — but a
 * compound Spanish surname is indistinguishable from a middle name without a
 * database of people, and rung 2 is only ever reached when the alternative is
 * shrinking the type or cutting the name in half.
 */

const PARTICLES = new Set([
  'van', 'von', 'de', 'del', 'della', 'der', 'den', 'di', 'da', 'dos', 'das',
  'du', 'la', 'le', 'el', 'al', 'bin', 'ibn', 'ter', 'ten', 'op', 'auf', "'t",
])

/** Split into [givenNames[], surnameTokens[]]. */
function split(name) {
  const parts = String(name || '').trim().split(/\s+/).filter(Boolean)
  if (parts.length <= 1) return [[], parts]

  let start = parts.length - 1
  while (start > 1 && PARTICLES.has(parts[start - 1].toLowerCase())) start -= 1
  return [parts.slice(0, start), parts.slice(start)]
}

/**
 * The rungs, longest first. Always at least one entry, and never an empty
 * string — a name that is a single token has nothing to shorten and simply
 * repeats, which callers treat as "no shorter form exists".
 */
export function nameForms(name) {
  const full = String(name || '').trim()
  if (!full) return ['']

  const [given, surname] = split(full)
  const last = surname.join(' ')
  if (!given.length || !last) return [full]

  // Initials keep particles as words: "B. van de Zandschulp", not "B. v. d. Z."
  const initials = given
    .map(g => `${[...g][0].toUpperCase()}.`)
    .join(' ')

  const forms = [full, `${initials} ${last}`, last]
  // Drop any rung that did not actually get shorter.
  return forms.filter((f, i) => i === 0 || f.length < forms[i - 1].length)
}

/* Doubles arrive as "A / B". Each side is shortened on its own so the pair
   collapses evenly rather than one name vanishing while the other stays whole. */
export function pairForms(name) {
  const sides = String(name || '').split('/').map(s => s.trim()).filter(Boolean)
  if (sides.length < 2) return nameForms(name)

  const each = sides.map(nameForms)
  const depth = Math.max(...each.map(f => f.length))
  const out = []
  for (let i = 0; i < depth; i++) {
    out.push(each.map(f => f[Math.min(i, f.length - 1)]).join(' / '))
  }
  return out.filter((f, i) => i === 0 || f !== out[i - 1])
}

/* SHEET SURNAMES ARRIVE SHOUTING. The order of play prints "Constantin
   FRANTZEN"; singles never showed it because entry_name (proper case, from
   the draw) took precedence, and a doubles pair has no draw entry — so the
   app printed "FRANTZEN / HAASE" beside "Cerúndolo / Cerúndolo" on the same
   court (2026-09-04). Lower the caps, keep the shapes: a capital after an
   apostrophe or hyphen, Mc + capital, particles lower unless they lead. */
const LOWER_PARTICLES = new Set(['de', 'van', 'der', 'den', 'da', 'di', 'du', 'la', 'le', 'von', 'del', 'della', 'dos', 'das', 'do'])
const SHOUTING = /^[A-ZÀ-ÖØ-Þ'’-]{2,}$/

export function properName(raw) {
  const parts = String(raw || '').split(/(\s+)/)
  let seenWord = false
  return parts.map(tok => {
    if (/^\s*$/.test(tok)) return tok
    const first = !seenWord
    seenWord = true
    if (!SHOUTING.test(tok)) return tok
    const low = tok.toLowerCase()
    if (!first && LOWER_PARTICLES.has(low)) return low
    let out = low.replace(/(^|['’-])([a-zà-öø-ÿ])/g, (m, p, c) => p + c.toUpperCase())
    out = out.replace(/^Mc([a-zà-öø-ÿ])/, (m, c) => 'Mc' + c.toUpperCase())
    return out
  }).join('')
}
