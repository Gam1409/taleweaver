import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5223'
const artifacts = process.env.CHAT_ARTIFACT_DIR || 'reports/chat-interactions'
const suffix = process.env.CHAT_PROOF_SUFFIX || 'green'
await mkdir(artifacts, { recursive: true })
const failures = []
let number = 0
async function check(name, action, mobile = false) {
  if (process.env.CHAT_CASE_FILTER && !name.includes(process.env.CHAT_CASE_FILTER)) return
  const page = await browser.newPage({ viewport: mobile ? { width: 390, height: 844 } : { width: 1280, height: 900 }, hasTouch: mobile })
  const errors = [], proof = ++number
  page.on('pageerror', error => errors.push(error.message))
  page.setDefaultTimeout(5000)
  await page.route('https://**', route => route.abort())
  try { await action(page); assert.deepEqual(errors, []); console.log(`PASS ${name}`) }
  catch (error) { failures.push(name); console.error(`FAIL ${name}: ${error.message}`) }
  finally { await page.screenshot({ path: `${artifacts}/chat-${suffix}-${proof}.png` }); await page.close() }
}
async function openMap(page) {
  await page.goto(base + '/tests/browser/groupedActions.html')
  await page.getByRole('button', { name: 'World', exact: true }).click()
  await page.getByRole('menuitem', { name: /World map/ }).click()
  await page.getByRole('heading', { name: 'World Map', exact: true }).waitFor()
  await page.waitForTimeout(350)
}
async function mockMic(page) {
  await page.addInitScript(() => {
    const permissions = [], streams = [], contexts = [], requests = []
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia() { return new Promise(resolve => permissions.push(resolve)) } } })
    window.AudioContext = class {
      state = 'running'; destination = {}; closed = 0
      constructor() { this.source = { connect() {}, disconnect() {} }; this.processor = { connect() {}, disconnect() {} }; contexts.push(this) }
      createMediaStreamSource() { return this.source }
      createScriptProcessor() { return this.processor }
      close() { this.state = 'closed'; this.closed++; return Promise.resolve() }
    }
    const original = window.fetch.bind(window)
    window.fetch = (input, options) => {
      if (String(input).endsWith('/stt/transcribe')) { requests.push(options); return Promise.resolve(Response.json({ text: 'Example speech' })) }
      if (String(input).includes('/api/')) return Promise.resolve(Response.json({ items: [], available: false, settings: { enabled: false } }))
      return original(input, options)
    }
    window.chatMic = { permissions, streams, contexts, requests, grant() { const track = { stopped: 0, stop() { this.stopped++ } }; streams.push(track); permissions.at(-1)({ getTracks: () => [track] }) } }
  })
}
const touchSessions = new WeakMap()
async function touch(page, type, points) {
  if (!touchSessions.has(page)) touchSessions.set(page, await page.context().newCDPSession(page))
  const cdp = touchSessions.get(page)
  await cdp.send('Input.dispatchTouchEvent', { type, touchPoints: points })
}
try {
  await check('touch hold starts the microphone before release; cancel discards it', async page => {
    await mockMic(page)
    await page.goto(base + '/tests/browser/voiceInput.html')
    const mic = page.getByTitle('Push-To-Talk (Hold to speak)', { exact: true }), box = await mic.boundingBox()
    await touch(page, 'touchStart', [{ x: box.x + box.width / 2, y: box.y + box.height / 2 }])
    await page.waitForTimeout(100)
    assert.equal(await page.evaluate(() => window.chatMic.permissions.length), 1)
    await page.evaluate(() => window.chatMic.grant())
    await page.getByText('PTT Active: Recording Voice...', { exact: true }).waitFor()
    await page.waitForTimeout(600)
    await touch(page, 'touchCancel', [])
    await page.waitForTimeout(100)
    assert.equal(await page.evaluate(() => window.chatMic.streams[0].stopped), 1)
    assert.equal(await page.evaluate(() => window.chatMic.contexts[0].closed), 1)
    assert.equal(await page.evaluate(() => window.chatMic.requests.length), 0)
    assert.deepEqual(await page.evaluate(() => window.voiceFixture.sends.value), [])
    assert.equal(await page.evaluate(() => window.chatMic.permissions.length), 1)
  }, true)
  await check('touch release outside the microphone submits once and suppresses compatibility mouse start', async page => {
    await mockMic(page)
    await page.goto(base + '/tests/browser/voiceInput.html')
    const box = await page.getByTitle('Push-To-Talk (Hold to speak)', { exact: true }).boundingBox()
    const start = { x: box.x + box.width / 2, y: box.y + box.height / 2 }
    await touch(page, 'touchStart', [start])
    await page.waitForFunction(() => window.chatMic.permissions.length === 1)
    await page.evaluate(() => window.chatMic.grant())
    await page.getByText('PTT Active: Recording Voice...', { exact: true }).waitFor()
    await page.evaluate(() => window.chatMic.contexts[0].processor.onaudioprocess({ inputBuffer: { getChannelData: () => new Float32Array([0.3]) } }))
    await page.keyboard.press('v')
    await page.waitForTimeout(600)
    await touch(page, 'touchMove', [{ x: start.x + 100, y: start.y - 100 }])
    await touch(page, 'touchEnd', [])
    await page.waitForFunction(() => window.voiceFixture.sends.value.length === 1)
    assert.equal(await page.evaluate(() => window.chatMic.permissions.length), 1)
    assert.equal(await page.evaluate(() => window.chatMic.requests.length), 1)
    assert.equal(await page.evaluate(() => window.chatMic.streams[0].stopped), 1)
    assert.deepEqual(await page.evaluate(() => window.voiceFixture.sends.value), [{ session: 'A', text: 'Example speech' }])
  }, true)
  await check('touch release before permission stops its late stream', async page => {
    await mockMic(page)
    await page.goto(base + '/tests/browser/voiceInput.html')
    const box = await page.getByTitle('Push-To-Talk (Hold to speak)', { exact: true }).boundingBox()
    await touch(page, 'touchStart', [{ x: box.x + box.width / 2, y: box.y + box.height / 2 }])
    await touch(page, 'touchEnd', [])
    await page.evaluate(() => window.chatMic.grant())
    await page.waitForTimeout(100)
    assert.equal(await page.evaluate(() => window.chatMic.streams[0].stopped), 1)
    assert.equal(await page.evaluate(() => window.chatMic.contexts.length), 0)
    assert.equal(await page.evaluate(() => window.chatMic.requests.length), 0)
  }, true)
  await check('map keyboard focus cannot start background push-to-talk', async page => {
    await mockMic(page)
    await openMap(page)
    await page.keyboard.press('v')
    assert.equal(await page.evaluate(() => window.chatMic.permissions.length), 0)
  })
  for (const mobile of [false, true]) await check(`map focus stays modal and returns to its opener (${mobile ? 'mobile' : 'desktop'})`, async page => {
    await openMap(page)
    const dialog = page.getByRole('dialog', { name: 'World Map', exact: true })
    assert.equal(await dialog.evaluate(node => node.contains(document.activeElement)), true)
    for (const key of ['Tab', 'Shift+Tab', 'Tab', 'Tab', 'Tab', 'Tab', 'Tab', 'Tab']) {
      await page.keyboard.press(key)
      assert.equal(await dialog.evaluate(node => node.contains(document.activeElement)), true)
    }
    await page.keyboard.press('Escape')
    await dialog.waitFor({ state: 'hidden' })
    await page.waitForFunction(() => document.activeElement?.textContent.trim() === 'World')
    await page.keyboard.press('Tab')
    await page.keyboard.press('Enter')
    assert.equal(await page.getByRole('menuitem', { name: /Quests/ }).isVisible(), true)
  }, mobile)
  for (const mobile of [false, true]) await check(`pinch preserves the scene under its stationary midpoint (${mobile ? 'mobile' : 'desktop'})`, async page => {
    await openMap(page)
    const map = page.locator('div.touch-none'), node = map.locator('.pointer-events-auto.cursor-pointer.group').filter({ hasText: 'Old Archive' })
    const before = await node.boundingBox(), center = { x: before.x + before.width / 2, y: before.y + before.height / 2 }
    for (const [type, id, dx] of [['pointerdown', 1, -40], ['pointerdown', 2, 40], ['pointermove', 1, -60], ['pointermove', 2, 60]]) {
      await map.dispatchEvent(type, { pointerId: id, pointerType: 'touch', clientX: center.x + dx, clientY: center.y })
    }
    const after = await node.boundingBox()
    assert.ok(Math.abs(after.width / before.width - 1.5) < 0.01)
    assert.ok(Math.abs(after.x + after.width / 2 - center.x) < 1, 'pinch midpoint drifted horizontally')
    assert.ok(Math.abs(after.y + after.height / 2 - center.y) < 1, 'pinch midpoint drifted vertically')
    await page.screenshot({ path: `${artifacts}/chat-map-open-${suffix}-${mobile ? 'mobile' : 'desktop'}.png` })
    await map.dispatchEvent('pointercancel', { pointerId: 1, pointerType: 'touch' })
    await map.dispatchEvent('pointerup', { pointerId: 2, pointerType: 'touch' })
    await page.keyboard.press('Escape')
  }, mobile)
  for (const width of [390, 320]) await check(`mobile map centers its current scene on open, reset and reopen at ${width}px`, async page => {
    await page.setViewportSize({ width, height: 844 })
    await openMap(page)
    const map = page.locator('div.touch-none'), node = map.locator('.pointer-events-auto.cursor-pointer.group').filter({ hasText: 'Old Archive' })
    const centered = async () => {
      const viewport = await map.boundingBox(), card = await node.boundingBox()
      assert.ok(Math.abs(card.x + card.width / 2 - viewport.x - viewport.width / 2) < 1, JSON.stringify({ viewport, card }))
      assert.ok(Math.abs(card.y + card.height / 2 - viewport.y - viewport.height / 2) < 1)
      assert.ok(card.x >= viewport.x && card.x + card.width <= viewport.x + viewport.width)
      assert.ok(card.y >= viewport.y && card.y + card.height <= viewport.y + viewport.height)
    }
    await centered()
    await map.dispatchEvent('pointerdown', { pointerId: 1, pointerType: 'touch', clientX: 100, clientY: 250 })
    await map.dispatchEvent('pointermove', { pointerId: 1, pointerType: 'touch', clientX: 180, clientY: 300 })
    await map.dispatchEvent('pointerup', { pointerId: 1, pointerType: 'touch' })
    await page.getByTitle('Zoom In', { exact: true }).click()
    await page.getByTitle('Reset View', { exact: true }).click()
    await centered()
    await page.keyboard.press('Escape')
    await page.getByRole('heading', { name: 'World Map', exact: true }).waitFor({ state: 'hidden' })
    await page.getByRole('button', { name: 'World', exact: true }).click()
    await page.getByRole('menuitem', { name: /World map/ }).click()
    await page.waitForTimeout(350)
    await centered()
    await page.screenshot({ path: `${artifacts}/chat-map-centered-${suffix}-${width}.png` })
  }, true)
  for (const error of [false, true]) await check(`late Agent ${error ? 'error' : 'success'} cannot change a newly connected session`, async page => {
    await page.goto(base + '/tests/browser/sessionOwnership.html')
    await page.getByLabel('Connection status', { exact: true }).filter({ hasText: 'connected' }).waitFor()
    await page.getByRole('button', { name: 'Save automatic mode', exact: true }).click()
    await page.waitForFunction(() => window.sessionOwnershipFixture.settings.length === 1)
    await page.getByRole('button', { name: 'Open B', exact: true }).click()
    await page.getByLabel('Session sheet', { exact: true }).filter({ hasText: 'Example B' }).waitFor()
    await page.evaluate(error => window.sessionOwnershipFixture.settings[0].finish(error), error)
    await page.waitForTimeout(1650)
    assert.equal(await page.evaluate(() => window.sessionOwnershipFixture.settings[0].signal.aborted), true)
    assert.equal(await page.evaluate(() => window.sessionOwnershipFixture.socket.sheet.value.agent_active), false)
    assert.equal(await page.evaluate(() => window.sessionOwnershipFixture.socket.sheet.value.agent_step_by_step), true)
    assert.equal(await page.evaluate(() => window.sessionOwnershipFixture.notifications.value.length), 0)
    assert.equal(await page.evaluate(() => window.sessionOwnershipFixture.requests.filter(item => item.path.endsWith('/agent/turn')).length), 0)
  })
  for (const ending of ['switch', 'unmount']) await check(`late alias resolution cannot navigate after ${ending}`, async page => {
    await page.goto(base + '/tests/browser/sessionOwnership.html')
    await page.getByRole('button', { name: 'Open old-template', exact: true }).click()
    await page.waitForFunction(() => window.sessionOwnershipFixture.aliases.length === 1)
    if (ending === 'switch') {
      await page.getByRole('button', { name: 'Open B', exact: true }).click()
      await page.getByLabel('Session sheet', { exact: true }).filter({ hasText: 'Example B' }).waitFor()
    } else await page.evaluate(() => window.sessionOwnershipFixture.leave())
    const before = await page.evaluate(() => window.sessionOwnershipFixture.route)
    await page.evaluate(() => window.sessionOwnershipFixture.aliases[0]('resolved-old-session'))
    await page.waitForTimeout(100)
    assert.equal(await page.evaluate(() => window.sessionOwnershipFixture.route), before)
  })
} finally { await browser.close() }
if (failures.length) throw new Error(`${failures.length} chat interaction regressions failed: ${failures.join('; ')}`)
