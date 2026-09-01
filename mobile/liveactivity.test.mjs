/*
 * The two Swift copies of the Live Activity wire format must agree.
 *
 * There are two, unavoidably: the app target (modules/live-activity/ios) and
 * the widget extension (targets/activity) are separate compilation units, and
 * an Expo module cannot see the extension's sources. The app ENCODES with its
 * copy and the widget DECODES with its own, so a field present in one and
 * absent from the other is silently dropped — no error, no warning, nothing in
 * a log. It just never arrives.
 *
 * That is not hypothetical. Seed badges shipped in a build that could never
 * draw one: p1_draw_rank/p2_draw_rank were added to the widget's copy and not
 * to the app's, and the field was gone before the widget was ever asked. The
 * file already said "Must match ... EXACTLY" in a comment; a comment is not a
 * check.
 *
 * Python owns the format (live_activity_content.py). This only enforces that
 * the two Swift mirrors are identical to each other.
 *
 *   node liveactivity.test.mjs
 */
import { readFileSync } from 'node:fs'

const FILES = {
  app: 'modules/live-activity/ios/LiveActivityModule.swift',
  widget: 'targets/activity/MatchActivityAttributes.swift',
}

/* Pull `var name: Type` declarations out of a named struct body, following
   nested braces so ContentState's fields are collected separately rather than
   folded into the outer struct. */
function fields(src, structName) {
  const head = new RegExp(`struct\\s+${structName}\\s*:[^{]*\\{`)
  const m = src.match(head)
  if (!m) return null
  let i = m.index + m[0].length
  let depth = 1
  const out = { own: [], nested: {} }
  let body = ''
  for (; i < src.length && depth > 0; i++) {
    const c = src[i]
    if (c === '{') depth++
    else if (c === '}') depth--
    if (depth > 0) body += c
  }
  // Strip nested struct bodies from `own`, then recurse into them.
  const nestedRe = /public\s+struct\s+(\w+)\s*:[^{]*\{/g
  let nm
  while ((nm = nestedRe.exec(body)) !== null) {
    out.nested[nm[1]] = fields(body.slice(nm.index), nm[1])?.own ?? []
  }
  const withoutNested = body.replace(/public\s+struct\s+\w+\s*:[^{]*\{[^}]*\}/g, '')
  for (const f of withoutNested.matchAll(/^\s*(?:public\s+)?var\s+(\w+)\s*:\s*([^\n=]+)/gm)) {
    out.own.push(`${f[1]}: ${f[2].trim()}`)
  }
  return out
}

const problems = []
const parsed = {}
for (const [side, path] of Object.entries(FILES)) {
  const src = readFileSync(path, 'utf8')
  const attrs = fields(src, 'MatchActivityAttributes')
  if (!attrs) { problems.push(`${path}: no MatchActivityAttributes struct found`); continue }
  parsed[side] = attrs
}

if (!problems.length) {
  const cmp = (label, a, b) => {
    const A = JSON.stringify(a), B = JSON.stringify(b)
    if (A !== B) {
      problems.push(
        `${label} differs:\n    app   : ${a.join(' | ') || '(none)'}\n    widget: ${b.join(' | ') || '(none)'}`)
    }
  }
  cmp('MatchActivityAttributes', parsed.app.own, parsed.widget.own)
  const names = new Set([...Object.keys(parsed.app.nested), ...Object.keys(parsed.widget.nested)])
  for (const n of names) {
    cmp(`${n} (nested)`, parsed.app.nested[n] ?? [], parsed.widget.nested[n] ?? [])
  }
}

if (problems.length) {
  console.error('Live Activity wire format mismatch:\n  ' + problems.join('\n  '))
  process.exit(1)
}
console.log(`ok — both Swift copies agree (${parsed.app.own.length} attribute fields, ` +
            `${Object.entries(parsed.app.nested).map(([k, v]) => `${k}:${v.length}`).join(' ')})`)
