import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { effectScope, ref } from 'vue'
import ts from 'typescript'
import { settle } from './mountSfc.mjs'

const require = createRequire(import.meta.url)
const source = readFileSync(new URL('../src/composables/useAdventureImageSettings.ts', import.meta.url), 'utf8')
const code = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
const response = value => ({ ok: true, json: async () => value })
const config = (source = 'saved', name = 'Saved Anima') => ({ source, selection: { background: 'old' }, effective: { preset_name: name } })

function fixture(t) {
  const requests = [], busyEvents = []
  const module = { exports: {} }
  new Function('require', 'module', 'exports', code)(name => name === '@/services/http'
    ? { apiFetch: (...args) => new Promise((resolve, reject) => requests.push({ args, resolve, reject })) }
    : require(name), module, module.exports)
  const context = ref({ adventureId: 'A', targetType: 'scene', advanced: true, reference: false })
  const scope = effectScope()
  const view = scope.run(() => module.exports.useAdventureImageSettings(() => context.value, value => busyEvents.push(value)))
  t.after(() => scope.stop())
  return { ...view, context, scope, requests, busyEvents }
}

test('image metadata uses the same background task and quality as scene generation', async t => {
  const f = fixture(t)
  const url = new URL(f.requests[0].args[0], 'http://local')
  assert.equal(url.pathname, '/adventures/A/visual-presets')
  assert.deepEqual(Object.fromEntries(url.searchParams), { purpose: 'background', advanced: 'true', reference: 'false' })
  assert.equal(f.busy.value, true)
  f.requests[0].resolve(response(config()))
  await settle()
  assert.equal(f.data.value.effective.preset_name, 'Saved Anima')
  assert.equal(f.busy.value, false)
})

test('switching to global settings preserves saved choices and refreshes the actual workflow', async t => {
  const f = fixture(t)
  f.requests[0].resolve(response(config()))
  await settle()
  f.source.value = 'current'
  const saved = f.save()
  assert.deepEqual(JSON.parse(f.requests[1].args[1].body), { source: 'current' })
  assert.equal(f.requests[1].args[1].method, 'PUT')
  f.requests[1].resolve(response({ source: 'current', selection: { background: 'old' } }))
  await settle()
  assert.equal(f.busy.value, true)
  f.requests[2].resolve(response(config('current', 'Nova Anima')))
  await saved
  assert.equal(f.data.value.effective.preset_name, 'Nova Anima')
  assert.equal(f.saved.value, true)
  assert.equal(f.requests.length, 3)
})

test('a failed source change keeps the existing source visible and can be retried', async t => {
  const f = fixture(t)
  f.requests[0].resolve(response(config()))
  await settle()
  f.source.value = 'current'
  const pending = f.save()
  f.requests[1].resolve({ ok: false, json: async () => ({ detail: 'The selected preset is unavailable.' }) })
  await pending
  assert.match(f.error.value, /unavailable/)
  assert.equal(f.data.value.source, 'saved')
  assert.equal(f.saved.value, false)
  assert.equal(f.busy.value, false)
  const retry = f.save()
  f.requests[2].resolve(response({}))
  await settle()
  f.requests[3].resolve(response(config('current', 'Nova Anima')))
  await retry
  assert.equal(f.error.value, '')
  assert.equal(f.data.value.source, 'current')
})

test('an older adventure response cannot overwrite the current target or clear its busy state', async t => {
  const f = fixture(t)
  const oldSignal = f.requests[0].args[1].signal
  f.context.value = { adventureId: 'B', targetType: 'npc', advanced: false, reference: true }
  assert.equal(oldSignal.aborted, true)
  assert.match(f.requests[1].args[0], /adventures\/B\/visual-presets\?purpose=npc&advanced=false&reference=true/)
  f.requests[0].resolve(response(config('saved', 'Wrong adventure')))
  await settle()
  assert.equal(f.data.value, null)
  assert.equal(f.busy.value, true)
  f.requests[1].resolve(response(config('current', 'Correct adventure')))
  await settle()
  assert.equal(f.data.value.effective.preset_name, 'Correct adventure')
})

test('closing settings aborts metadata waiting and ignores late errors', async t => {
  const f = fixture(t)
  const signal = f.requests[0].args[1].signal
  f.scope.stop()
  assert.equal(signal.aborted, true)
  assert.equal(f.busyEvents.at(-1), false)
  f.requests[0].reject(new Error('Late provider error'))
  await settle()
  assert.equal(f.error.value, '')
})

test('the manual image dialog receives the adventure and blocks generation during source changes', () => {
  const editor = readFileSync(new URL('../src/views/AdventureEditorView.vue', import.meta.url), 'utf8')
  const modal = readFileSync(new URL('../src/components/editor/ManualVisionModal.vue', import.meta.url), 'utf8')
  assert.match(editor.match(/<ManualVisionModal[\s\S]*?\/>/)[0], /:adventure-id="adventureId"/)
  assert.match(modal, /<AdventureImageSettings[^]*?@busy="settingsBusy = \$event"/)
  assert.match(modal, /@click="emit\('regenerate'\)" :disabled="isRegenerating \|\| isSuggestingPrompt \|\| settingsBusy"/)
})
