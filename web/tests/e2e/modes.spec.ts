import { expect, test } from '@playwright/test'
import { closeAll, finalRows, join, NAMES, playToTheEnd, uniqueInstance } from './helpers'

const MODES = [
  { mode: 'bamboozled', card: 'mode-bamboozled', rounds: '3' },
  { mode: 'fff', card: 'mode-fff', rounds: '5' },
  { mode: 'survival', card: 'mode-survival', rounds: '' },
] as const

for (const { mode, card, rounds } of MODES) {
  for (const n of [2, 3, 4]) {
    test(`${n} players play a whole ${mode} game`, async ({ browser }) => {
      const players = await join(browser, uniqueInstance(mode), NAMES.slice(0, n))
      try {
        const host = players[0].page
        await host.getByTestId(card).click()
        if (rounds) await host.getByLabel(mode === 'fff' ? 'Questions' : 'Rounds').selectOption(rounds)
        await host.getByRole('button', { name: 'Start the game' }).click()
        await playToTheEnd(players)
        for (const p of players) {
          await expect(finalRows(p.page)).toHaveCount(n)
          await expect(p.page.getByRole('list', { name: 'Podium' })).toBeVisible()
        }
        await expect(host.getByRole('button', { name: 'Play again' })).toBeVisible()
        await expect(players[1].page.getByText('Waiting for the host to start another game.')).toBeVisible()
        // the host can go again: back to a working lobby
        await host.getByRole('button', { name: 'Play again' }).click()
        for (const p of players) await expect(p.page.getByRole('heading', { name: 'Pick a game' })).toBeVisible()
      } finally {
        await closeAll(players)
      }
    })
  }
}
