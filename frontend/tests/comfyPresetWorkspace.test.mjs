import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { effectScope, reactive, nextTick } from 'vue'
import ts from 'typescript'

const compile = source =>
  ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
  }).outputText
const uri = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`
const libraryUri = uri(compile(readFileSync(new URL('../src/services/comfyLibrary.ts', import.meta.url), 'utf8')))
const draftModule = uri(
  compile(readFileSync(new URL('../src/services/comfyPresetDraft.ts', import.meta.url), 'utf8')).replaceAll("'./comfyLibrary'", JSON.stringify(libraryUri))
)
const tick = async () => {
  await nextTick()
  await new Promise(resolve => setImmediate(resolve))
}
const rules = id => ({
  template_id: id,
  format: 'description',
  language: 'English',
  max_words: 100,
  adapt_with_llm: true,
  prefix: '',
  suffix: '',
  negative_prompt: '',
  instructions: ''
})
const preset = name => ({
  name,
  auto_prompt_template: true,
  prompt_rules: null,
  reference: null,
  generate: {
    name,
    graph: {},
    bindings: { prompt: { node_id: '1', input_name: 'text' } },
    output_node: '2'
  }
})
let counter = 0
async function fixture(t, request) {
  const key = `__comfyWorkspace${counter++}`
  globalThis[key] = {
    request,
    templates: [
      { id: 'a', rules: rules('a') },
      { id: 'b', rules: rules('b') }
    ]
  }
  const service = uri(
    `export const comfyRequest = (...args) => globalThis['${key}'].request(...args); export const loadPromptTemplates = async () => globalThis['${key}'].templates;`
  )
  let source = compile(
    readFileSync(new URL('../src/composables/useComfyPresetWorkspace.ts', import.meta.url), 'utf8')
  )
  source = source
    .replaceAll("'vue'", JSON.stringify(import.meta.resolve('vue')))
    .replaceAll("'@/services/comfyPresetService'", JSON.stringify(service))
    .replaceAll("'@/services/comfyPresetDraft'", JSON.stringify(draftModule))
  const module = await import(uri(source))
  const props = reactive({
    open: true,
    profile: 'simple',
    modelValue: {
      comfyui_url: 'http://localhost:8188',
      comfyui_timeout: 600,
      comfyui_profiles: {},
      comfyui_presets: { a: preset('A'), b: preset('B') },
      comfyui_assignments: { simple: 'a' }
    }
  })
  const scope = effectScope()
  const editor = scope.run(() => module.useComfyPresetWorkspace(props))
  t.after(() => {
    scope.stop()
    delete globalThis[key]
  })
  await tick()
  return { props, editor }
}

test('late detection completes its own draft without overwriting the selected preset', async t => {
  const pending = []
  const { editor } = await fixture(t, () => new Promise(resolve => pending.push(resolve)))
  editor.workspace.value.selectedId = 'b'
  await tick()
  assert.equal(pending.length, 2)
  pending[1]({ template_id: 'b', models: ['b'], message: 'B detected' })
  await tick()
  pending[0]({ template_id: 'a', models: ['a'], message: 'A detected' })
  await tick()
  assert.equal(editor.draft.value.name, 'B')
  assert.equal(editor.detection.value.message, 'B detected')
  assert.equal(editor.workspace.value.presets.a.prompt_rules.template_id, 'a')
  assert.equal(editor.workspace.value.presets.b.prompt_rules.template_id, 'b')
  assert.equal(editor.ready.value, true)
})

test('closing and reopening fences responses from the discarded workspace', async t => {
  const pending = []
  const { props, editor } = await fixture(t, () => new Promise(resolve => pending.push(resolve)))
  props.open = false
  await tick()
  props.open = true
  await tick()
  pending[0]({ template_id: 'a', models: ['a'], message: 'Old detection' })
  await tick()
  assert.equal(editor.draft.value.prompt_rules, null)
  pending[1]({ template_id: 'b', models: ['b'], message: 'New detection' })
  await tick()
  assert.equal(editor.draft.value.prompt_rules.template_id, 'b')
  assert.equal(editor.detection.value.message, 'New detection')
})

test('a failed old preview cannot show an error in a reopened editor', async t => {
  let rejectPreview
  const { props, editor } = await fixture(t, path =>
    path === 'preview-prompt'
      ? new Promise((_, reject) => {
          rejectPreview = reject
        })
      : Promise.resolve({ template_id: 'a', models: ['a'], message: 'Detected' })
  )
  const pending = editor.previewPrompt()
  await tick()
  props.open = false
  await tick()
  props.open = true
  await tick()
  rejectPreview(new Error('Late preview failure'))
  await pending
  assert.equal(editor.error.value, '')
  assert.equal(editor.previewing.value, false)
  assert.equal(editor.preview.value, null)
})

test('changing reference policy invalidates detection from the previous model pairing', async t => {
  const pending = []
  const { editor } = await fixture(t, () => new Promise(resolve => pending.push(resolve)))
  editor.draft.value.reference_prompt_rules = rules('b')
  await tick()
  pending[0]({ template_id:'b', models:['old pair'], message:'Old pair' })
  await tick()
  assert.equal(editor.draft.value.prompt_rules, null)
  pending[1]({ template_id:'a', models:['base'], message:'Base only' })
  await tick()
  assert.equal(editor.draft.value.prompt_rules.template_id, 'a')
  assert.equal(editor.draft.value.reference_prompt_rules.template_id, 'b')
})
