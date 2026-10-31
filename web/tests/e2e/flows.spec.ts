import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { spawn } from 'node:child_process'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join as pathJoin, resolve } from 'node:path'
import { closeAll, join, NAMES, uniqueInstance } from './helpers'

const startGame = async (host: import('@playwright/test').Page, mode: 'bamboozled' | 'fff' | 'survival' = 'bamboozled') => {
  await host.getByTestId(`mode-${mode}`).click()
  await host.getByRole('button', { name: 'Start the game' }).click()
}

test('only the host can change the game, and everyone sees who the host is', async ({ browser }) => {
  const [alice, bob] = await join(browser, uniqueInstance('host'), NAMES.slice(0, 2))
  try {
    await expect(bob.page.getByTestId('mode-fff')).toBeDisabled()
    await expect(bob.page.getByText('Only the host can change the game.')).toBeVisible()
    await expect(bob.page.getByRole('button', { name: 'Start the game' })).toHaveCount(0)
    await alice.page.getByTestId('mode-fff').click()
    await expect(bob.page.getByTestId('mode-fff')).toHaveAttribute('aria-pressed', 'true')
  } finally {
    await closeAll([alice, bob])
  }
})

test('a late joiner watches as a spectator and cannot act', async ({ browser }) => {
  const instance = uniqueInstance('late')
  const [alice, bob] = await join(browser, instance, NAMES.slice(0, 2))
  const ctx = await browser.newContext({ reducedMotion: 'reduce' })
  try {
    await startGame(alice.page)
    await expect(alice.page.getByRole('region', { name: 'Question' })).toBeVisible()
    const carol = await ctx.newPage()
    await carol.goto(`/?user=carol&instance=${instance}`)
    await expect(carol.getByText('You are watching this game.')).toBeVisible()
    await expect(carol.getByRole('region', { name: 'Question' })).toBeVisible()
    await expect(carol.locator('[data-testid^="answer-"]:not([disabled])')).toHaveCount(0)
  } finally {
    await closeAll([alice, bob])
    await ctx.close()
  }
})

test('the host leaving hands the lobby to the next player after the grace period', async ({ browser }) => {
  const [alice, bob, carol] = await join(browser, uniqueInstance('leave'), NAMES.slice(0, 3))
  try {
    await expect(bob.page.getByRole('button', { name: 'Start the game' })).toHaveCount(0)
    await alice.context.close()                                         // the host's window disappears
    await expect(bob.page.getByRole('button', { name: 'Start the game' })).toBeVisible({ timeout: 15_000 })
    await expect(carol.page.getByRole('button', { name: 'Start the game' })).toHaveCount(0)
    await expect(bob.page.getByRole('heading', { name: /^Players/ })).toContainText('(2/')
  } finally {
    await closeAll([bob, carol])
  }
})

test('a dropped connection mid-question keeps the seat and the question', async ({ browser }) => {
  const instance = uniqueInstance('drop')
  const mk = async (name: string) => {
    const context = await browser.newContext({ reducedMotion: 'reduce' })
    await context.addInitScript(() => {
      const Native = window.WebSocket
      const w = window as unknown as { __sockets: WebSocket[] }
      w.__sockets = []
      window.WebSocket = class extends Native { constructor(u: string | URL, p?: string | string[]) { super(u, p); w.__sockets.push(this) } } as typeof WebSocket
    })
    const page = await context.newPage()
    await page.goto(`/?user=${name}&instance=${instance}`)
    return { context, page }
  }
  const alice = await mk('alice')
  const bob = await mk('bob')
  try {
    await expect(bob.page.getByRole('heading', { name: /^Players/ })).toContainText('(2/')
    await startGame(alice.page)
    await expect(alice.page.getByRole('region', { name: 'Question' })).toBeVisible()

    await alice.context.setOffline(true)                                // the network drops and her socket dies
    await alice.page.evaluate(() => (window as unknown as { __sockets: WebSocket[] }).__sockets.at(-1)!.close(4000))
    await expect(alice.page.getByText('Reconnecting', { exact: false }).first()).toBeVisible()
    await expect(bob.page.getByLabel('reconnecting')).toBeVisible()      // the others see that she is only reconnecting

    await alice.context.setOffline(false)
    await expect(alice.page.getByText('Reconnecting', { exact: false })).toHaveCount(0, { timeout: 15_000 })
    await expect(alice.page.getByRole('region', { name: 'Question' })).toBeVisible()
    await alice.page.getByTestId('answer-0').click()                    // she can still play: the seat was kept
    await expect(bob.page.getByText(/got it right|missed it/)).toBeVisible()
  } finally {
    await alice.context.close()
    await bob.context.close()
  }
})

test('keys 1 to 4 answer on desktop', async ({ browser }) => {
  const [alice, bob] = await join(browser, uniqueInstance('keys'), NAMES.slice(0, 2))
  try {
    await startGame(alice.page)
    await expect(alice.page.getByText('Your turn: pick an answer (keys 1 to 4).')).toBeVisible()
    await alice.page.keyboard.press('2')
    await expect(bob.page.getByText(/got it right|missed it/)).toBeVisible()
  } finally {
    await closeAll([alice, bob])
  }
})

test('settings are applied at once and remembered', async ({ page, context }) => {
  await page.goto(`/?user=alice&instance=${uniqueInstance('settings')}`)
  await page.getByRole('button', { name: 'Settings' }).click()
  const dialog = page.getByRole('dialog', { name: 'Settings' })
  await dialog.getByRole('switch', { name: 'Reduce motion' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'reduce')
  await dialog.getByLabel('Theme').selectOption('light')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  await dialog.getByRole('switch', { name: 'Sound effects' }).click()
  await expect(dialog.getByRole('switch', { name: 'Sound effects' })).toHaveAttribute('aria-checked', 'false')
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')            // theme and motion survive a reload
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'reduce')
  await page.getByRole('button', { name: 'Settings' }).click()
  await expect(page.getByRole('switch', { name: 'Sound effects' })).toHaveAttribute('aria-checked', 'false')   // the mute is for the session
  await context.clearCookies()
})

test('opting out asks for confirmation and says so honestly when the server cannot do it yet', async ({ page }) => {
  await page.goto(`/?user=alice&instance=${uniqueInstance('optout')}`)
  await page.getByRole('button', { name: 'Settings' }).click()
  await page.getByRole('button', { name: /Opt out and delete/ }).click()
  const confirm = page.getByRole('dialog', { name: 'Opt out of Bamboozled?' })
  await expect(confirm).toBeVisible()
  await confirm.getByRole('button', { name: 'Keep playing' }).click()
  await expect(confirm).toHaveCount(0)
  await page.getByRole('button', { name: /Opt out and delete/ }).click()
  await page.getByRole('button', { name: 'Yes, delete and opt out' }).click()
  await expect(page.getByText('Privacy controls are not switched on yet', { exact: false })).toBeVisible()
})

test('the stats dialog loads and shows an empty state for a new player', async ({ page }) => {
  const fresh = `newbie${Date.now() % 100000}`                         // a user nobody has played as: no games recorded
  await page.goto(`/?user=${fresh}&instance=${uniqueInstance('stats')}`)
  await page.getByRole('button', { name: 'Stats and leaderboards' }).click()
  await expect(page.getByText('You have not finished a game yet.')).toBeVisible()
  await page.getByRole('tab', { name: 'Bamboozled' }).click()
  await expect(page.getByRole('button', { name: 'This server' })).toHaveAttribute('aria-pressed', 'true')
  // loaded: either a table of earlier games from this shared test server, or the friendly empty message
  await expect(page.getByRole('table', { name: /leaderboard/ }).or(page.getByText('No games here yet.'))).toBeVisible()
  await page.getByRole('button', { name: 'Everywhere' }).click()
  await expect(page.getByRole('button', { name: 'Everywhere' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('table', { name: /leaderboard/ }).or(page.getByText('No games here yet.'))).toBeVisible()
})

test('live pages have no serious accessibility problems (lobby, question, results)', async ({ browser }) => {
  const [alice, bob] = await join(browser, uniqueInstance('axe'), NAMES.slice(0, 2))
  const scan = async (page: import('@playwright/test').Page) => {
    const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
    return r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.nodes[0].target.join(' ')}`)
  }
  try {
    expect(await scan(alice.page)).toEqual([])
    await startGame(alice.page, 'fff')
    await expect(alice.page.getByRole('region', { name: 'Question' })).toBeVisible()
    expect(await scan(alice.page)).toEqual([])
    await alice.page.getByTestId('answer-0').click()
    await bob.page.getByTestId('answer-1').click()
    await expect(alice.page.getByRole('heading', { name: 'Round result' })).toBeVisible()
    expect(await scan(alice.page)).toEqual([])
  } finally {
    await closeAll([alice, bob])
  }
})

// ───────────────────────────── a real server restart ─────────────────────────────

test('a server restart shows "game interrupted" at once and returns everyone to a working lobby', async ({ browser }) => {
  const PORT = 8482
  const python = process.env.PYTHON ?? resolve(process.cwd(), '../.venv/bin/python')
  const launch = () => spawn(python, ['-m', 'bamboozled'], {
    cwd: '..',
    env: { ...process.env, BAMBOOZLED_DEV_AUTH: '1', BAMBOOZLED_ENV: 'test', BAMBOOZLED_PORT: String(PORT), BAMBOOZLED_WEB_DIST: 'web/dist-mock',
      BAMBOOZLED_DB_PATH: pathJoin(mkdtempSync(pathJoin(tmpdir(), 'bz-restart-')), 'r.db'), LOG_TO_FILE: '0' },
    stdio: 'ignore',
  })
  const up = async () => { for (let i = 0; i < 60; i++) { try { if ((await fetch(`http://127.0.0.1:${PORT}/api/health`)).ok) return } catch { /* not yet */ } await new Promise((r) => setTimeout(r, 250)) } throw new Error('server did not start') }
  let server = launch()
  await up()
  const instance = uniqueInstance('restart')
  const contexts = await Promise.all([0, 1].map(() => browser.newContext({ baseURL: `http://127.0.0.1:${PORT}`, reducedMotion: 'reduce' })))
  try {
    const pages = await Promise.all(contexts.map((c) => c.newPage()))
    await pages[0].goto(`/?user=alice&instance=${instance}`)
    await pages[1].goto(`/?user=bob&instance=${instance}`)
    await expect(pages[0].getByRole('heading', { name: /^Players/ })).toContainText('(2/')
    await startGame(pages[0])
    await expect(pages[1].getByRole('region', { name: 'Question' })).toBeVisible()

    const killed = new Promise((r) => server.once('exit', r))
    server.kill('SIGTERM')
    await killed
    const t0 = Date.now()
    for (const p of pages) await expect(p.getByRole('alertdialog', { name: 'Game interrupted' })).toBeVisible({ timeout: 10_000 })
    expect(Date.now() - t0).toBeLessThan(10_000)

    server = launch()
    await up()
    for (const p of pages) {
      await expect(p.getByRole('heading', { name: 'Pick a game' })).toBeVisible({ timeout: 20_000 })
      await expect(p.getByRole('alertdialog')).toHaveCount(0)
    }
    // a fresh room: whoever reconnected first is the host, and exactly one player can start
    const starters = () => Promise.all(pages.map((p) => p.getByRole('button', { name: 'Start the game' }).count())).then((c) => c[0] + c[1])
    await expect.poll(starters, { timeout: 10_000 }).toBe(1)
    const host = (await pages[0].getByRole('button', { name: 'Start the game' }).count()) ? pages[0] : pages[1]
    await expect(host.getByRole('button', { name: 'Start the game' })).toBeEnabled()
  } finally {
    await Promise.all(contexts.map((c) => c.close()))
    server.kill('SIGKILL')
  }
})
