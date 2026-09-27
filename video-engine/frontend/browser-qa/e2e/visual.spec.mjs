import { test, expect } from '@playwright/test'
import {
  assertRuntimeGates,
  installRuntimeGates,
  resetFixture,
} from '../runtime-gates.mjs'

async function assertReviewedVisual(page, testInfo, name) {
  await expect(page).toHaveScreenshot(name + '.png')
  const actual = await page.screenshot({
    animations: 'disabled',
    caret: 'hide',
  })
  await testInfo.attach('visual-actual-' + name + '.png', {
    body: actual,
    contentType: 'image/png',
  })
}

test.beforeEach(async ({ page }, testInfo) => {
  const identityProfile = testInfo.project.name === 'chromium-desktop-narrow'
    ? 'desktop-narrow'
    : 'desktop'
  await resetFixture(page, identityProfile)
})

test('[visual:editor-with-project] reviewed editor baseline remains exact', async ({ page }, testInfo) => {
  const gates = installRuntimeGates(page)
  await page.goto('/')
  await expect(page.getByText('Video principal', { exact: true })).toBeVisible()
  await expect(page.getByText('Overlay QA', { exact: true })).toBeVisible()
  await assertReviewedVisual(page, testInfo, 'editor-with-project')
  await assertRuntimeGates(gates, testInfo)
})

test('[visual:selected-clip] reviewed selected-clip baseline remains exact', async ({ page }, testInfo) => {
  const gates = installRuntimeGates(page)
  await page.goto('/')
  const clip = page.locator('.clip').filter({ hasText: 'QA Blue' }).first()
  await expect(clip).toBeVisible()
  await clip.click()
  await expect(clip).toHaveClass(/\bsel\b/)
  await assertReviewedVisual(page, testInfo, 'selected-clip')
  await assertRuntimeGates(gates, testInfo)
})

test('[visual:track-dialog] reviewed destructive-dialog baseline remains exact', async ({ page }, testInfo) => {
  const gates = installRuntimeGates(page)
  await page.goto('/')
  const track = page.locator('.track').filter({
    has: page.getByText('Overlay QA', { exact: true }),
  }).first()
  await track.getByTitle('Elimina la traccia').click()
  const dialog = page.getByRole('dialog', { name: 'Eliminare la traccia?' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'annulla' })).toBeFocused()
  await assertReviewedVisual(page, testInfo, 'track-dialog')
  await assertRuntimeGates(gates, testInfo)
})

test('[visual:inspector-open] reviewed text-inspector baseline remains exact', async ({ page }, testInfo) => {
  const gates = installRuntimeGates(page)
  await page.goto('/')
  const clip = page.locator('.clip').filter({ hasText: 'QA Title' }).first()
  await expect(clip).toBeVisible()
  await clip.click()
  await expect(page.locator('.inspector')).toBeVisible()
  await expect(page.locator('.inspector .section-title')).toContainText('text')
  await assertReviewedVisual(page, testInfo, 'inspector-open')
  await assertRuntimeGates(gates, testInfo)
})
