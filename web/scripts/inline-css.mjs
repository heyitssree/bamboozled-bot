// After `vite build`: put the stylesheet into index.html so the first paint needs one request, not two.
// index.html is served no-cache and the stylesheet is only ~4 KB gzipped.
import { readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const dist = new URL(`../${process.argv[2] ?? 'dist'}/`, import.meta.url).pathname
const indexPath = join(dist, 'index.html')
let html = readFileSync(indexPath, 'utf8')
const link = /<link rel="stylesheet"[^>]*href="\/assets\/([^"]+\.css)"[^>]*>/
const match = html.match(link)
if (match) {
  const css = readFileSync(join(dist, 'assets', match[1]), 'utf8')
  html = html.replace(link, () => `<style>${css}</style>`)
  writeFileSync(indexPath, html)
  for (const f of readdirSync(join(dist, 'assets'))) if (f.endsWith('.css')) rmSync(join(dist, 'assets', f))
  console.log(`inlined ${match[1]} (${(css.length / 1024).toFixed(1)} KB) into index.html`)
}
