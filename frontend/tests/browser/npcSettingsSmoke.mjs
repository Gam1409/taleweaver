import assert from 'node:assert/strict'
import process from 'node:process'
import { mkdir } from 'node:fs/promises'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
const requests = []
const root = process.env.FRONTEND_URL || 'http://127.0.0.1:5187'
const output = process.env.SCREENSHOT_DIR || '/tmp/npc-settings-screenshots'
await mkdir(output, { recursive: true })
const prefs = { mode: 'off', actor_ids: [], max_active_npcs: 3, model_role: 'complex', max_output_tokens: 1200, max_input_chars: 24000, max_calls_per_turn: 8, memory_limit: 12, agent_steps: 0, failure_policy: 'continue' }
const world = { living_world_enabled: false, mode: 'PAUSE', deliberation_enabled: false, decision_engine: 'native', max_deliberations: 8 }
const finding = { code: 'NPC_TRAITS', message: 'Character traits are missing.', severity: 'warn', location: 'npc:NPC_0' }
await page.route('**/api/**', async route => {
  const path = new URL(route.request().url()).pathname
  requests.push(path)
  let data = {}
  if (path.includes('/items/COAT/repair')) {
    const item = { id: 'COAT', name: 'White laboratory coat', description: 'The crisp white fabric falls in clean folds. Neat seams frame its practical cut.', item_type: 'WEARABLE', is_portable: true, wearable_slots: ['Chest'], clothing: { layer: 3, coverage: ['torso', 'arms'], opaque: true, underwear: false, description: 'White coat' } }
    const body = route.request().postDataJSON() || {}
    const values = { ...item }; delete values.id
    if (path.endsWith('/preview')) data = { before_hash: 'original', values }
    else if (path.endsWith('/image')) data = { before_hash: 'original', image_url: '/data/preview.png' }
    else if (path.endsWith('/apply')) { assert.deepEqual(body.parts, ['text']); data = { before_hash: 'updated', item: { ...item, name: body.values.name, description: body.values.description } } }
    else data = { before_hash: 'original', item }
    await route.fulfill({ json: data }); return
  }
  if (path.endsWith('/validation/latest')) data = { ai_findings: [finding], structural_findings: [], run_at: '2026-11-06T00:00:00Z' }
  else if (path.endsWith('/suggest-fix')) data = { finding_signature: 'signature', proposals: [{ title: 'Restore the personality profile', summary: 'Fill authored traits.', rationale: 'Preserve individual voice.', patches: [{ target_type: 'npc', target_id: 'NPC_0', field_updates: { character: 'Independent physician.' } }] }] }
  else if (path.endsWith('/living-world')) data = { settings: world, revision: 0, status: 'PAUSED', cursor: 59, target: 59, pending_events: 0, last_run_events: 0, llm_calls: 0, recap: [], concordia_available: true }
  else if (path.endsWith('/chpm')) data = { module_version: '1.0.0', settings: prefs, revision: 0, available: true, characters: [{ id: 'NPC_0', name: 'Dr. Rin Aoyama' }], usage: { status: 'idle', calls: 0 }, trace: [], memory_counts: {}, agenda_counts: { active: 0, closed: 0 }, agenda: [] }
  else if (path.endsWith('/content-settings')) data = { enabled: false, level: 'soft' }
  else if (path.endsWith('/vn-settings')) data = { settings: { narration_pace: 'balanced' }, available: true }
  else if (path.endsWith('/dynamic-locations')) data = { policy: { enabled: false, scale: 'auto', generate_images: false } }
  else if (path.endsWith('/session-visual-presets') || path.endsWith('/visual-presets')) data = { source: 'current', selection: {}, presets: [] }
  else if (path.endsWith('/events')) data = { events: [], private_notes: {} }
  await route.fulfill({ json: data })
})
try {
  await page.goto(root + '/tests/browser/npcSettings.html?view=validation')
  await page.getByRole('button', { name: 'AI-Fix', exact: true }).click()
  await page.getByRole('heading', { name: 'AI Fix Suggestions' }).waitFor()
  assert.ok(requests.some(path => path.endsWith('/suggest-fix')))
  const fix = page.getByRole('dialog')
  const box = await fix.boundingBox()
  assert.ok(box.height >= 900 && box.y <= 0, `AI-Fix must cover the viewport, not its scrolling ancestor: ${JSON.stringify(box)}`)
  await page.getByText('Restore the personality profile', { exact: true }).waitFor()
  await page.goto(root + '/tests/browser/npcSettings.html?view=debug')
  await page.getByRole('button', { name: 'Clothing', exact: true }).first().waitFor()
  const labels = await page.getByRole('button', { name: 'Heal', exact: true }).first().locator('..').getByRole('button').allTextContents()
  assert.deepEqual(labels.slice(0, 3).map(value => value.trim()), ['Heal', 'Kill', 'Clothing'])
  const toolbar = await page.getByRole('button', { name: /^(Scene JSON|VN Settings)$/ }).evaluateAll(nodes => nodes.map(node => { const style = getComputedStyle(node); return [style.height, style.fontFamily, style.textTransform, style.borderRadius, style.backgroundColor] }))
  assert.deepEqual(toolbar[0], toolbar[1])
  assert.equal(await page.getByRole('toolbar', { name: 'Debug tools' }).getByRole('button').count(), 7)
  await page.screenshot({ path: output + '/debug-npcs.png' })
  await page.getByRole('button', { name: 'Clothing', exact: true }).first().click()
  await page.getByRole('heading', { name: 'Clothing — Dr. Rin Aoyama' }).waitFor()
  await page.getByRole('dialog').getByText('White laboratory coat', { exact: true }).waitFor()
  const layers = await page.getByRole('dialog').locator('[data-clothing-layer]').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().x))
  assert.equal(new Set(layers).size, 5)
  await page.screenshot({ path: output + '/debug-clothing.png' })
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
  await page.getByRole('button', { name: /^Items/ }).first().click()
  await page.getByRole('button', { name: 'Repair White laboratory coat', exact: true }).click()
  await page.getByRole('button', { name: 'Generate text & technical draft', exact: true }).click()
  await page.getByText('Draft ready.', { exact: false }).waitFor()
  const technical = page.getByRole('textbox', { name: 'Technical item JSON' })
  const validTechnical = await technical.inputValue()
  await page.getByRole('checkbox', { name: 'Apply technical fields', exact: true }).check()
  await technical.fill('{')
  await page.getByRole('button', { name: 'Apply selected sections', exact: true }).click()
  await page.getByText('Technical fields must be valid JSON.', { exact: false }).waitFor()
  assert.ok(!requests.some(path => path.endsWith('/repair/apply')))
  await technical.fill(validTechnical)
  await page.getByRole('checkbox', { name: 'Apply technical fields', exact: true }).uncheck()
  await page.getByRole('button', { name: 'Apply selected sections', exact: true }).click()
  await page.getByText('Selected sections saved.', { exact: false }).waitFor()
  await page.screenshot({ path: output + '/debug-item-repair.png' })
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()

  await page.getByRole('button', { name: 'VN Settings', exact: true }).click()
  await page.getByRole('heading', { name: 'VN Settings & Diagnostics' }).waitFor()
  await page.getByRole('heading', { name: 'NPC Personality', exact: true }).waitFor()
  await page.screenshot({ path: output + '/debug-vn-settings.png' })
  await page.goto(root + '/tests/browser/npcSettings.html?view=session')
  const columns = await page.locator('[aria-labelledby="session-story-settings"], [aria-labelledby="session-memory-settings"], [aria-labelledby="session-npc-settings"]').evaluateAll(nodes => nodes.map(node => ({ x: node.getBoundingClientRect().x, width: node.getBoundingClientRect().width })))
  assert.equal(new Set(columns.map(column => column.x)).size, 3)
  await page.screenshot({ path: output + '/session-settings-desktop.png' })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: output + '/session-settings-mobile.png' })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  assert.deepEqual(errors, [])
  console.log('PASS: AI-Fix request and viewport dialog; debug actions and VN diagnostics; three desktop columns and mobile bounds.')
} finally { await browser.close() }
