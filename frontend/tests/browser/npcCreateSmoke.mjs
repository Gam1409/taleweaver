import assert from 'node:assert/strict'
import process from 'node:process'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
const errors = [], generation = [], saved = []
const draft = {
  name: 'Rin', description: 'A meticulous doctor with dark hair and grey eyes.', goal: 'Identify the contamination.',
  character: 'Reserved, independent and principled.', gender: 'female', age_years: 32,
  appearance: { hair: 'dark hair', eyes: 'grey eyes', build: '', features: '' }, personality_profile: {},
  hp: 30, stamina: 20, mana: 0, moveable: true, is_killable: true,
  items: [
    { name: 'White coat', description: 'A crisp white coat with notched lapels and pearl buttons.',
      item_type: 'WEARABLE', is_portable: true, wearable_slots: ['Chest'], text_log_content: '', worn: true,
      clothing: { category: 'clothing', layer: 3, coverage: ['torso', 'arms'], opaque: true, underwear: false } },
    { name: 'Red bra', description: 'A silk bra with neat seams and adjustable straps.',
      item_type: 'WEARABLE', is_portable: true, wearable_slots: ['Chest'], text_log_content: '', worn: true,
      clothing: { category: 'clothing', layer: 0, coverage: ['torso'], opaque: true, underwear: true } },
    { name: 'Laboratory key', description: 'A brass key with a blue enamel tag.', item_type: 'DEFAULT',
      is_portable: true, wearable_slots: [], text_log_content: '', worn: false, clothing: null },
  ],
}
try {
  for (const viewport of [{ width: 1340, height: 950 }, { width: 390, height: 760 }]) {
    const page = await browser.newPage({ viewport })
    if (viewport.width === 390) await page.addInitScript(() => {
      Object.defineProperty(globalThis.crypto, 'randomUUID', { value: undefined, configurable: true })
    })
    page.setDefaultTimeout(12000)
    page.on('pageerror', error => errors.push(error.message))
    let attempts = 0, saves = 0, releaseLate
    const late = new Promise(resolve => { releaseLate = resolve })
    await page.route('**/api/adventures/npc-fixture/editor/generate-npc-draft', async route => {
      generation.push(route.request().postDataJSON())
      attempts++
      if (attempts === 3) await late
      await route.fulfill({ status: attempts === 1 ? 503 : 200, json: attempts === 1 ? { detail: 'NPC model unavailable. Retry.' } : draft })
    })
    await page.route('**/api/adventures/npc-fixture/editor/npc-with-items', async route => {
      saved.push(route.request().postDataJSON())
      saves++
      await route.fulfill({ status: saves === 1 ? 503 : 200, json: saves === 1 ? { detail: 'Could not save. Please retry.' } : { npc_id: 'NPC_RIN', item_ids: ['COAT', 'KEY'] } })
    })
    await page.goto((process.env.FRONTEND_URL || 'http://127.0.0.1:5206') + '/tests/browser/npcCreate.html')
    await page.getByRole('button', { name: 'New', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'New NPC', exact: true })
    const generate = dialog.getByRole('button', { name: 'Generate NPC draft', exact: true })
    assert.equal(await generate.isDisabled(), true)
    assert.equal(await dialog.getByLabel('Include underwear', { exact: true }).isDisabled(), true)
    await dialog.getByLabel('Age (optional)').fill('32')
    await dialog.getByLabel('Include underwear', { exact: true }).check()
    await dialog.getByRole('textbox', { name: 'Character description', exact: true }).fill('A reserved doctor with a white coat, red underwear and laboratory key.')
    await generate.click()
    await dialog.getByRole('alert').filter({ hasText: 'NPC model unavailable' }).waitFor()
    await generate.click()
    await dialog.getByRole('region', { name: 'Review NPC draft', exact: true }).waitFor()
    assert.equal(saved.length % 2, 0)
    await dialog.getByRole('textbox', { name: 'Name', exact: true }).fill('Rin Aoyama')
    await dialog.getByRole('checkbox', { name: 'Include Red bra', exact: true }).uncheck()
    await dialog.locator('summary').filter({ hasText: 'White coat' }).click()
    await dialog.getByRole('textbox', { name: 'Item description', exact: true }).first().fill('A crisp white medical coat with notched lapels, pearl buttons and neatly stitched pockets.')
    assert.equal(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth + 1), true)
    await page.screenshot({ path: `/tmp/new-npc-${viewport.width}.png` })
    const save = dialog.getByRole('button', { name: 'Create NPC & selected items', exact: true })
    await save.click()
    await dialog.getByRole('alert').filter({ hasText: 'Could not save' }).waitFor()
    await save.click()
    await dialog.waitFor({ state: 'hidden' })
    assert.equal(saved.at(-1).creation_id, saved.at(-2).creation_id)
    assert.equal(saved.at(-1).draft.name, 'Rin Aoyama')
    assert.deepEqual(saved.at(-1).draft.items.map(item => item.name), ['White coat', 'Laboratory key'])
    assert.equal(saved.at(-1).scene_id, 'LAB')
    assert.equal(generation.at(-1).include_underwear, true)
    await page.getByRole('button', { name: 'New', exact: true }).click()
    await dialog.getByRole('textbox', { name: 'Character description', exact: true }).fill('A different doctor.')
    await generate.click()
    await dialog.getByRole('button', { name: 'Close new NPC', exact: true }).click()
    await page.getByRole('button', { name: 'New', exact: true }).click()
    releaseLate()
    await page.waitForResponse(response => response.url().endsWith('/generate-npc-draft'))
    assert.equal(await dialog.getByRole('textbox', { name: 'Character description', exact: true }).inputValue(), '')
    await page.evaluate(() => document.getElementById('remove-scenes').click())
    await dialog.getByRole('alert').filter({ hasText: 'Add a scene' }).waitFor()
    assert.equal(await generate.isDisabled(), true)
    await page.keyboard.press('Escape')
    await dialog.waitFor({ state: 'hidden' })
    await page.close()
  }
  assert.deepEqual(errors, [])
  console.log('NPC browser checks passed: desktop/mobile, empty list, options, failed generation/retry, editable draft, selected belongings, idempotent save/retry, late result isolation and removed scenes.')
} finally {
  await browser.close()
}
