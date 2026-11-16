import assert from 'node:assert/strict'
import process from 'node:process'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } })
const root = process.env.FRONTEND_URL || 'http://127.0.0.1:5187'
const errors = []
page.on('pageerror', error => errors.push(error.message))
const roles = ['small', 'complex', 'generator', 'play_agent', 'compression']
let saved = {
  custom_openai_url: 'http://shared.test/v1', custom_openai_timeout: 300,
  ...Object.fromEntries(roles.flatMap(role => [[`${role}_model_provider`, 'custom_openai'], [`${role}_model`, 'original-model'], [`${role}_custom_openai_url`, '']])),
}
const discovery = []
const tests = []
await page.route('**/api/**', async route => {
  const url = new URL(route.request().url())
  const path = url.pathname
  let data = {}
  if (path === '/api/settings/llm') { saved = route.request().postDataJSON(); data = { status: 'success' } }
  else if (path === '/api/settings/test-llm') { tests.push(route.request().postDataJSON()); data = { status: 'success', message: 'Mock connection passed.' } }
  else if (path === '/api/settings/llm-models') {
    const endpoint = url.searchParams.get('api_base'); discovery.push(endpoint)
    data = { models: [`model-at-${new URL(endpoint).hostname}`] }
  }
  else if (path === '/api/settings') data = { llm_settings: saved, keys: {}, is_llm_configured: true, available_constants: { llm_providers: [{ id: 'custom_openai', name: 'OpenAI-Compatible API' }, { id: 'ollama', name: 'Ollama' }], image_providers: [], predefined_llm_models: {}, predefined_image_models: {} } }
  else if (path.endsWith('/users')) data = []
  else if (path.endsWith('/inference-queue')) data = { enabled: true, reservations: [] }
  else if (path.endsWith('/npc-card-settings')) data = { show_state: false }
  else if (path.endsWith('/npcs/NPC_0')) {
    const offset = Number(url.searchParams.get('offset') || 0)
    const kind = url.searchParams.get('history')
    const entries = Array.from({ length: offset ? 3 : 40 }, (_, i) => ({ id: `${kind}-${offset + i}`, category: 'event', source: 'observed', text: `Memory ${offset + i}: ` + 'A detailed remembered conversation about medical work, personal goals and disagreements. '.repeat(4), evidence: 'An exact source passage.' }))
    data = { id: 'NPC_0', name: 'Dr. Rin Aoyama', description: 'An independent physician.', image_url: null, aliases: [], entry_count: 43, entries, has_more: !offset, history_counts: { general: 43, shared: 43 }, summary: entries.slice(0, 3), history_kind: kind }
  }
  else if (path.includes('models')) data = { models: [] }
  await route.fulfill({ json: data })
})
try {
  await page.goto(root + '/tests/browser/playerTools.html?view=input')
  const input = page.getByRole('textbox', { name: 'Your next action' })
  await input.fill('A long player action with carefully described movement and dialogue. '.repeat(16))
  const dimensions = await input.evaluate(node => ({ height: node.clientHeight, scroll: node.scrollHeight, width: node.clientWidth, scrollWidth: node.scrollWidth }))
  assert.ok(dimensions.height > 60 && dimensions.height <= 192)
  assert.ok(dimensions.scroll > dimensions.height && dimensions.scrollWidth <= dimensions.width)
  await input.fill('First action')
  await input.press('End')
  await input.press('Shift+Enter')
  await input.pressSequentially('Second action')
  assert.equal(await input.inputValue(), 'First action\nSecond action')
  await input.press('ArrowUp')
  assert.equal(await input.inputValue(), 'First action\nSecond action')
  await input.dispatchEvent('keydown', { key: 'Enter', isComposing: true })
  assert.equal(await page.locator('#sent').textContent(), '[]')
  await input.press('Enter')
  assert.deepEqual(JSON.parse(await page.locator('#sent').textContent()), ['First action\nSecond action'])
  assert.equal(await input.inputValue(), '')
  assert.ok(await input.evaluate(node => node.clientHeight) <= 50)
  await input.press('Alt+ArrowUp')
  assert.equal(await input.inputValue(), 'First action\nSecond action')
  await input.press('Alt+ArrowDown')
  assert.equal(await input.inputValue(), '')
  await page.setViewportSize({ width: 390, height: 844 })
  await input.fill('UnbrokenWord'.repeat(40))
  assert.equal(await input.evaluate(node => node.scrollWidth <= node.clientWidth), true)

  await page.setViewportSize({ width: 1400, height: 1000 })
  await page.goto(root + '/tests/browser/playerTools.html?view=npc')
  const panel = page.getByRole('tabpanel')
  await panel.getByText('Memory 39:', { exact: false }).waitFor()
  assert.ok(await panel.evaluate(node => node.scrollHeight > node.clientHeight))
  await panel.hover()
  await page.mouse.wheel(0, 1400)
  await page.waitForFunction(() => document.querySelector('[role="tabpanel"]').scrollTop > 0)
  await panel.focus()
  await panel.press('Control+End')
  await page.getByRole('button', { name: 'Load earlier entries' }).click()
  await panel.getByText('Memory 42:', { exact: false }).waitFor()
  assert.equal(await panel.locator('ol > li').count(), 43)
  const sharedTab = page.getByRole('tab', { name: /History with your character/ })
  await sharedTab.click()
  assert.equal(await panel.evaluate(node => node.scrollTop), 0)
  await page.getByText('All shared events', { exact: false }).click()
  await panel.getByText('Memory 39:', { exact: false }).waitFor()
  await page.getByRole('button', { name: 'Close character', exact: true }).click()
  assert.equal(await page.getByRole('dialog').count(), 0)

  await page.goto(root + '/tests/browser/playerTools.html?view=admin')
  await page.getByRole('button', { name: 'Intelligence (LLM)', exact: false }).click()
  await page.locator('[data-custom-api-role="small"]').waitFor()
  for (const role of roles) {
    const details = page.locator(`[data-custom-api-role="${role}"]`)
    await details.locator('summary').click()
    await page.getByRole('textbox', { name: `API URL — ${role}`, exact: true }).fill(`http://${role.replace('_', '-')}.test/v1`)
    await details.getByRole('button', { name: /Check models at this API URL/ }).click()
    await page.getByText(`model-at-${role.replace('_', '-')}.test`, { exact: true }).waitFor({ state: 'attached' })
    const card = details.locator('..')
    const choices = await card.locator('select').nth(1).locator('option').allTextContents()
    assert.ok(choices.includes(`model-at-${role.replace('_', '-')}.test`))
    assert.ok(!choices.includes('model-at-shared.test'))
    await Promise.all([
      page.waitForResponse(response => response.url().endsWith('/test-llm')),
      card.getByRole('button', { name: 'Test Model', exact: true }).click(),
    ])
    assert.equal(tests.at(-1).custom_openai_url, `http://${role.replace('_', '-')}.test/v1`)
    assert.equal(tests.at(-1).role, role)
  }
  await Promise.all([
    page.waitForResponse(response => response.url().endsWith('/llm') && response.request().method() === 'POST'),
    page.getByRole('button', { name: 'Save Routing', exact: true }).first().click(),
  ])
  assert.ok(roles.every(role => saved[`${role}_custom_openai_url`] === `http://${role.replace('_', '-')}.test/v1`))
  await page.getByRole('textbox', { name: 'Base URL', exact: true }).fill('http://new-shared.test/v1')
  await page.getByRole('button', { name: 'Use shared API URL for all roles', exact: true }).click()
  await Promise.all([
    page.waitForResponse(response => response.url().endsWith('/llm') && response.request().method() === 'POST'),
    page.getByRole('button', { name: 'Save Routing', exact: true }).first().click(),
  ])
  assert.ok(roles.every(role => saved[`${role}_custom_openai_url`] === '' && saved[`${role}_model`] === 'original-model'))
  assert.equal(saved.custom_openai_url, 'http://new-shared.test/v1')
  assert.ok(roles.every(role => discovery.includes(`http://${role.replace('_', '-')}.test/v1`)))
  assert.deepEqual(errors, [])
  console.log('PASS: multiline input and IME; scrollable paged NPC history; actual admin URL discovery, test and persistence across five roles.')
} finally { await browser.close() }
