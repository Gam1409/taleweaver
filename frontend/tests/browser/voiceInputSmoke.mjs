import assert from 'node:assert/strict'
import process from 'node:process'
import { mkdir } from 'node:fs/promises'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5217'
const artifacts = process.env.VOICE_ARTIFACT_DIR || 'reports/voice-input'
await mkdir(artifacts, { recursive: true })
const suffix = process.env.VOICE_PROOF_SUFFIX || 'green'
const failures = []
let caseNumber = 0
async function check(name, action) {
  const proofNumber = ++caseNumber
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  page.setDefaultTimeout(10000)
  await page.addInitScript(() => {
    const permissions = [], streams = [], contexts = [], requests = []
    let offset = 0
    const now = Date.now.bind(Date)
    Date.now = () => now() + offset
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia() { return new Promise(resolve => permissions.push(resolve)) } } })
    window.AudioContext = class {
      state = 'running'; destination = {}; closed = 0
      constructor() { this.source = { disconnected: 0, connect() {}, disconnect() { this.disconnected++ } }; this.processor = { disconnected: 0, connect() {}, disconnect() { this.disconnected++ } }; contexts.push(this) }
      createMediaStreamSource() { return this.source }
      createScriptProcessor() { return this.processor }
      close() { this.state = 'closed'; this.closed++; return Promise.resolve() }
    }
    const originalFetch = window.fetch.bind(window)
    window.fetch = (input, options) => {
      const path = String(input)
      if (path.endsWith('/stt/transcribe')) return new Promise(resolve => { requests.push({ signal: options.signal, finish: text => resolve(Response.json({ text })) }) })
      if (path.includes('/api/')) return Promise.resolve(Response.json({ items: [], available: false, settings: { enabled: false } }))
      return originalFetch(input, options)
    }
    Object.assign(window, { voiceMedia: {
      permissions, streams, contexts, requests,
      advance(value) { offset += value },
      grant(index = permissions.length - 1) { const track = { stopped: 0, stop() { this.stopped++ } }, stream = { track, getTracks: () => [track] }; streams.push(stream); permissions[index](stream) },
      samples() { contexts.at(-1).processor.onaudioprocess({ inputBuffer: { getChannelData: () => new Float32Array([0.25, -0.5]) } }) },
    } })
  })
  try {
    await page.goto(base + '/tests/browser/voiceInput.html')
    await page.getByRole('textbox', { name: 'Your next action' }).waitFor()
    await action(page)
    assert.deepEqual(errors, [])
    console.log(`PASS ${name}`)
  } catch (error) { failures.push(`${name}: ${error.message}`); console.error(`FAIL ${name}: ${error.message}`) }
  finally { await page.screenshot({ path: `${artifacts}/voice-browser-${suffix}-${proofNumber}.png` }); await page.close() }
}
const input = page => page.getByRole('textbox', { name: 'Your next action' })
async function pressMic(page) { const box = await page.getByTitle('Push-To-Talk (Hold to speak)', { exact: true }).boundingBox(); await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.down() }
async function record(page, say = false) {
  const before = await page.evaluate(() => window.voiceMedia.requests.length)
  if (say) await page.keyboard.down('Shift')
  await pressMic(page)
  await page.evaluate(() => window.voiceMedia.grant())
  await page.getByText('PTT Active: Recording Voice...', { exact: true }).waitFor()
  await page.evaluate(() => { window.voiceMedia.samples(); window.voiceMedia.advance(600) })
  await page.mouse.up()
  if (say) await page.keyboard.up('Shift')
  await page.waitForFunction(count => window.voiceMedia.requests.length > count, before)
}
try {
  await check('late session A transcription preserves session B draft and route instance', async page => {
    await record(page)
    await page.evaluate(() => window.voiceFixture.switchSession('B'))
    await input(page).fill('Keep the new-session draft')
    await page.evaluate(() => window.voiceMedia.requests[0].finish('Old-session spoken action'))
    await page.waitForTimeout(80)
    assert.equal(await input(page).inputValue(), 'Keep the new-session draft')
    assert.deepEqual(await page.evaluate(() => window.voiceFixture.sends.value), [])
    assert.equal(await page.evaluate(() => window.voiceFixture.routeInstances), 1)
    assert.equal(await page.evaluate(() => window.voiceMedia.requests[0].signal.aborted), true)
    assert.equal(await page.evaluate(() => window.voiceFixture.health.reachable), true)
  })
  await check('permission after release or session change stops the returned microphone', async page => {
    await pressMic(page); await page.mouse.up()
    await page.evaluate(() => window.voiceFixture.switchSession('B'))
    await page.evaluate(() => window.voiceMedia.grant())
    await page.waitForTimeout(60)
    assert.equal(await page.evaluate(() => window.voiceMedia.streams[0].track.stopped), 1)
    assert.equal(await page.evaluate(() => window.voiceMedia.contexts.length), 0)
    assert.equal(await page.getByText('PTT Active: Recording Voice...', { exact: true }).count(), 0)
  })
  for (const phase of ['permission', 'recording', 'transcription']) await check(`unmount during ${phase} discards voice and releases media`, async page => {
    if (phase === 'transcription') await record(page)
    else {
      await pressMic(page)
      if (phase === 'recording') { await page.evaluate(() => window.voiceMedia.grant()); await page.getByText('PTT Active: Recording Voice...', { exact: true }).waitFor() }
    }
    await page.evaluate(() => window.voiceFixture.leave())
    if (phase === 'permission') await page.evaluate(() => window.voiceMedia.grant())
    if (phase === 'transcription') await page.evaluate(() => window.voiceMedia.requests[0].finish('Discarded speech'))
    await page.mouse.up(); await page.waitForTimeout(60)
    assert.deepEqual(await page.evaluate(() => window.voiceFixture.sends.value), [])
    assert.equal(await page.evaluate(() => window.voiceMedia.streams[0].track.stopped), 1)
    if (phase !== 'permission') assert.equal(await page.evaluate(() => window.voiceMedia.contexts[0].closed), 1)
    if (phase === 'transcription') assert.equal(await page.evaluate(() => window.voiceMedia.requests[0].signal.aborted), true)
    if (phase !== 'transcription') assert.equal(await page.evaluate(() => window.voiceMedia.requests.length), 0)
  })
  await check('same-session draft edits survive while ordinary voice still merges and autosends', async page => {
    await input(page).fill('Original draft'); await record(page)
    await input(page).fill('Edited draft')
    await page.evaluate(() => window.voiceMedia.requests[0].finish('Stale speech'))
    await page.waitForTimeout(60)
    assert.equal(await input(page).inputValue(), 'Edited draft')
    assert.deepEqual(await page.evaluate(() => window.voiceFixture.sends.value), [])
    await record(page, true)
    await page.evaluate(() => window.voiceMedia.requests[1].finish('Fresh speech'))
    await page.waitForFunction(() => window.voiceFixture.sends.value.length === 1)
    assert.deepEqual(await page.evaluate(() => window.voiceFixture.sends.value), [{ session: 'A', text: 'Edited draft /say Fresh speech' }])
    assert.equal(await input(page).inputValue(), '')
  })
  assert.deepEqual(failures, [])
} finally { await browser.close() }
