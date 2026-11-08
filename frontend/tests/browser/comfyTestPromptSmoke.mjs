import assert from 'node:assert/strict'
import process from 'node:process'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1460, height: 1060 } })
const errors = [], requests = [], previews = []
page.on('pageerror', error => errors.push(error.message))
page.setDefaultTimeout(10000)
try {
  await page.route('**/api/settings/comfyui/**', async route => {
    const path = new URL(route.request().url()).pathname.split('/').at(-1)
    if (path === 'preview-prompt') {
      previews.push(route.request().postDataJSON())
      return route.fulfill({ json: { body: 'A lone traveler beside a stone bridge.', positive: 'masterpiece A lone traveler beside a stone bridge.', negative: 'text' } })
    }
    await route.fulfill({ json: path === 'detect-template' ? { template_id: null, models: [], message: '' } : [] })
  })
  await page.route('**/api/settings/visual-jobs', async route => {
    const request = route.request().postDataJSON()
    requests.push(request)
    await route.fulfill({ json: { id: request.id, state: 'succeeded', message: 'Completed', result: {
      status: 'success', message: 'Image generation successful!\nTested UNETLoader: installed-nova.safetensors',
      image_url: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aPUkAAAAASUVORK5CYII=',
    } } })
  })
  await page.goto((process.env.FRONTEND_URL || 'http://127.0.0.1:5206') + '/tests/browser/comfyTestPrompt.html')
  await page.getByRole('button', { name: 'Manage presets & assignments' }).click()
  await page.getByRole('button', { name: 'Location backgrounds', exact: true }).click()
  await page.getByRole('button', { name: 'Edit preset / create copy' }).click()
  await page.getByRole('tab', { name: 'Workflow', exact: true }).click()
  await page.getByRole('combobox', { name: 'Saved workflows' }).selectOption('installed')
  await page.getByRole('tab', { name: 'Test', exact: true }).click()
  const example = page.getByRole('textbox', { name: 'Example description' })
  await example.fill('A traveler by a bridge.')
  await page.getByRole('button', { name: 'Preview prompt', exact: true }).click()
  await page.getByText('masterpiece A lone traveler beside a stone bridge.', { exact: true }).waitFor()
  await page.getByRole('button', { name: 'Generate test image', exact: true }).click()
  await page.getByRole('img', { name: 'Preset test result' }).waitFor()
  assert.equal(previews[0].description, 'A traveler by a bridge.')
  assert.equal(requests[0].payload.test_prompt, 'A traveler by a bridge.')
  assert.equal(requests[0].payload.prepared_body, 'A lone traveler beside a stone bridge.')
  assert.equal(requests[0].payload.image_purpose, 'background')
  await example.fill('A cat sleeping on a chair.')
  assert.equal(await page.getByRole('img', { name: 'Preset test result' }).count(), 0)
  await page.getByRole('button', { name: 'Generate test image', exact: true }).click()
  await page.getByRole('img', { name: 'Preset test result' }).waitFor()
  assert.equal(requests[1].payload.test_prompt, 'A cat sleeping on a chair.')
  assert.equal(requests[1].payload.prepared_body, undefined)
  await page.getByRole('button', { name: 'Apply to form', exact: true }).click()
  await page.getByRole('button', { name: 'Apply assignments', exact: true }).click()
  await page.getByRole('button', { name: 'Save Visuals Settings', exact: true }).click()
  const saved = JSON.parse(await page.locator('#saved').textContent())
  assert.equal('test_prompt' in saved, false)
  assert.equal('prepared_body' in saved, false)
  assert.equal(saved.comfyui_presets.nova.generate.graph.model.inputs.unet_name, 'installed-nova.safetensors')
  assert.equal(requests[0].payload.comfyui_presets.nova.generate.graph.model.inputs.unet_name, saved.comfyui_presets.nova.generate.graph.model.inputs.unet_name)
  assert.deepEqual(errors, [])
  console.log('Preset test browser checks passed: visible example and prepared body reach HTTP, stale results clear, and the exact tested model survives preset → assignments → global Save.')
} finally {
  await browser.close()
}
