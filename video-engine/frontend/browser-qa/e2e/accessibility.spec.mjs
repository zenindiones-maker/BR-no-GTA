import AxeBuilder from '@axe-core/playwright'
import { test, expect } from '@playwright/test'
import {
  assertRuntimeGates,
  installRuntimeGates,
  resetFixture,
} from '../runtime-gates.mjs'

test.beforeEach(async ({ page }) => {
  await resetFixture(page)
})

test('[accessibility:axe] automated WCAG A/AA serious and critical gate', async ({ page }, testInfo) => {
  const gates = installRuntimeGates(page)
  await page.goto('/')
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .analyze()
  const blocking = results.violations.filter(
    (item) => item.impact === 'critical' || item.impact === 'serious',
  )
  await testInfo.attach('axe-results.json', {
    body: Buffer.from(JSON.stringify(results, null, 2)),
    contentType: 'application/json',
  })
  expect(blocking, JSON.stringify(blocking, null, 2)).toEqual([])
  await assertRuntimeGates(gates, testInfo)
})

test('[aria:editor] important surfaces expose stable accessible structure', async ({ page }, testInfo) => {
  const gates = installRuntimeGates(page)
  await page.goto('/')
  const topbar = await page.locator('.topbar').ariaSnapshot()
  const timeline = await page.locator('.timeline').ariaSnapshot()
  expect(topbar).toContain('button')
  expect(topbar).toContain('novo')
  expect(topbar).toContain('salva')
  expect(timeline).toContain('Video principal')
  expect(timeline).toContain('Overlay QA')
  await testInfo.attach('topbar-aria.yml', {
    body: Buffer.from(topbar),
    contentType: 'text/yaml',
  })
  await testInfo.attach('timeline-aria.yml', {
    body: Buffer.from(timeline),
    contentType: 'text/yaml',
  })
  await assertRuntimeGates(gates, testInfo)
})
