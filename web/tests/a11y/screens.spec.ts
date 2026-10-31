import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { FIXTURES } from '../../src/app/fixtures'

/** axe on every screen in every state, in the dark and light themes. Fails on serious or critical findings. */
for (const theme of ['dark', 'light'] as const) {
  for (const f of FIXTURES) {
    test(`${f.id} (${theme}) has no serious accessibility problems`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: theme, reducedMotion: 'reduce' })
      await page.goto(`/?screen=${f.id}`)
      await page.waitForSelector('main, [role=dialog], [role=alertdialog]')
      if (f.dialog) await page.waitForSelector('[role=dialog]')
      await page.waitForTimeout(150)                       // let fixture events and effects settle
      const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
      const bad = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
      expect(bad.map((v) => `${v.id}: ${v.help} -> ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')}`)).toEqual([])
    })
  }
}
