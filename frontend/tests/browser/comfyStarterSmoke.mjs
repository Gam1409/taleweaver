import assert from 'node:assert/strict'
import process from 'node:process'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
// Build authentic recipe graphs locally; all server discovery below is fixture data.
const data = JSON.parse(execFileSync(process.env.PYTHON || 'python', ['-c', `
import json
from backend.core.comfyui_task_templates import preset_catalog, task_preset
from backend.core.comfyui_starter_models import LoaderRecipe
print(json.dumps({'catalog':preset_catalog(), 'nova':task_preset('nova_anime_am','npc',LoaderRecipe(layout='checkpoint',encoder_source='external',vae_source='external',checkpoint_name='__choose_checkpoint__.safetensors'))}))
`], { cwd: fileURLToPath(new URL('../../../', import.meta.url)), encoding: 'utf8' }).trim().split('\n').at(-1))
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1400, height: 1150 } })
const errors = [], requests = []
page.on('pageerror', error => errors.push(error.message))
page.setDefaultTimeout(10000)
const files = { ckpt_name: ['models/nova-combined.safetensors'], clip_name: ['encoders/qwen_3_06b_base.safetensors'], vae_name: ['vae/qwen_image_vae.safetensors'] }
let failNext = false
try {
  await page.route('**/api/settings/comfyui/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname.split('/').at(-1)
    requests.push({ path, body: request.postDataJSON() })
    if (path === 'starter-presets') return route.fulfill({ json: request.method() === 'GET' ? data.catalog : data.nova })
    if (failNext) { failNext = false; return route.fulfill({ status: 400, json: { detail: 'ComfyUI is temporarily unavailable. Retry the check.' } }) }
    const workflow = request.postDataJSON().workflow
    const options = Object.entries(workflow.graph).flatMap(([node_id, node]) => Object.keys(node.inputs).filter(input_name => files[input_name]).map(input_name => ({ node_id, input_name, choices: files[input_name] })))
    if (path === 'model-options') return route.fulfill({ json: options })
    if (path === 'check') {
      const missing = options.filter(item => !item.choices.includes(workflow.graph[item.node_id].inputs[item.input_name]))
      return route.fulfill({ json: { compatible: !missing.length, errors: missing.map(item => `${item.node_id}.${item.input_name}: selected value is not available on the server.`), message: 'Static checks only; run a test image to verify execution and image output.' } })
    }
    throw new Error(`Unexpected fixture request: ${path}`)
  })
  await page.goto((process.env.FRONTEND_URL || 'http://127.0.0.1:5206') + '/tests/browser/comfyStarter.html')
  await page.getByText('Create from a task template', { exact: false }).click()
  await page.getByRole('combobox', { name: /^Model family/ }).selectOption('nova_anime_am')
  await page.getByRole('combobox', { name: /^Model file layout/ }).selectOption('checkpoint')
  const check = page.getByRole('button', { name: 'Check VAE / Checkpoint / CLIP', exact: true })
  await check.click()
  await page.getByLabel('Checkpoint', { exact: true }).selectOption(files.ckpt_name[0])
  await page.getByLabel('Text encoder', { exact: true }).selectOption(files.clip_name[0])
  await page.getByLabel('VAE', { exact: true }).selectOption(files.vae_name[0])
  await check.click()
  await page.getByText('Required nodes and selected model files are available.', { exact: true }).waitFor()
  await page.screenshot({ path: '/tmp/comfy-starter-model-check.png', fullPage: true })
  await page.getByRole('button', { name: 'Create task preset', exact: true }).click()
  const created = JSON.parse(await page.locator('#created').textContent())
  assert.equal(created.length, 1)
  for (const graph of [created[0].generate.graph, created[0].reference.graph]) {
    assert.equal(graph.model.inputs.ckpt_name, files.ckpt_name[0])
    assert.equal(graph.clip.inputs.clip_name, files.clip_name[0])
    assert.equal(graph.vae.inputs.vae_name, files.vae_name[0])
  }
  failNext = true
  await check.click()
  await page.getByRole('alert').filter({ hasText: 'ComfyUI is temporarily unavailable.' }).waitFor()
  await check.click()
  await page.getByText('Required nodes and selected model files are available.', { exact: true }).waitFor()
  await page.getByLabel('ComfyUI URL', { exact: true }).fill('http://comfy-two.test:8188')
  assert.equal(await page.getByText('Required nodes and selected model files are available.', { exact: true }).count(), 0)
  assert.equal(await page.getByRole('button', { name: 'Create task preset', exact: true }).isDisabled(), true)
  assert.equal(requests.some(request => request.path === 'prompt' || request.path === 'visual-jobs'), false)
  assert.deepEqual(errors, [])
  console.log('Starter model check browser passed: discovery, file choices, reference sync, retry, URL invalidation, and no generation.')
} finally {
  await browser.close()
}
