import { test, expect } from '@playwright/test'
import {
  assertRuntimeGates,
  installRuntimeGates,
  resetFixture,
} from '../runtime-gates.mjs'

test.beforeEach(async ({ page }) => {
  await resetFixture(page)
})

test('[functional:editor-load] real VEdit loads canonical project', async ({ page }, testInfo) => {
  const gates = installRuntimeGates(page)
  await page.goto('/')
  await expect(page.getByText('VEDIT', { exact: true })).toBeVisible()
  await expect(page.getByText('Video principal', { exact: true })).toBeVisible()
  await expect(page.getByText('Overlay QA', { exact: true })).toBeVisible()
  await expect(page.getByText('QA Blue', { exact: true })).toBeVisible()
  await expect(page.getByRole('slider', { name: 'Scala dei tempi in timeline' })).toBeVisible()
  await assertRuntimeGates(gates, testInfo)
})

test('[functional:clip-selection] clip selection exposes selected state', async ({ page }, testInfo) => {
  const gates = installRuntimeGates(page)
  await page.goto('/')
  const clip = page.locator('.clip').filter({ hasText: 'QA Blue' }).first()
  await expect(clip).toBeVisible()
  await clip.click()
  await expect(clip).toHaveClass(/\bsel\b/)
  await assertRuntimeGates(gates, testInfo)
})

test('[functional:track-rename] inline track rename persists', async ({ page }, testInfo) => {
  const gates = installRuntimeGates(page)
  await page.goto('/')
  await page.getByText('Video principal', { exact: true }).dblclick()
  const input = page.locator('input.rename').first()
  await expect(input).toBeFocused()
  await input.fill('Video QA')
  await input.press('Enter')
  await expect(page.getByText('Video QA', { exact: true })).toBeVisible()
  const response = await page.request.get('/api/state')
  expect(response.ok()).toBeTruthy()
  const state = await response.json()
  expect(state.project.tracks.find((track) => track.id === 'V1').name).toBe('Video QA')
  await assertRuntimeGates(gates, testInfo)
})

test('[functional:modal-focus] destructive track dialog is keyboard-safe', async ({ page }, testInfo) => {
  const gates = installRuntimeGates(page)
  await page.goto('/')
  const track = page.locator('.track').filter({
    has: page.getByText('Overlay QA', { exact: true }),
  }).first()
  const remove = track.getByTitle('Elimina la traccia')
  await remove.focus()
  await remove.click()
  const dialog = page.getByRole('dialog', { name: 'Eliminare la traccia?' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'annulla' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(remove).toBeFocused()
  await assertRuntimeGates(gates, testInfo)
})

test('[functional:track-delete] confirmation performs explicit destructive action', async ({ page }, testInfo) => {
  const gates = installRuntimeGates(page)
  await page.goto('/')
  const track = page.locator('.track').filter({
    has: page.getByText('Overlay QA', { exact: true }),
  }).first()
  await track.getByTitle('Elimina la traccia').click()
  const dialog = page.getByRole('dialog', { name: 'Eliminare la traccia?' })
  await dialog.getByRole('button', { name: 'elimina' }).click()
  await expect(page.getByText('Overlay QA', { exact: true })).toBeHidden()
  await assertRuntimeGates(gates, testInfo)
})

test('[functional:responsive] root layout remains bounded', async ({ page }, testInfo) => {
  const gates = installRuntimeGates(page)
  await page.goto('/')
  const metrics = await page.evaluate(() => ({
    innerWidth: window.innerWidth,
    innerHeight: window.innerHeight,
    bodyOverflow: getComputedStyle(document.body).overflow,
  }))
  const appBox = await page.locator('.app').boundingBox()
  expect(appBox).not.toBeNull()
  expect(appBox.x).toBeGreaterThanOrEqual(0)
  expect(appBox.y).toBeGreaterThanOrEqual(0)
  expect(appBox.x + appBox.width).toBeLessThanOrEqual(metrics.innerWidth + 1)
  expect(appBox.y + appBox.height).toBeLessThanOrEqual(metrics.innerHeight + 1)
  expect(metrics.bodyOverflow).toBe('hidden')
  await expect(page.getByRole('button', { name: /media/i }).first()).toBeVisible()
  await assertRuntimeGates(gates, testInfo)
})

test('[functional:timeline-scroll] timeline scroll container accepts scrolling', async ({ page }, testInfo) => {
  const gates = installRuntimeGates(page)
  await page.goto('/')
  const scroll = page.locator('.tl-scroll')
  await expect(scroll).toBeVisible()
  await scroll.evaluate((node) => { node.scrollLeft = 240 })
  await expect.poll(() => scroll.evaluate((node) => node.scrollLeft)).toBeGreaterThan(0)
  await assertRuntimeGates(gates, testInfo)
})
