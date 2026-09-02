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
  // A day with a washout behind it: postponed, carried-over and resumed rows.
  { name: 'washout',   mobile: '/schedule?date=2026-09-01', pwa: '/schedule?date=2026-09-01' },
  // The same day scrolled to its end, where the postponed rows live, and with
  // "Completed" switched off, which must take the postponed rows with it.
  { name: 'washout-end',  mobile: '/schedule?date=2026-09-01', pwa: '/schedule?date=2026-09-01', scrollEnd: true },
  { name: 'schedule-court', mobile: '/schedule', pwa: '/schedule', appClick: 'Court', pwaClick: 'Court' },
  { name: 'washout-court',  mobile: '/schedule?date=2026-09-01', pwa: '/schedule?date=2026-09-01', appClick: 'Court', pwaClick: 'Court', scrollEnd: true },
  // A finished row tapped open: the score-history sheet beside the site's popup.
  { name: 'score-history', mobile: '/schedule?date=2026-09-01', pwa: '/schedule?date=2026-09-01', appClick: 'Madison Keys', pwaClick: 'KEYS' },
  // A finished match on the draw page tapped open: the same sheet from the bracket.
  { name: 'draw-score', mobile: '/draw/77', pwa: '/tournaments/77', appClick: 'Halys', pwaClick: 'Halys' },
  // Another member's picks on the bracket, reached from a standings row.
  { name: 'draw-other', mobile: '/draw/77?user=43&name=piotr_lotr86', pwa: '/tournaments/77?user=43' },
  // The league settings sheet (owner / league admin / site admin).
  { name: 'league-settings', mobile: '/league/10', pwa: '/leagues/10', appClick: 'Settings' },
  // The league page's foot: the Members tally beside the site's Members tab.
  { name: 'league-members', mobile: '/league/10', pwa: '/leagues/10', pwaClick: 'Members', scrollEnd: true },
  // Global standings for a draw — the site's Global league list for it.
  { name: 'standings-global', mobile: '/standings/77', pwa: '/leagues' },
  { name: 'washout-open', mobile: '/schedule?date=2026-09-01', pwa: '/schedule?date=2026-09-01', appClick: 'Completed', pwaClick: 'Completed' },
  { name: 'league',    mobile: '/league/10',   pwa: '/leagues/10' },
  // The site keeps standings behind a tab rather than a route, so the PWA side
  // has to be clicked into position before it can be compared with anything.
  { name: 'standings', mobile: '/league/10/draw/77', pwa: '/leagues/10', pwaClick: 'Members' },
  { name: 'h2h',       mobile: '/draw/77', pwa: '/tournaments/77', appClick: 'H2H', pwaClick: 'H2H' },
  { name: 'called',    mobile: '/draw/77', pwa: '/tournaments/77', appClick: 'WHO CALLED IT' },
  // Signed OUT on purpose: this screen had two invisible-token bugs at once.
  { name: 'signin',    mobile: '/sign-in', pwa: '/login', noAuth: true },
  { name: 'picks',     mobile: '/league/10/draw/77/picks', pwa: '/tournaments/77' },
  { name: 'history',   mobile: '/history',      pwa: '/draw-history' },
  { name: 'hof',       mobile: '/hall-of-fame', pwa: '/hall-of-fame' },
  /* NOT '/status': Metro's dev server answers that path itself with
     "packager-status:running" and never reaches the app. Reached by tapping
     the tab instead. */
  { name: 'status',    mobile: '/', pwa: '/', appClick: 'Status' },
]

const only = process.argv.slice(2).filter(a => !a.startsWith('-'))
/* --scale 1.7: render the APP at the phone's text-size setting. react-native-web
   always reports a font scale of 1, which hid a whole class of bug — clipped
   chips, truncated names — until fontScale.js grew a harness override. The
   PWA side is unaffected (it has no such setting). Output goes to
   <screen>@<scale>.*.png so the 1.0 set is kept for comparison. */
const scaleArg = process.argv.find(a => a.startsWith('--scale='))
const SCALE = scaleArg ? Number(scaleArg.split('=')[1]) : 1
const SUFFIX = SCALE !== 1 ? `@${SCALE}` : ''
const full = process.argv.includes('--full')
const targets = only.length ? SCREENS.filter(s => only.includes(s.name)) : SCREENS

mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({
  args: ['--disable-web-security', '--hide-scrollbars', '--force-color-profile=srgb'],
})

async function shoot(url, kind, name, click, noAuth, scrollEnd) {
  const ctx = await browser.newContext({
    viewport: VIEW, deviceScaleFactor: DSF, isMobile: true, hasTouch: true,
    colorScheme: 'dark',
    /* The phone is in Vancouver. Headless Chromium defaults to UTC, which made
       every expected-start label read "... UTC" on BOTH sides — so a real
       disagreement about whose clock to use would have looked like agreement. */
    timezoneId: 'America/Vancouver',
    locale: 'en-CA',
  })
  // Both keys every time: the Expo app reads upsetalert.session.jwt (session.js),
  // the PWA reads `token`. Setting the other app's key is inert.
  if (!noAuth) {
    await ctx.addInitScript(t => {
      try {
        localStorage.setItem('upsetalert.session.jwt', t)
        localStorage.setItem('token', t)
      } catch {}
    }, TOKEN)
  }
  if (kind === 'app' && SCALE !== 1) {
    await ctx.addInitScript(sc => { globalThis.__UA_FONT_SCALE = sc }, SCALE)
  }

  const page = await ctx.newPage()
  const errors = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text().slice(0, 160)) })
  page.on('pageerror', e => errors.push('PAGEERROR ' + String(e).slice(0, 160)))
  // "Failed to load resource: 404" on its own names nothing. Log the URL, or a
  // benign missing favicon is indistinguishable from a broken API call.
  page.on('response', r => {
    if (r.status() >= 400) errors.push(`HTTP ${r.status()} ${r.url().slice(0, 120)}`)
  })

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

  // The app's lists live in a bounded ScrollView, so a full-page shot never
  // reaches their end. Scroll the deepest scroller (and the window) to the
  // bottom when a screen asks for it.
  if (scrollEnd) {
    await page.evaluate(() => {
      window.scrollTo(0, document.body.scrollHeight)
      const els = [...document.querySelectorAll('*')].filter(e =>
        e.scrollHeight > e.clientHeight + 40 && /auto|scroll/.test(getComputedStyle(e).overflowY))
      for (const e of els) e.scrollTop = e.scrollHeight
    })
    await page.waitForTimeout(1500)
  }

  // EXPO'S RED BOX IS NOT A pageerror. A crash inside a screen is caught and
  // painted as an overlay, so the console hook above stays silent and the
  // screenshot shows an error page that reads, at a glance, like a dark
  // screen. Read the overlay's own text so a crash is reported as one.
  if (kind === 'app') {
    const box = await page.evaluate(() =>
      (document.body.innerText.match(/Uncaught Error[\s\S]{0,160}/) || [null])[0])
    if (box) errors.push('RED BOX ' + box.replace(/\n+/g, ' ').slice(0, 160))
  }

  const file = join(OUT, `${name}${SUFFIX}.${kind}.png`)
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
  const out = join(OUT, `${name}${SUFFIX}.compare.png`)
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
  const app = await shoot(MOBILE + s.mobile, 'app', s.name, s.appClick, s.noAuth, s.scrollEnd)
  const pwa = await shoot(PWA + s.pwa, 'pwa', s.name, s.pwaClick, s.noAuth, s.scrollEnd)
  const cmp = await pair(s.name, app.file, pwa.file)
  console.log(`${s.name}: ${cmp}`)
  for (const e of app.errors.slice(0, 4)) console.log(`   app  ! ${e}`)
  for (const e of pwa.errors.slice(0, 4)) console.log(`   pwa  ! ${e}`)
}

await browser.close()
