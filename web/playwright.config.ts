import { defineConfig } from '@playwright/test'

const PORT = Number(process.env.PORT ?? 8481)

export default defineConfig({
  testDir: './tests',
  timeout: 90_000,
  workers: 2,
  reporter: [['list']],
  expect: { timeout: 10_000, toHaveScreenshot: { maxDiffPixelRatio: 0.003, animations: 'disabled' } },
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    // locally the installed Chrome is used; CI downloads Chromium (npx playwright install chromium)
    channel: process.env.PW_CHANNEL ?? (process.env.CI ? undefined : 'chrome'),
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'sh scripts/e2e-server.sh',
    url: `http://127.0.0.1:${PORT}/api/health`,
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
    stdout: 'pipe',                                   // the server's log lines show up in the test output
    stderr: 'pipe',
    env: { PORT: String(PORT) },
  },
  projects: [
    { name: 'e2e', testMatch: 'e2e/**/*.spec.ts' },
    { name: 'a11y', testMatch: 'a11y/**/*.spec.ts' },
    { name: 'visual', testMatch: 'visual/**/*.spec.ts' },
  ],
})
