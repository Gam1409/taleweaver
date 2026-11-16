import assert from 'node:assert/strict'
import process from 'node:process'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce' })
page.setDefaultTimeout(10000)
const errors = []
page.on('pageerror', error => errors.push(error.message))
const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5203'
const discoveries = () => page.getByRole('button', { name: /^Discoveries/ })
const passages = () => page.getByRole('button', { name: /^Passages/ })
async function panelBounds(label) {
  const box = await page.getByText(label, { exact: true }).locator('xpath=ancestor::div[contains(@class,"scene-hotspots-popover")]').boundingBox()
  const viewport = page.viewportSize()
  assert.ok(box.x >= 0 && box.y >= 0 && box.x + box.width <= viewport.width + 1 && box.y + box.height <= viewport.height + 1, `${label}: ${JSON.stringify(box)}`)
}
try {
  await page.goto(base + '/tests/browser/groupedActions.html')
  await page.locator('.game-character-stage').waitFor()
  const cards = page.locator('.emotion-portrait')
  assert.equal(await cards.count(), 3)
  for (const card of await cards.all()) {
    const box = await card.boundingBox()
    assert.ok(box.width >= 88, 'Mobile portraits need enough room for readable labels and separate controls.')
    assert.equal(await card.locator('h4').evaluate(node => node.scrollWidth <= node.clientWidth), true)
  }
  const change = await page.getByRole('button', { name: 'Change portrait of Mira', exact: true }).boundingBox()
  const speaking = await cards.nth(1).locator('.speaker-badge').boundingBox()
  assert.ok(change.x + change.width <= speaking.x || change.y + change.height <= speaking.y, 'Portrait editing must not cover the speaker indicator.')
  assert.equal(await page.locator('.bable-fish-container .lucide-fish').count(), 1)
  for (const width of [390, 320, 768, 1440]) {
    await page.setViewportSize({ width, height: 844 })
    if (width < 768) await page.getByRole('button', { name: 'Toggle interact menu', exact: true }).click()
    await discoveries().click()
    await panelBounds('Room Discoveries')
    await page.getByRole('button', { name: /^Take All/ }).click()
    await page.waitForFunction(() => window.groupedActionsFixture.events.includes('take:LETTER'))
    assert.equal(await page.evaluate(() => window.groupedActionsFixture.events.includes('take:COAST_MAP')), false)
    await passages().click()
    await panelBounds('Passages & Exits')
    await page.locator('.scene-hotspots-popover').getByText('Harbour path', { exact: true }).click()
    assert.equal(await page.evaluate(() => window.groupedActionsFixture.events.includes('passage:HARBOUR_PATH')), true)
    await page.getByTitle('Toggle Reading lamp', { exact: true }).click()
    assert.equal(await page.evaluate(() => window.groupedActionsFixture.events.includes('switch:READING_LAMP')), true)
    await page.getByRole('button', { name: /^System/ }).click()
    await panelBounds('System Messages')
    await page.keyboard.press('Escape')
    if (width < 768) await page.getByRole('button', { name: 'Toggle interact menu', exact: true }).click()
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  }
  assert.deepEqual(errors, [])
  console.log('PASS: readable mobile portraits, separate speaker controls, fish icon, discoveries, portable item pickup, passages, switches and system notices across four widths.')
} finally { await browser.close() }
