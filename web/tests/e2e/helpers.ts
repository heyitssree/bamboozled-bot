import type { Browser, BrowserContext, Page } from '@playwright/test'
import { expect } from '@playwright/test'

export const NAMES = ['alice', 'bob', 'carol', 'dave'] as const
let counter = 0
export const uniqueInstance = (label: string) => `${label}-${Date.now()}-${counter++}`

export interface Player { name: string; page: Page; context: BrowserContext }

/** Open one browser context per player, each signed in through the mock SDK. */
export async function join(browser: Browser, instance: string, names: readonly string[], opts: { width?: number } = {}): Promise<Player[]> {
  const players: Player[] = []
  for (const name of names) {
    const context = await browser.newContext({ viewport: { width: opts.width ?? 900, height: 900 }, reducedMotion: 'reduce' })
    const page = await context.newPage()
    await page.goto(`/?user=${name}&instance=${instance}`)
    players.push({ name, page, context })
  }
  for (const p of players) await expect(p.page.getByRole('heading', { name: /^Players/ })).toContainText(`(${names.length}/`)
  return players
}

export const closeAll = (players: Player[]) => Promise.all(players.map((p) => p.context.close()))

const resultsTable = (page: Page) => page.getByRole('table', { name: 'Final standings' })

/** One look at the page: do whatever the player can do right now. Returns true if something was clicked. */
export async function act(page: Page, pick = 0): Promise<boolean> {
  const click = async (loc: ReturnType<Page['locator']>) => {
    try {
      await loc.click({ timeout: 800 })
      return true
    } catch {
      return false
    }
  }
  const answers = page.locator('[data-testid^="answer-"]:not([disabled])')
  const n = await answers.count()
  if (n) return click(answers.nth(pick % n))
  for (const name of ['Draw the card', 'Spin the wheel!', 'Belly']) {
    const b = page.getByRole('button', { name })
    if (await b.count()) return click(b.first())
  }
  const target = page.locator('.picker button')
  if (await target.count()) return click(target.first())
  const law = page.locator('.law')
  if (await law.count()) return click(law.nth(pick % 11))
  return false
}

/** Everyone keeps acting until every page shows the final standings. */
export async function playToTheEnd(players: Player[], timeoutMs = 80_000): Promise<void> {
  const end = Date.now() + timeoutMs
  let round = 0
  while (Date.now() < end) {
    let done = 0
    for (const p of players) {
      if (await resultsTable(p.page).count()) { done++; continue }
      await act(p.page, round++)
    }
    if (done === players.length) return
    await players[0].page.waitForTimeout(40)
  }
  throw new Error('the game did not finish in time')
}

export const finalRows = (page: Page) => resultsTable(page).locator('tbody tr')
