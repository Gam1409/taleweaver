import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const artifacts = process.env.AUTHORING_ARTIFACT_DIR || 'reports/authoring-persistence'
await mkdir(artifacts, { recursive: true })
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, reducedMotion: 'reduce' })
page.setDefaultTimeout(12000)
const errors = [], writes = []
page.on('pageerror', error => errors.push(error.message))
const adventure = { id: 'scroll-adventure', title: 'Workbench study', status: 'ready', rule_enforcement_mode: 'rpg', start_scene_id: 'LAB' }
const objects = [{ id: 'SW_FIXTURE', name: 'Control switch', description: 'A switch beside the workbench.', entity_type: 'OBJECT', item_type: 'SWITCH', current_scene_id: 'LAB',
  is_portable: false, metadata_json: { switch: { states: ['OFF', 'ON'], initial_state: 'OFF', transitions: [],
    on_success_script: "tw.vars.set('initial_success', True)", on_failure_script: "tw.vars.set('initial_failure', True)" } } }]
const npcs = [{ id: 'NPC_EXISTING', name: 'Ari', description: 'A careful technician.', entity_type: 'NPC', current_scene_id: 'LAB', hp: 20, stamina: 20, mana: 20, max_hp: 20, max_stamina: 20, max_mana: 20, inventory: [], stats: { hp: 20, stamina: 20, mana: 20 }, is_killable: true }]
const modal = () => page.locator('.entity-editor-dialog')
const scriptField = label => modal().locator('.script-editor-container').filter({ has: page.getByText(label, { exact: true }) }).locator('textarea')
async function section(name) {
  const select = page.locator('#editor-section')
  if (await select.isVisible()) await select.selectOption(name.toLowerCase())
  else await page.getByRole('button', { name, exact: true }).filter({ visible: true }).click()
}
async function save(label) {
  await modal().getByRole('button', { name: label, exact: true }).click()
  await modal().waitFor({ state: 'hidden' })
}
async function editSwitch() {
  await section('Items')
  await page.getByRole('button', { name: 'Actions for Control switch', exact: true }).click()
  await page.getByRole('button', { name: 'Edit Details', exact: true }).click()
  await modal().getByRole('button', { name: 'Rules & scripts', exact: true }).click()
}
async function editNpc() {
  const card = page.locator('div.relative.group').filter({ has: page.getByText('Ari', { exact: true }) })
  await card.locator('div.absolute.top-2.right-2 > button').click()
  await page.getByRole('button', { name: 'Edit Details', exact: true }).click()
  await modal().locator('summary').filter({ hasText: 'State & behaviour' }).click()
}
async function setResources(value) {
  for (const label of ['Health (HP)', 'Stamina (STM)', 'Mana (MAN)']) {
    const input = modal().getByText(label, { exact: true }).locator('..').locator('input')
    assert.equal(await input.count(), 1)
    await input.fill(value)
  }
}
try {
  await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort())
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname, method = request.method()
    let data
    if (path.endsWith('/editor/entity') && ['POST', 'PATCH'].includes(method)) {
      const body = request.postDataJSON()
      writes.push({ method, data: body })
      const collection = (body.entity_type === 'NPC' || body.target_type === 'npc') ? npcs : objects
      if (method === 'POST') collection.push({ ...body, ...body.metadata_json, id: body.entity_id, current_scene_id: body.scene_id })
      else {
        const entity = collection.find(entity => entity.id === body.target_id)
        Object.assign(entity, body)
        if (entity.item_type === 'SWITCH') Object.assign(entity.metadata_json.switch, {
          on_success_script: body.on_success_script, on_failure_script: body.on_failure_script,
        })
      }
      data = { status: 'success' }
    } else if (path.endsWith('/editor/generate-item-draft')) {
      data = { name: 'Supply chest', description: 'A sturdy supply chest.', item_type: request.postDataJSON().item_type,
        is_portable: true, wearable_slots: [], text_log_content: '', clothing: null }
    } else if (path.endsWith('/editor/assets')) {
      data = { adventure, objects, npcs, scenes: [{ id: 'LAB', name: 'Laboratory', label: 'Laboratory' }], entities_all: [], exits: [] }
    } else if (path === '/api/adventures/scroll-adventure') data = adventure
    else if (path.endsWith('/world-brief')) data = { setting: '', history: '', opening: '', characters: '', world_rules: '', open_threads: '', references: [] }
    else data = { image_styles_catalog: [], tone_catalog: [], tts_settings: {} }
    await route.fulfill({ json: data })
  })
  await page.goto((process.env.FRONTEND_URL || 'http://127.0.0.1:5219') + '/tests/browser/editorItemsScroll.html')
  await section('Items')
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  const add = page.getByRole('dialog', { name: 'Add item', exact: true })
  await add.getByLabel(/Item type/).selectOption('CONTAINER')
  await add.getByLabel('Create from description', { exact: true }).fill('A sturdy supply chest.')
  await add.getByRole('button', { name: 'Generate item draft', exact: true }).click()
  await modal().getByRole('textbox', { name: 'Entity identifier', exact: true }).fill('CHEST_BROWSER')
  await modal().getByText('Portable', { exact: true }).locator('..').getByRole('button').click()
  await modal().getByText('Locked State', { exact: true }).locator('../..').getByRole('button').click()
  await modal().getByText('Code To Unlock', { exact: true }).locator('..').locator('input').fill('1234')
  await modal().getByRole('button', { name: 'Deterministic Guard Expression' }).click()
  await scriptField('Deterministic Script Guard Expression').fill("tw.vars.get('permit', False)")
  await page.screenshot({ path: `${artifacts}/frontend-container-browser.png`, fullPage: true })
  await save('Create OBJECT')
  assert.equal(writes.at(-1).data.is_portable, false)
  assert.equal(writes.at(-1).data.metadata_json.locked, true)
  assert.equal(writes.at(-1).data.metadata_json.code_to_unlock, '1234')
  assert.equal(writes.at(-1).data.metadata_json.unlock_expression, "tw.vars.get('permit', False)")
  await editSwitch()
  assert.equal(await scriptField('Global On Success Script').inputValue(), "tw.vars.set('initial_success', True)")
  assert.equal(await scriptField('Global On Failure Script').inputValue(), "tw.vars.set('initial_failure', True)")
  await scriptField('Global On Success Script').fill("tw.vars.set('saved_success', True)")
  await scriptField('Global On Failure Script').fill("tw.vars.set('saved_failure', True)")
  await save('Apply Changes')
  assert.equal(writes.at(-1).data.on_success_script, "tw.vars.set('saved_success', True)")
  assert.equal(writes.at(-1).data.on_failure_script, "tw.vars.set('saved_failure', True)")
  await editSwitch()
  assert.equal(await scriptField('Global On Success Script').inputValue(), "tw.vars.set('saved_success', True)")
  await scriptField('Global On Success Script').fill('')
  await scriptField('Global On Failure Script').fill('')
  await save('Apply Changes')
  assert.equal(writes.at(-1).data.on_success_script, '')
  assert.equal(writes.at(-1).data.on_failure_script, '')
  await section('Inhabitants')
  await page.getByRole('button', { name: /Create NPC/ }).click()
  await modal().getByRole('textbox', { name: 'Entity identifier', exact: true }).fill('NPC_ZERO_BROWSER')
  await modal().locator('summary').filter({ hasText: 'State & behaviour' }).click()
  await setResources('0')
  await page.screenshot({ path: `${artifacts}/frontend-resources-browser.png`, fullPage: true })
  await save('Create NPC')
  const actor = writes.at(-1).data
  assert.deepEqual([actor.hp, actor.stamina, actor.mana], [0, 0, 0])
  await page.setViewportSize({ width: 390, height: 900 })
  await editNpc()
  await setResources('')
  await save('Apply Changes')
  for (const field of ['hp', 'stamina', 'mana']) assert.equal(field in writes.at(-1).data, false)
  assert.deepEqual([npcs[0].hp, npcs[0].stamina, npcs[0].mana], [20, 20, 20])
  await editNpc()
  await setResources('0')
  await save('Apply Changes')
  assert.deepEqual([writes.at(-1).data.hp, writes.at(-1).data.stamina, writes.at(-1).data.mana], [0, 0, 0])
  await editNpc()
  assert.equal(await modal().getByText('Health (HP)', { exact: true }).locator('..').locator('input').inputValue(), '0')
  await page.screenshot({ path: `${artifacts}/frontend-resources-mobile.png`, fullPage: true })
  await modal().getByRole('button', { name: 'Discard', exact: true }).click()
  assert.deepEqual(errors, [])
  await writeFile(`${artifacts}/frontend-browser-requests.json`, JSON.stringify(writes, null, 2) + '\n')
  console.log('PASS actual editor browser: container lock/guard/portability creation; switch legacy load/save/reopen/clear; manual NPC zero resources; mobile NPC blank omission/zero save/reload. All API/CDN traffic intercepted.')
} catch (error) {
  await page.screenshot({ path: `${artifacts}/frontend-browser-failure.png`, fullPage: true })
  throw error
} finally { await browser.close() }
