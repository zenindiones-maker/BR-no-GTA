import { defineConfig } from '@playwright/test'

const baseURL = process.env.BROWSER_QA_BASE_URL || 'http://127.0.0.1:8760'

export default defineConfig({
  testDir: './browser-qa/e2e',
  timeout: 30_000,
  expect: {
    timeout: 5_000,
    toHaveScreenshot: {
      pathTemplate: '{testDir}/../visual-baselines/{projectName}/{arg}{ext}',
      animations: 'disabled',
      caret: 'hide',
      maxDiffPixels: 0,
      threshold: 0,
    },
  },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  outputDir: './browser-qa/test-results',
  reporter: [
    ['json', { outputFile: './browser-qa/playwright-results.json' }],
    ['html', { outputFolder: './browser-qa/html-report', open: 'never' }],
  ],
  use: {
    baseURL,
    browserName: 'chromium',
    headless: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    deviceScaleFactor: 1,
    locale: 'pt-BR',
    timezoneId: 'America/Sao_Paulo',
    actionTimeout: 8_000,
    navigationTimeout: 12_000,
  },
  projects: [
    {
      name: 'chromium-desktop',
      use: { viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'chromium-desktop-narrow',
      use: { viewport: { width: 1024, height: 768 } },
    },
  ],
})
