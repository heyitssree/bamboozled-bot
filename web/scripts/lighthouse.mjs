// Lighthouse budgets on the real flow: mobile emulation, Lighthouse's simulated slow 4G and 4x CPU slowdown.
// Starts the e2e server (real Python server, mock Discord build), signs in as a mock user, and reports.
import { spawn } from 'node:child_process'
import { launch } from 'chrome-launcher'
import lighthouse from 'lighthouse'

const PORT = 8483
const BUDGETS = { performance: 0.9, accessibility: 0.95, lcpMs: 3000, fcpMs: 2000, tbtMs: 300, jsKb: 250 }
// Discord's avatar CDN sets cookies on the pictures we must show; those two audits are not ours to fix.
const KNOWN_BEST_PRACTICE_NOISE = new Set(['third-party-cookies', 'inspector-issues'])

const server = spawn('sh', ['scripts/e2e-server.sh'], { env: { ...process.env, PORT: String(PORT) }, stdio: 'ignore' })
const stop = () => server.kill('SIGTERM')
process.on('exit', stop)
for (let i = 0; i < 120; i++) {
  try { if ((await fetch(`http://127.0.0.1:${PORT}/api/health`)).ok) break } catch { /* starting */ }
  await new Promise((r) => setTimeout(r, 500))
}

const chrome = await launch({ chromeFlags: ['--headless=new', '--no-sandbox'] })
let exit = 0
try {
  const url = `http://127.0.0.1:${PORT}/?user=alice&instance=lighthouse-${Date.now()}`
  const { lhr } = await lighthouse(url, { port: chrome.port, output: 'json', logLevel: 'error', onlyCategories: ['performance', 'accessibility', 'best-practices'] })
  const audit = (id) => lhr.audits[id]?.numericValue ?? NaN
  const js = lhr.audits['resource-summary']?.details?.items?.find((i) => i.resourceType === 'script')?.transferSize ?? NaN
  const rows = [
    ['performance score', lhr.categories.performance.score, BUDGETS.performance, '>='],
    ['accessibility score', lhr.categories.accessibility.score, BUDGETS.accessibility, '>='],
    ['first contentful paint (ms)', audit('first-contentful-paint'), BUDGETS.fcpMs, '<='],
    ['largest contentful paint (ms)', audit('largest-contentful-paint'), BUDGETS.lcpMs, '<='],
    ['total blocking time (ms)', audit('total-blocking-time'), BUDGETS.tbtMs, '<='],
    ['JavaScript transferred (KB)', js / 1024, BUDGETS.jsKb, '<='],
  ]
  for (const [name, value, budget, op] of rows) {
    const ok = op === '>=' ? value >= budget : value <= budget
    if (!ok) exit = 1
    console.log(`${ok ? 'PASS' : 'FAIL'}  ${name.padEnd(32)} ${Number(value).toFixed(op === '>=' ? 2 : 0).padStart(8)}   (budget ${op} ${budget})`)
  }
  const bad = lhr.categories['best-practices'].auditRefs.map((r) => lhr.audits[r.id])
    .filter((a) => a.score !== null && a.score < 1 && !KNOWN_BEST_PRACTICE_NOISE.has(a.id))
  console.log(`${bad.length ? 'FAIL' : 'PASS'}  best-practices problems other than Discord's avatar-CDN cookies: ${bad.map((a) => a.id).join(', ') || 'none'}`)
  if (bad.length) exit = 1
  console.log(`\n${lhr.configSettings.formFactor} / ${lhr.configSettings.throttlingMethod} throttling, ${lhr.environment.hostUserAgent}`)
} finally {
  await chrome.kill()
  stop()
}
process.exit(exit)
