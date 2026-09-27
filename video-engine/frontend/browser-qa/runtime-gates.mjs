import { expect } from '@playwright/test'

export function installRuntimeGates(page) {
  const state = {
    consoleErrors: [],
    pageErrors: [],
    networkFailures: [],
    nativeDialogs: [],
    websockets: 0,
    websocketErrors: [],
  }

  page.on('console', (message) => {
    if (message.type() === 'error') state.consoleErrors.push(message.text())
  })
  page.on('pageerror', (error) => state.pageErrors.push(String(error)))
  page.on('dialog', async (dialog) => {
    state.nativeDialogs.push({ type: dialog.type(), message: dialog.message() })
    await dialog.dismiss().catch(() => {})
  })
  page.on('websocket', (socket) => {
    state.websockets += 1
    socket.on('socketerror', (error) => state.websocketErrors.push(String(error)))
  })
  page.on('requestfailed', (request) => {
    const url = new URL(request.url())
    if (url.hostname === '127.0.0.1' || url.hostname === 'localhost') {
      state.networkFailures.push({
        url: request.url(),
        reason: request.failure()?.errorText || 'requestfailed',
      })
    }
  })
  page.on('response', (response) => {
    const url = new URL(response.url())
    if (
      (url.hostname === '127.0.0.1' || url.hostname === 'localhost')
      && response.status() >= 400
    ) {
      state.networkFailures.push({
        url: response.url(),
        reason: 'HTTP_' + response.status(),
      })
    }
  })
  return state
}

export async function resetFixture(page, identityProfile = 'desktop') {
  if (!['desktop', 'desktop-narrow'].includes(identityProfile)) {
    throw new Error('Browser QA identity profile is not allowlisted')
  }
  const response = await page.request.post(
    '/__qa/reset?identity_profile=' + encodeURIComponent(identityProfile),
  )
  expect(response.ok()).toBeTruthy()
  const payload = await response.json()
  expect(payload.single_store).toBe(true)
}

export async function assertRuntimeGates(state, testInfo) {
  await expect.poll(() => state.websockets).toBeGreaterThan(0)
  await testInfo.attach('runtime-gates.json', {
    body: Buffer.from(JSON.stringify(state, null, 2)),
    contentType: 'application/json',
  })
  expect(state.nativeDialogs, 'browser-native dialogs').toEqual([])
  expect(state.consoleErrors, 'unexpected console.error').toEqual([])
  expect(state.pageErrors, 'uncaught page errors').toEqual([])
  expect(state.websocketErrors, 'websocket errors').toEqual([])
  expect(state.networkFailures, 'first-party network failures').toEqual([])
}
