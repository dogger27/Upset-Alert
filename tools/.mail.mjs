import { chromium } from 'playwright'
const OUT = '/tmp/claude-501/-home-paulwiens-Documents-Claude-Projects-TennisFantasyLeague/cd64758a-3199-4fdf-bbdc-4e36bbf36f83/scratchpad'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 420, height: 560 } })
const fails = []
p.on('requestfailed', r => fails.push(r.url()))
p.on('response', r => { if (r.status() >= 400) fails.push(r.status() + ' ' + r.url()) })
await p.goto('file://' + OUT + '/email_new.html', { waitUntil: 'networkidle' })
await p.waitForTimeout(600)
await p.screenshot({ path: OUT + '/email_new.png' })
console.log('image requests failed:', fails.length ? fails : 'none')
await b.close()
