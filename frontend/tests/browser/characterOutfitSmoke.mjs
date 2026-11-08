import assert from 'node:assert/strict'
import process from 'node:process'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
const errors = [], requests = []
const bra = { item_id: 'BRA', name: 'Red bra', description: 'A red silk bra with neatly finished seams.', wearable_slots: ['Chest'], clothing: { layer: 0, coverage: ['torso'], underwear: true } }
const skirt = { name: 'Grey skirt', description: 'A grey wool skirt with precise seams.', wearable_slots: ['Legs'], clothing: { layer: 2, coverage: ['pelvis', 'legs'] } }
const context = { allow_underwear: true, owned: [{ id: 'COAT', name: 'White coat', worn: true, clothing: { layer: 3 } }, { id: 'BRA', name: 'Red bra', worn: false, clothing: bra.clothing }] }
try {
  for (const viewport of [{ width: 1340, height: 1000 }, { width: 390, height: 780 }]) {
    const page = await browser.newPage({ viewport })
    page.setDefaultTimeout(12000)
    page.on('pageerror', error => errors.push(error.message))
    let generation = 0, reads = 0
    await page.route('**/api/**', route => route.fulfill({ json: [] }))
    await page.route('**/api/adventures/outfit-fixture/editor/character-outfit?*', route => { reads++; return route.fulfill({ json: context }) })
    await page.route('**/api/adventures/outfit-fixture/editor/generate-character-outfit', route => {
      requests.push(route.request().postDataJSON())
      generation++
      return route.fulfill({ status: generation === 1 ? 503 : 200, json: generation === 1 ? { detail: 'Model busy; try again.' } : { context, notes: [], draft: { appearance: null, outfit: [bra, skirt] } } })
    })
    await page.goto((process.env.FRONTEND_URL || 'http://127.0.0.1:5206') + '/tests/browser/characterOutfit.html')
    await page.getByRole('button', { name: 'Generate clothing', exact: true }).click()
    const region = page.getByRole('region', { name: 'Generate character clothing', exact: true })
    await region.getByText('White coat · Worn · Layer 3', { exact: true }).waitFor()
    await region.getByText('Red bra · Carried · Layer 0', { exact: true }).waitFor()
    assert.equal(reads, 1)
    await region.getByLabel('Include underwear', { exact: true }).check()
    await region.getByRole('button', { name: 'Generate outfit draft', exact: true }).click()
    await region.getByRole('alert').filter({ hasText: 'Model busy' }).waitFor()
    await region.getByRole('button', { name: 'Generate outfit draft', exact: true }).click()
    await region.getByRole('checkbox', { name: 'Include Grey skirt', exact: true }).waitFor()
    await region.getByRole('checkbox', { name: 'Include Red bra', exact: true }).uncheck()
    await page.screenshot({ path: `/tmp/character-outfit-${viewport.width}.png` })
    await page.getByRole('button', { name: 'Apply Changes', exact: true }).click()
    await page.waitForFunction(() => document.getElementById('saved-outfit').textContent.length > 0)
    const saved = JSON.parse(await page.locator('#saved-outfit').textContent())
    assert.equal(saved.name, 'Rin')
    assert.deepEqual(saved.inventory, ['COAT', 'BRA', 'KEY'])
    assert.deepEqual(saved.outfit_completion.outfit.map(item => item.name), ['Grey skirt'])
    assert.deepEqual(requests.at(-1).inventory_ids, ['COAT', 'BRA', 'KEY'])
    assert.equal(requests.at(-1).include_underwear, true)
    assert.equal(reads, 1)
    await page.getByRole('button', { name: 'Edit character', exact: true }).click()
    await page.getByRole('button', { name: 'Generate clothing', exact: true }).waitFor()
    await page.getByRole('button', { name: 'Discard', exact: true }).click()
    await page.close()
  }
  assert.deepEqual(errors, [])
  console.log('Existing character outfit browser checks passed: desktop/mobile, worn/carried context, error/retry, selection, unchanged inventory and normal Apply Changes payload.')
} finally {
  await browser.close()
}
