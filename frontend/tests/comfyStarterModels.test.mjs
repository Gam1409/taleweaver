import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { effectScope, reactive } from 'vue'
import ts from 'typescript'
import { settle } from './mountSfc.mjs'

const require = createRequire(import.meta.url)
const source = readFileSync(new URL('../src/composables/useComfyStarterModels.ts', import.meta.url), 'utf8')
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
const labels = { ckpt_name: 'Checkpoint', clip_name: 'Text encoder', vae_name: 'VAE' }
const clone = value => JSON.parse(JSON.stringify(value))
const graph = () => ({ model: { class_type: 'CheckpointLoaderSimple', inputs: { ckpt_name: '__choose_checkpoint__.safetensors' } },
  clip: { class_type: 'CLIPLoader', inputs: { clip_name: 'default-clip.safetensors' } },
  vae: { class_type: 'VAELoader', inputs: { vae_name: 'default-vae.safetensors' } } })
const preset = () => ({ name: 'Nova portrait', generate: { name: 'Base', graph: graph() }, reference: { name: 'Reference', graph: graph() } })
const options = [{ node_id: 'model', input_name: 'ckpt_name', choices: ['folder/nova.safetensors'] },
  { node_id: 'clip', input_name: 'clip_name', choices: ['encoders/clip.safetensors'] },
  { node_id: 'vae', input_name: 'vae_name', choices: ['vae/vae.safetensors'] }]

function fixture(t, request) {
  const calls = [], emitted = [], module = { exports: {} }
  new Function('require', 'module', 'exports', code)(name => ({
    '@/services/comfyPresetService': { comfyRequest: (...args) => { calls.push(clone(args)); return request(...args) } },
    '@/services/comfyPresetDraft': { clonePresetData: clone },
    '@/services/comfyWorkflowGraph': { MODEL_FIELD_LABELS: labels },
  })[name] ?? require(name), module, module.exports)
  const props = reactive({ url: 'http://first.test:8188', requiresFilename: true,
    recipe: { family: 'nova_anime_am', purpose: 'npc', layout: 'checkpoint', encoder_source: 'external', vae_source: 'external', checkpoint_name: null } })
  const scope = effectScope()
  const f = scope.run(() => module.exports.useComfyStarterModels(props, value => emitted.push(value)))
  t.after(() => scope.stop())
  return { ...f, props, scope, calls, emitted }
}
const response = async path => path === 'starter-presets' ? { preset: preset() }
  : path === 'model-options' ? options : { compatible: false, errors: ['Select installed files.'], message: 'Static checks only.' }

test('discovery works before a custom checkpoint filename is known and starts no image job', async t => {
  const f = fixture(t, response)
  await f.check()
  assert.equal(f.calls[0][1].checkpoint_name, '__choose_checkpoint__.safetensors')
  assert.deepEqual(f.calls.map(call => call[0]), ['starter-presets', 'model-options', 'check'])
  assert.equal(f.calls[1][1].url, 'http://first.test:8188')
  assert.equal(f.fields.value.length, 3)
  assert.deepEqual(f.fields.value[0].files, ['folder/nova.safetensors'])
  assert.equal(f.emitted.at(-1), null, 'The discovery placeholder cannot become a ready preset.')
  assert.equal(f.report.value.compatible, false)
})

test('chosen filenames reach both graphs and rechecking keeps them without rebuilding the recipe', async t => {
  const f = fixture(t, response)
  await f.check()
  for (const field of options) f.select(field.node_id, field.input_name, field.choices[0])
  assert.equal(f.report.value, null)
  const chosen = f.emitted.at(-1)
  for (const workflow of [chosen.generate, chosen.reference]) {
    for (const field of options) assert.equal(workflow.graph[field.node_id].inputs[field.input_name], field.choices[0])
  }
  await f.check()
  assert.equal(f.calls.filter(call => call[0] === 'starter-presets').length, 1)
  assert.equal(f.calls.at(-1)[1].workflow.graph.vae.inputs.vae_name, 'vae/vae.safetensors')
  chosen.generate.graph.model.inputs.ckpt_name = 'Externally mutated'
  assert.equal(f.preset.value.generate.graph.model.inputs.ckpt_name, 'folder/nova.safetensors')
})

test('a failed recheck keeps selected files, clears the old success, and permits retry', async t => {
  let failing = false
  const f = fixture(t, path => failing && path === 'check' ? Promise.reject(new Error('Server offline.')) : response(path))
  await f.check()
  f.select('model', 'ckpt_name', 'folder/nova.safetensors')
  failing = true
  await f.check()
  assert.equal(f.error.value, 'Server offline.')
  assert.equal(f.report.value, null)
  assert.equal(f.preset.value.generate.graph.model.inputs.ckpt_name, 'folder/nova.safetensors')
  assert.equal(f.busy.value, false)
  failing = false
  await f.check()
  assert.equal(f.error.value, '')
  assert.ok(f.report.value)
})

test('server changes discard the old check without releasing a newer request', async t => {
  const pending = []
  const f = fixture(t, (...args) => new Promise(resolve => pending.push({ args, resolve })))
  const old = f.check()
  pending[0].resolve({ preset: preset() })
  await settle()
  f.props.url = 'http://second.test:8188'
  const current = f.check()
  pending[1].resolve(options)
  pending[2].resolve({ compatible: true, errors: [], message: 'Old server.' })
  await old
  assert.equal(f.busy.value, true)
  assert.equal(f.preset.value, null)
  pending[3].resolve({ preset: preset() })
  await settle()
  pending[4].resolve(options)
  pending[5].resolve({ compatible: true, errors: [], message: 'New server.' })
  await current
  assert.equal(f.report.value.message, 'New server.')
  assert.equal(f.calls.at(-1)[1].url, 'http://second.test:8188')
})

test('changing the recipe invalidates choices and a pending recipe cannot start server checks', async t => {
  let finish
  const f = fixture(t, () => new Promise(resolve => { finish = resolve }))
  const pending = f.check()
  f.props.recipe.family = 'anima'
  finish({ preset: preset() })
  await pending
  assert.equal(f.calls.length, 1)
  assert.equal(f.preset.value, null)
  assert.equal(f.busy.value, false)
  assert.equal(f.emitted.at(-1), null)
})

test('unmount ignores a late check and a blank URL sends no requests', async t => {
  let finish
  const f = fixture(t, () => new Promise(resolve => { finish = resolve }))
  f.props.url = ''
  await f.check()
  assert.equal(f.calls.length, 0)
  f.props.url = 'http://first.test:8188'
  const pending = f.check()
  f.scope.stop()
  finish({ preset: preset() })
  await pending
  assert.equal(f.calls.length, 1)
  assert.equal(f.preset.value, null)
  assert.equal(f.busy.value, false)
})

test('embedded components do not produce invented external file controls', async t => {
  const combined = preset()
  delete combined.generate.graph.clip
  delete combined.generate.graph.vae
  combined.generate.graph.model.inputs.ckpt_name = 'folder/nova.safetensors'
  const f = fixture(t, path => path === 'starter-presets' ? { preset: combined }
    : path === 'model-options' ? options.slice(0, 1) : response(path))
  await f.check()
  assert.deepEqual(f.fields.value.map(field => field.name), ['ckpt_name'])
})
