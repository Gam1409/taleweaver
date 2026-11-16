import assert from 'node:assert/strict'
import process from 'node:process'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
const errors = [], requests = []
page.on('pageerror', error => errors.push(error.message))
page.setDefaultTimeout(10000)
const draft = {
  name: 'Silk scarf', description: 'A silver-grey silk scarf with neatly rolled edges.',
  item_type: 'WEARABLE', is_portable: true, wearable_slots: ['Neck'], text_log_content: '',
  clothing: { category: 'clothing', layer: 3, coverage: ['torso'], opaque: true },
}
let releaseLate
const late = new Promise(resolve => { releaseLate = resolve })
try {
  await page.route('**/api/adventures/item-fixture/editor/generate-item-draft', async route => {
    requests.push(route.request().postDataJSON())
    const call = requests.length
    if (call === 3) await late
    await route.fulfill({ status: call === 1 ? 503 : 200,
      json: call === 1 ? { detail: 'The item model is unavailable. Please retry.' } : draft })
  })
  await page.goto((process.env.FRONTEND_URL || 'http://127.0.0.1:5206') + '/tests/browser/itemCreate.html')
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Add item', exact: true })
  const generate = dialog.getByRole('button', { name: 'Generate item draft', exact: true })
  assert.equal(await generate.isDisabled(), true)
  await dialog.getByRole('combobox', { name: 'Location' }).selectOption('LAB')
  await dialog.getByRole('combobox', { name: 'Item type' }).selectOption('WEARABLE')
  await dialog.locator('textarea').fill('A silver-grey silk scarf, worn around the neck. No magic.')
  await page.screenshot({ path: '/tmp/add-item-dialog.png', fullPage: true })
  await generate.click()
  await dialog.getByRole('alert').filter({ hasText: 'The item model is unavailable.' }).waitFor()
  assert.equal(await dialog.locator('textarea').inputValue(), 'A silver-grey silk scarf, worn around the neck. No magic.')
  assert.equal(await generate.isEnabled(), true)
  await generate.click()
  await dialog.waitFor({ state: 'hidden' })
  const review = JSON.parse(await page.locator('#review').textContent())
  assert.equal(review.sceneId, 'LAB')
  assert.equal(review.name, draft.name)
  assert.deepEqual(review.clothing, draft.clothing)
  assert.deepEqual(requests[1], { brief: 'A silver-grey silk scarf, worn around the neck. No magic.', item_type: 'WEARABLE', wearable_slots: [] })
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await dialog.locator('textarea').fill('Another scarf')
  const started = page.waitForRequest(request => request.url().endsWith('/generate-item-draft'))
  await generate.click()
  await started
  await dialog.getByRole('button', { name: 'Close add item' }).click()
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  releaseLate()
  await page.waitForResponse(response => response.url().endsWith('/generate-item-draft'))
  assert.equal(await dialog.locator('textarea').inputValue(), '')
  assert.equal(await generate.isDisabled(), true)
  assert.equal(await dialog.isVisible(), true)
  await page.evaluate(() => document.getElementById('remove-scenes').click())
  await dialog.getByRole('alert').filter({ hasText: 'Add a scene' }).waitFor()
  assert.equal(await dialog.locator('textarea').isDisabled(), true)
  assert.equal(await generate.isDisabled(), true)
  await page.keyboard.press('Escape')
  await dialog.waitFor({ state: 'hidden' })
  assert.equal(requests.length, 3)
  assert.deepEqual(errors, [])
  console.log('Add item browser checks passed: empty Items, location/type, model error and retry, review, closed-dialog isolation, missing scene and Escape.')
} finally {
  releaseLate()
  await browser.close()
}
