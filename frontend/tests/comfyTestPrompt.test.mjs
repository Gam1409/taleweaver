import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { effectScope, reactive } from 'vue'
import ts from 'typescript'
import { settle } from './mountSfc.mjs'

const require = createRequire(import.meta.url)
const compile = source => ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
function load(path, dependencies = {}) {
  const module = { exports: {} }
  new Function('require', 'module', 'exports', compile(readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')))(
    name => dependencies[name] ?? require(name), module, module.exports,
  )
  return module.exports
}
const library = load('services/comfyLibrary.ts')
const draftModule = load('services/comfyPresetDraft.ts', { './comfyLibrary': library })

async function fixture(t) {
  const calls = []
  const service = {
    loadPromptTemplates: async () => [],
    comfyRequest: async (path, body) => {
      if (path === 'detect-template') return { template_id: null, models: [], message: '' }
      calls.push({ path, body })
      return { body: 'One red-coated traveler beside a stone bridge.', positive: 'masterpiece, One red-coated traveler beside a stone bridge.', negative: 'text' }
    },
  }
  const module = load('composables/useComfyPresetWorkspace.ts', {
    '@/services/comfyPresetService': service, '@/services/comfyPresetDraft': draftModule,
  })
  const props = reactive({ open: true, profile: 'simple', purpose: 'background', modelValue: {
    comfyui_url: 'https://comfy.example', comfyui_timeout: 600, comfyui_profiles: {},
    comfyui_presets: { nova: {
      name: 'Nova Anima', auto_prompt_template: false, prompt_rules: null, reference: null,
      generate: { name: 'Nova', graph: { text: { class_type: 'Text', inputs: { text: '' } }, save: { class_type: 'SaveImage', inputs: {} } },
        bindings: { prompt: { node_id: 'text', input_name: 'text' } }, output_node: 'save' },
    } }, comfyui_assignments: { background: 'nova' },
  } })
  const scope = effectScope()
  t.after(() => scope.stop())
  const controls = scope.run(() => module.useComfyPresetWorkspace(props))
  await settle()
  return { ...controls, calls, props }
}

test('the preset test sends the visible description and keeps test inputs out of saved settings', async t => {
  const f = await fixture(t)
  f.example.value = 'A traveler by a bridge.'
  const input = f.testOptions()
  assert.equal(input.test_prompt, 'A traveler by a bridge.')
  assert.equal(input.prepared_body, undefined)
  assert.equal(input.image_purpose, 'background')
  assert.equal('test_prompt' in f.result(), false)
  assert.equal('prepared_body' in f.result(), false)
})

test('the generated image reuses the current prepared preview body', async t => {
  const f = await fixture(t)
  f.example.value = 'A traveler by a bridge.'
  await settle()
  await f.previewPrompt()
  const input = f.testOptions()
  assert.equal(f.calls[0].body.description, 'A traveler by a bridge.')
  assert.equal(input.prepared_body, 'One red-coated traveler beside a stone bridge.')
  assert.equal(input.test_prompt, 'A traveler by a bridge.')
})

test('changing the example immediately invalidates the old preview even before watchers flush', async t => {
  const f = await fixture(t)
  await f.previewPrompt()
  f.example.value = 'A black cat sleeping on a red chair.'
  const input = f.testOptions()
  assert.equal(input.test_prompt, 'A black cat sleeping on a red chair.')
  assert.equal(input.prepared_body, undefined)
})

test('changing the preset cannot reuse a preview prepared for its previous workflow', async t => {
  const f = await fixture(t)
  await f.previewPrompt()
  f.draft.value.generate.graph.text.inputs.text = 'Changed graph'
  assert.equal(f.testOptions().prepared_body, undefined)
})

test('the admin handler forwards both test input fields to the HTTP test service', async () => {
  const source = readFileSync(new URL('../src/views/AdminView.vue', import.meta.url), 'utf8')
  const handler = source.slice(source.indexOf('const handleTestVision ='), source.indexOf('const handleTestTTS ='))
  const calls = []
  const run = new Function('testService', compile(`${handler}\nhandleTestVision({ key:'test', model:'', provider:'comfyui', test_prompt:'A cat', prepared_body:'A prepared cat' })`))
  run({ testVision: (...args) => calls.push(args) })
  assert.equal(calls[0].at(-1).test_prompt, 'A cat')
  assert.equal(calls[0].at(-1).prepared_body, 'A prepared cat')
})

test('changing the example or prepared body invalidates the displayed test image', () => {
  const modal = readFileSync(new URL('../src/components/admin/ComfyPresetModal.vue', import.meta.url), 'utf8')
  const signature = modal.slice(modal.indexOf('const signature ='), modal.indexOf('const showTestResult'))
  assert.match(signature, /example.value/)
  assert.match(signature, /preview.value\?\.body/)
  assert.match(modal, /emit\('test', testOptions\(\)\)/)
})
