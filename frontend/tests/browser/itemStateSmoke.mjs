import assert from 'node:assert/strict'
import process from 'node:process'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
try {
  const page = await browser.newPage({ viewport: { width: 1360, height: 900 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto((process.env.FRONTEND_URL || 'http://127.0.0.1:5199') + '/tests/browser/itemState.html')
  const state = page.getByRole('region', { name: 'Current item state' })
  await state.getByText('Half full of water.', { exact: true }).waitFor()
  await page.getByText('An originally full metal flask.', { exact: true }).waitFor()
  await page.getByRole('button', { name: 'Empty the flask' }).click()
  await state.getByText('Empty. <script>not executable</script>', { exact: true }).waitFor()
  assert.equal(await state.locator('script').count(), 0)
  assert.equal(await page.getByText('Half full of water.', { exact: true }).count(), 0)
  for (const width of [1360, 390]) {
    await page.setViewportSize({ width, height: 900 })
    const box = await state.boundingBox()
    assert.ok(box && box.x >= 0 && box.x + box.width <= width)
    await page.screenshot({ path: `/tmp/item-state-${width}.png` })
  }
  await page.getByRole('button', { name: 'Show NPC equipment' }).click()
  await page.getByText('Item state · form', { exact: true }).waitFor()
  for (const width of [1360, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await page.getByRole('button', { name: 'Chest: Coat', exact: true }).click()
    const tooltip = page.getByRole('tooltip')
    await tooltip.getByText('The coat is crumpled.', { exact: true }).waitFor()
    const bounds = await tooltip.boundingBox()
    assert.ok(bounds && bounds.x >= 0 && bounds.x + bounds.width <= width)
    await page.screenshot({ path: `/tmp/item-state-npc-${width}.png` })
    await page.keyboard.press('Escape')
  }
  assert.deepEqual(errors, [])
  console.log('Item state browser checks passed.')
} finally { await browser.close() }
