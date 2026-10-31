// Bundle budget: initial JavaScript under 250 KB gzipped, and no mock/gallery code in the production bundle.
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { gzipSync } from 'node:zlib'

const dist = new URL('../dist/', import.meta.url).pathname
const BUDGET = 250 * 1024
const assets = readdirSync(join(dist, 'assets')).filter((f) => f.endsWith('.js'))
const gz = (f) => gzipSync(readFileSync(join(dist, 'assets', f))).length
const html = readFileSync(join(dist, 'index.html'), 'utf8')
const referenced = new Set([...html.matchAll(/assets\/([^"']+\.js)/g)].map((m) => m[1]))
// the Discord SDK is imported dynamically but needed before anything shows, so it counts as initial
const initial = assets.filter((f) => referenced.has(f) || f.startsWith('discord-'))
const total = initial.reduce((n, f) => n + gz(f), 0)

console.log('chunk'.padEnd(34), 'gzip KB'.padStart(9), '  loaded')
for (const f of assets.sort()) console.log(f.padEnd(34), (gz(f) / 1024).toFixed(1).padStart(9), initial.includes(f) ? '  at start' : '  on demand (a mode screen or the stats dialog)')
console.log(`\ninitial JavaScript: ${(total / 1024).toFixed(1)} KB gzipped (budget ${BUDGET / 1024} KB)`)

let failed = false
if (total > BUDGET) { console.error('FAIL: initial JavaScript is over budget'); failed = true }
const modes = ['Bamboozled-', 'Fff-', 'Survival-'].map((p) => assets.find((f) => f.startsWith(p)))
if (modes.some((m) => !m || initial.includes(m))) { console.error('FAIL: each mode must be its own on-demand chunk'); failed = true }
for (const f of assets) {
  const text = readFileSync(join(dist, 'assets', f), 'utf8')
  if (/splash-loading|lobby-host|createMockSdk|dev:\$\{/.test(text)) { console.error(`FAIL: mock or gallery code found in ${f}`); failed = true }
}
if (!failed) console.log('OK: within budget, modes are split, no mock code in the production bundle')
process.exit(failed ? 1 : 0)
