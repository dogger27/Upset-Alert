/*
 * Render the Expo app and the PWA side by side, at phone size, on the SAME data.
 *
 * Why this exists: every design correction was costing a round trip through the
 * user's phone — they screenshot, I guess. This closes that loop. The Expo app
 * has a web target already (it backs prerendering), so react-native-web renders
 * the same components, tokens and fonts the phone does. It is NOT pixel-identical
 * to iOS — shadows, font smoothing and the safe-area insets differ — so treat it
 * as a layout and hierarchy check, never as proof of native rendering.
 *
 * Both apps are pointed at ONE local backend so a difference on screen is a
 * difference in the app, not a difference in the data. That is the whole point;
 * comparing a live US Open against a stale local copy would be worse than useless.
 *
 * Chromium runs with web security off purely so two localhost origins may call
 * that backend without an allowlist entry. It is a throwaway profile with no
 * credentials in it beyond a locally-minted token for a local database.
 */
import { chromium } from 'playwright'
import sharp from 'sharp'
import { mkdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

const MOBILE = process.env.MOBILE_URL || 'http://localhost:8099'
const PWA    = process.env.PWA_URL    || 'http://localhost:5173'
const TOKEN  = readFileSync('/tmp/ua_token.txt', 'utf8').trim()
const OUT    = join(import.meta.dirname, 'shots')

// 393x852 is the iPhone 15/16 logical viewport. dsf 2 rather than 3: the extra
// pixels cost file size and buy nothing for judging layout.
const VIEW = { width: 393, height: 852 }
const DSF = 2

const SCREENS = [
  { name: 'dashboard', mobile: '/',            pwa: '/' },
  { name: 'draw',      mobile: '/draw/77',     pwa: '/tournaments/77' },
  { name: 'leagues',   mobile: '/leagues',     pwa: '/leagues' },
  { name: 'schedule',  mobile: '/schedule',    pwa: '/schedule' },
  { name: 'league',    mobile: '/league/10',   pwa: '/leagues/10' },
  // The site keeps standings behind a tab rather than a route, so the PWA side
  // has to be clicked into position before it can be compared with anything.
  { name: 'standings', mobile: '/league/10/draw/77', pwa: '/leagues/10', pwaClick: 'Members' },
]

const only = process.argv.slice(2).filter(a => !a.startsWith('-'))
const full = process.argv.includes('--full')
const targets = only.length ? SCREENS.filter(s => only.includes(s.name)) : SCREENS

mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({
  args: ['--disable-web-security', '--hide-scrollbars', '--force-color-profile=srgb'],
})

async function shoot(url, kind, name, click) {
  const ctx = await browser.newContext({
    viewport: VIEW, deviceScaleFactor: DSF, isMobile: true, hasTouch: true,
    colorScheme: 'dark',
  })
  // Both keys every time: the Expo app reads upsetalert.session.jwt (session.js),
  // the PWA reads `token`. Setting the other app's key is inert.
  await ctx.addInitScript(t => {
    try {
      localStorage.setItem('upsetalert.session.jwt', t)
      localStorage.setItem('token', t)
    } catch {}
  }, TOKEN)

  const page = await ctx.newPage()
  const errors = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text().slice(0, 160)) })
  page.on('pageerror', e => errors.push('PAGEERROR ' + String(e).slice(0, 160)))

  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 })
  // networkidle alone fires before React Query has painted the second wave of
  // fetches (standings, per-draw calls), which is exactly the content being judged.
  await page.waitForLoadState('networkidle', { timeout: 45000 }).catch(() => {})
  await page.waitForTimeout(3500)

  // Optional: put the page into the state being compared (a tab, a filter).
  if (click) {
    await page.getByText(click, { exact: false }).first().click({ timeout: 8000 }).catch(() => {})
    await page.waitForTimeout(2000)
  }

  const file = join(OUT, `${name}.${kind}.png`)
  await page.screenshot({ path: file, fullPage: full })
  await ctx.close()
  return { file, errors }
}

// Side by side in one image: half the files to open, and the only way to actually
// see a spacing or type-scale difference rather than infer it from two tabs.
async function pair(name, a, b) {
  const label = (text, w) => Buffer.from(
    `<svg width="${w}" height="34"><rect width="${w}" height="34" fill="#000"/>` +
    `<text x="10" y="23" font-family="monospace" font-size="16" fill="#fff">${text}</text></svg>`)
  const [ma, mb] = [sharp(a), sharp(b)]
  const [xa, xb] = [await ma.metadata(), await mb.metadata()]
  const H = Math.max(xa.height, xb.height)
  const GAP = 24
  const W = xa.width + xb.width + GAP
  const out = join(OUT, `${name}.compare.png`)
  await sharp({ create: { width: W, height: H + 34, channels: 3, background: '#000' } })
    .composite([
      { input: label('APP (Expo)', xa.width), top: 0, left: 0 },
      { input: label('PWA', xb.width), top: 0, left: xa.width + GAP },
      { input: await ma.toBuffer(), top: 34, left: 0 },
      { input: await mb.toBuffer(), top: 34, left: xa.width + GAP },
    ]).png().toFile(out)
  return out
}

for (const s of targets) {
  const app = await shoot(MOBILE + s.mobile, 'app', s.name)
  const pwa = await shoot(PWA + s.pwa, 'pwa', s.name, s.pwaClick)
  const cmp = await pair(s.name, app.file, pwa.file)
  console.log(`${s.name}: ${cmp}`)
  for (const e of app.errors.slice(0, 4)) console.log(`   app  ! ${e}`)
  for (const e of pwa.errors.slice(0, 4)) console.log(`   pwa  ! ${e}`)
}

await browser.close()
