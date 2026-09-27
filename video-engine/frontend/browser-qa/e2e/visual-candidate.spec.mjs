import { test, expect } from '@playwright/test'
import {
  assertRuntimeGates,
  installRuntimeGates,
  resetFixture,
} from '../runtime-gates.mjs'

async function attachFullPageCandidate(page, testInfo, name) {
  const png = await page.screenshot({
    fullPage: false,
    animations: 'disabled',
    caret: 'hide',
  })
  await testInfo.attach(name + '.png', {
    body: png,
    contentType: 'image/png',
  })
}

test.beforeEach(async ({ page }) => {
  await resetFixture(page)
})

test('[visual-candidate:editor-with-project] capture reviewed baseline candidate', async ({ page }, testInfo) => {
  const gates = installRuntimeGates(page)
  await page.goto('/')
  await expect(page.getByText('Video principal', { exact: true })).toBeVisible()
  await expect(page.getByText('Overlay QA', { exact: true })).toBeVisible()
  await attachFullPageCandidate(page, testInfo, 'editor-with-project')
  await assertRuntimeGates(gates, testInfo)
})

test('[visual-candidate:selected-clip] capture reviewed baseline candidate', async ({ page }, testInfo) => {
  const gates = installRuntimeGates(page)
  await page.goto('/')
  const clip = page.locator('.clip').filter({ hasText: 'QA Blue' }).first()
  await expect(clip).toBeVisible()
  await clip.click()
  await expect(clip).toHaveClass(/\bsel\b/)
  await attachFullPageCandidate(page, testInfo, 'selected-clip')
  await assertRuntimeGates(gates, testInfo)
})

test('[visual-candidate:track-dialog] capture reviewed baseline candidate', async ({ page }, testInfo) => {
  const gates = installRuntimeGates(page)
  await page.goto('/')
  const track = page.locator('.track').filter({
    has: page.getByText('Overlay QA', { exact: true }),
  }).first()
  await track.getByTitle('Elimina la traccia').click()
  const dialog = page.getByRole('dialog', { name: 'Eliminare la traccia?' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'annulla' })).toBeFocused()
  await attachFullPageCandidate(page, testInfo, 'track-dialog')
  await assertRuntimeGates(gates, testInfo)
})

test('[visual-candidate:inspector-open] capture reviewed baseline candidate', async ({ page }, testInfo) => {
  const gates = installRuntimeGates(page)
  await page.goto('/')
  const clip = page.locator('.clip').filter({ hasText: 'QA Title' }).first()
  await clip.click()
  await expect(page.locator('.inspector')).toBeVisible()
  await expect(page.locator('.inspector .section-title')).toContainText('text')
  await attachFullPageCandidate(page, testInfo, 'inspector-open')
  await assertRuntimeGates(gates, testInfo)
})
