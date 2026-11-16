import assert from 'node:assert/strict'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
const page = await browser.newPage()
const errors = []
page.on('pageerror', error => errors.push(error.message))
const settings = { living_world_enabled: false, mode: 'PAUSE', offline_time_scale: 1, max_catchup_game_hours: 6, max_events: 16, max_wall_seconds: 2, auto_catchup_on_resume: false, deliberation_enabled: false, decision_engine: 'native', auto_schedule: false, schedule_interval_minutes: 60, max_npcs: 4, max_decisions_per_run: 1, max_deliberations: 8, decision_max_tokens: 256 }
let state = { settings, revision: 0, status: 'PAUSED', cursor: 0, target: 60, pending_events: 1, last_run_events: 0, llm_calls: 0, recap: [], concordia_available: true }
let cycle = null
const calls = []
await page.route('**/api/adventures/fixture/living-world**', async route => {
  const suffix = new URL(route.request().url()).pathname.split('/living-world')[1]
  const method = route.request().method()
  calls.push([method, suffix])
  if (method === 'PATCH') state = { ...state, settings: route.request().postDataJSON().settings, revision: state.revision + 1 }
  if (suffix === '/cycle') {
    await new Promise(resolve => { cycle = resolve })
    return route.fulfill({ status: 409, json: { detail: 'The private decision was stopped. No result was applied.' } })
  }
  if (suffix === '/stop') { cycle?.(); return route.fulfill({ json: { stop_requested: true } }) }
  if (suffix === '/events') return route.fulfill({ json: { events: [], private_notes: { LILI: { goal: 'Visit the room.', belief: 'It might be quiet.', observations: ['Was in the hall.'] } } } })
  await route.fulfill({ json: state })
})
try {
  await page.goto((process.env.FRONTEND_URL || 'http://127.0.0.1:5179') + '/tests/browser/livingWorldSmoke.html')
  await page.getByLabel('Enable Living World for this session').check()
  await page.getByLabel('Allow bounded NPC decisions').check()
  await page.getByLabel(/Decision engine/).selectOption('concordia')
  await page.getByLabel('Schedule recurring NPC decisions').check()
  await page.getByRole('button', { name: 'Save Living World settings' }).click()
  await page.waitForFunction(() => document.querySelector('button[disabled]') !== null)
  assert.equal(state.settings.decision_engine, 'concordia')
  assert.equal(state.settings.auto_schedule, true)
  await page.getByRole('button', { name: 'Continue catch-up' }).click()
  await page.waitForFunction(() => document.body.textContent.includes('Working…'))
  await page.getByRole('button', { name: 'Stop after current event' }).click()
  await page.getByRole('alert').filter({ hasText: 'stopped' }).waitFor()
  await page.getByText('Private simulation journal (administrator)', { exact: true }).click()
  await page.getByText('Belief (unverified): It might be quiet.', { exact: true }).waitFor()
  assert.equal(calls.filter(([, suffix]) => suffix === '/cycle').length, 1)
  assert.deepEqual(errors, [])
  console.log('PASS: configure, save, Concordia selection, bounded cycle, stop, error recovery and private journal in Chromium')
} finally { await browser.close() }
