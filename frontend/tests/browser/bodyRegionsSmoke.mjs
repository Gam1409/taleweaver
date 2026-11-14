import assert from 'node:assert/strict'
import process from 'node:process'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5215'
try {
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto(`${base}/tests/browser/bodyRegions.html`)
    const dialog = page.getByRole('dialog', { name: 'Fictional character state', exact: true })
    await dialog.waitFor()
    await page.evaluate(async () => { await document.fonts.load('14px RPGAwesome'); await document.fonts.ready })
    await dialog.getByRole('checkbox', { name: 'Show empty slots', exact: true }).check()
    assert.equal(await dialog.locator('[data-equipment-slot^="Body"]').count(), 4)
    const boxes = await dialog.locator('[data-equipment-slot]').evaluateAll(nodes => nodes.map(node => ({ key: node.getAttribute('data-equipment-slot'), rect: node.getBoundingClientRect() })).filter(row => row.rect.width && row.rect.height).map(({ key, rect }) => ({ key, x: rect.x, y: rect.y, right: rect.right, bottom: rect.bottom })))
    for (const a of boxes) for (const b of boxes) {
      if (a.key >= b.key) continue
      assert.ok(a.right <= b.x + 1 || b.right <= a.x + 1 || a.bottom <= b.y + 1 || b.bottom <= a.y + 1, `${a.key} overlaps ${b.key} at ${width}`)
    }
    const hand = dialog.locator('[data-equipment-slot="Hands"]')
    await hand.click()
    const tooltip = page.getByRole('tooltip')
    await tooltip.waitFor()
    for (const text of ['A recorded cut on the hand.', 'Black glove', 'The cuff is torn.', 'Dust coats the glove.']) assert.ok((await tooltip.innerText()).includes(text))
    assert.ok(await tooltip.evaluate(node => !!node.closest('dialog[open]')), 'The popup must remain interactive in the active modal')
    if (width === 1440) await page.screenshot({ path: '/tmp/placement-regions-desktop.png' })
    await page.keyboard.press('Escape')
    await dialog.locator('[data-equipment-slot="BodyUterine"]').click()
    await tooltip.waitFor()
    assert.ok((await tooltip.innerText()).includes('A source-confirmed medical observation.'))
    assert.ok((await tooltip.innerText()).includes('Known from narration'))
    if (width === 390) await page.screenshot({ path: '/tmp/placement-regions-mobile.png' })
    await page.keyboard.press('Escape')
    await dialog.locator('[data-equipment-slot="BodyAnal"]').click()
    await tooltip.waitFor(); assert.match(await tooltip.innerText(), /confirmation/)
    await page.keyboard.press('Escape')
    await dialog.getByRole('checkbox', { name: 'Show empty slots', exact: true }).uncheck()
    assert.equal(await dialog.locator('[data-equipment-slot="BodyVaginal"]').count(), 0)
    assert.equal(await dialog.locator('[data-equipment-slot="BodyUterine"]').isVisible(), true, 'Known conditions stay discoverable without an item')
    await dialog.getByRole('button', { name: 'Unassessed layout', exact: true }).click()
    assert.equal(await dialog.locator('[data-equipment-slot^="Body"]').count(), 0)
    await dialog.getByText(/availability is not fully assessed/).waitFor()
    await dialog.getByRole('checkbox', { name: 'Show empty slots', exact: true }).check()
    assert.equal(await dialog.locator('[data-equipment-slot^="Body"]').count(), 4)
    await dialog.locator('[data-equipment-slot="BodyUterine"]').click()
    await tooltip.waitFor()
    assert.match(await tooltip.innerText(), /Availability not assessed/)
    assert.doesNotMatch(await tooltip.innerText(), /source-confirmed medical observation/)
  }
  assert.deepEqual(errors, [])
  console.log('Placement groups: four declared areas, grouped condition/item hover, source uncertainty, unknown layout and non-overlapping positions at desktop/mobile widths passed.')
} finally { await browser.close() }
