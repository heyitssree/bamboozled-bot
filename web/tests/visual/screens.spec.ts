import { expect, test } from '@playwright/test'
import { FIXTURES } from '../../src/app/fixtures'

const WIDTHS = [360, 768, 1280]
const FROZEN = new Date('2026-10-31T12:00:00Z')

/** Screenshots of each key screen at three widths. Baselines live in tests/visual/screens.spec.ts-snapshots and are
 *  approved by the owner; regenerate with `npm run test:visual -- --update-snapshots` and review the diff. */
for (const f of FIXTURES.filter((x) => x.visual)) {
  for (const width of WIDTHS) {
    test(`${f.id} at ${width}px`, async ({ page }) => {
      // the approved baselines are rendered on macOS; other systems draw fonts differently, so they do not compare pixels
      test.skip(process.platform !== 'darwin', 'screenshot baselines are macOS-rendered')
      await page.setViewportSize({ width, height: width < 700 ? 760 : 800 })
      await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' })
      await page.clock.install({ time: FROZEN })              // deadlines in the fixtures are relative to "now": keep it still
      await page.goto(`/?screen=${f.id}`)
      await page.waitForSelector('main, [role=dialog]')
      await page.waitForTimeout(250)
      await expect(page).toHaveScreenshot(`${f.id}-${width}.png`, { fullPage: true })
    })
  }
}

test('no screen needs sideways scrolling at 320px (portrait phone)', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  for (const f of FIXTURES) {
    await page.goto(`/?screen=${f.id}`)
    await page.waitForSelector('main, [role=dialog]')
    await page.waitForTimeout(80)
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow, `${f.id} overflows by ${overflow}px`).toBeLessThanOrEqual(0)
  }
})

test('touch targets are at least 44px on the screens with buttons', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 760 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  for (const id of ['lobby-host', 'bz-my-question', 'bz-pick-law', 'bz-monkey', 'fff-open', 'surv-playing', 'results-win', 'dialog-settings']) {
    await page.goto(`/?screen=${id}`)
    await page.waitForSelector('main, [role=dialog]')
    await page.waitForTimeout(80)
    const small = await page.evaluate(() =>
      Array.from(document.querySelectorAll<HTMLElement>('button, select, [role=tab], a[href], [role=switch]'))
        .filter((el) => el.offsetParent !== null)
        .map((el) => ({ el, r: el.getBoundingClientRect() }))
        .filter(({ r }) => r.height < 43.5 || r.width < 43.5)
        .map(({ el }) => `${el.tagName.toLowerCase()} "${(el.textContent ?? '').trim().slice(0, 30)}" ${Math.round(el.getBoundingClientRect().width)}x${Math.round(el.getBoundingClientRect().height)}`))
    expect(small, id).toEqual([])
  }
})
