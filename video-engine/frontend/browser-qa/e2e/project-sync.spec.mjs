import { test, expect } from '@playwright/test'
import {
  assertRuntimeGates,
  installRuntimeGates,
  resetFixture,
} from '../runtime-gates.mjs'

test.beforeEach(async ({ page }) => {
  await resetFixture(page)
})

test('[functional:project-sync] direct agent Store mutation propagates to UI', async ({ page }, testInfo) => {
  const gates = installRuntimeGates(page)
  await page.goto('/')
  await expect(page.getByText('Video principal', { exact: true })).toBeVisible()

  const response = await page.request.post('/__qa/agent/rename', {
    data: { track_id: 'V1', name: 'Agent Synced Track' },
  })
  expect(response.ok()).toBeTruthy()
  const payload = await response.json()
  expect(payload.same_store).toBe(true)

  await expect(
    page.getByText('Agent Synced Track', { exact: true }),
  ).toBeVisible({ timeout: 4_000 })
  await assertRuntimeGates(gates, testInfo)
})
