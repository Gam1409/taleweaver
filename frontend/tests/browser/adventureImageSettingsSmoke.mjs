import assert from 'node:assert/strict'
import process from 'node:process'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1380, height: 1080 } })
const errors = [], writes = [], generations = [], metadata = []
page.on('pageerror', error => errors.push(error.message))
page.setDefaultTimeout(10000)
let source = 'saved', releaseSave
const heldSave = new Promise(resolve => { releaseSave = resolve })
try {
  await page.route('**/api/adventures/adventure/visual-presets*', async route => {
    const request = route.request()
    if (request.method() === 'PUT') {
      writes.push(request.postDataJSON())
      if (writes.length === 1) return route.fulfill({ status: 503, json: { detail: 'Could not save. Please retry.' } })
      await heldSave
      source = 'current'
      return route.fulfill({ json: { source, selection: { background: 'old' } } })
    }
    metadata.push(Object.fromEntries(new URL(request.url()).searchParams))
    await route.fulfill({ json: {
      source, selection: { background: 'old' },
      effective: {
        provider: 'comfyui', preset_name: source === 'saved' ? 'Saved Anima' : 'Nova Anima',
        workflow_name: source === 'saved' ? 'Old background workflow' : 'Current background workflow', variant: 'generate',
        models: [{ node: 'model', loader: 'UNETLoader', input: 'unet_name',
          file: source === 'saved' ? 'missing-anima.safetensors' : 'installed-nova.safetensors', folder: 'models/diffusion_models' }],
      },
    } })
  })
  await page.route('**/api/settings/visual-jobs', async route => {
    generations.push(route.request().postDataJSON())
    await route.fulfill({ json: { id: generations[0].id, state: 'succeeded', message: 'Completed', result: { image_url: '/data/new.png' } } })
  })
  await page.goto((process.env.FRONTEND_URL || 'http://127.0.0.1:5206') + '/tests/browser/manualVision.html?image-settings')
  const panel = page.getByRole('region', { name: 'Adventure image settings' })
  await panel.getByText('Preset: Saved Anima', { exact: true }).waitFor()
  await panel.getByText('UNETLoader: missing-anima.safetensors', { exact: true }).waitFor()
  const selector = panel.getByRole('combobox', { name: 'Preset source' })
  await selector.selectOption('current')
  await panel.getByRole('button', { name: 'Apply image settings' }).click()
  await panel.getByRole('alert').filter({ hasText: 'Could not save' }).waitFor()
  assert.equal(await panel.getByText('Preset: Saved Anima', { exact: true }).isVisible(), true)
  const started = page.waitForRequest(request => request.method() === 'PUT' && request.url().includes('/visual-presets'))
  await panel.getByRole('button', { name: 'Apply image settings' }).click()
  await started
  assert.equal(await page.getByRole('button', { name: 'Generate Vision' }).isDisabled(), true)
  assert.equal(generations.length, 0)
  releaseSave()
  await panel.getByText('Preset: Nova Anima', { exact: true }).waitFor()
  await panel.getByText('UNETLoader: installed-nova.safetensors', { exact: true }).waitFor()
  assert.equal(await selector.inputValue(), 'current')
  assert.equal(await panel.getByRole('alert').count(), 0)
  await page.screenshot({ path: '/tmp/adventure-image-settings.png', fullPage: true })
  assert.deepEqual(writes, [{ source: 'current' }, { source: 'current' }])
  assert.ok(metadata.every(query => query.purpose === 'background' && query.advanced === 'false' && query.reference === 'false'))
  await page.getByRole('button', { name: 'Generate Vision' }).click()
  await panel.waitFor({ state: 'hidden' })
  assert.equal(generations.length, 1)
  assert.equal(generations[0].operation, 'asset')
  assert.equal(generations[0].template_id, 'adventure')
  assert.equal(generations[0].payload.target_type, 'scene')
  assert.equal(generations[0].payload.target_id, 'LAB')
  assert.deepEqual(errors, [])
  console.log('Adventure image settings browser checks passed: actual saved workflow, source error/retry, save-before-generate, global workflow and scene image submission.')
} finally {
  releaseSave()
  await browser.close()
}
