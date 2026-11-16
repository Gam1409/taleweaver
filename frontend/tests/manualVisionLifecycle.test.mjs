import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { effectScope, nextTick, ref } from 'vue'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const source = readFileSync(new URL('../src/composables/useManualVision.ts', import.meta.url), 'utf8')
const code = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText

function fixture(t) {
  const requests = [], notices = []
  let refreshes = 0
  const service = Object.fromEntries(['regenerateVisual', 'suggestPrompt'].map(method => [method,
    (...args) => new Promise((resolve, reject) => requests.push({ method, args, resolve, reject })),
  ]))
  const module = { exports: {} }
  new Function('require', 'module', 'exports', code)(name => name === '@/services/visualService'
    ? { visualService: service } : require(name), module, module.exports)
  const adventureId = ref('adventure'), target = ref({ kind: 'npc', id: 'A', label: 'Alice' })
  const open = ref(true), prompt = ref('A manual prompt.'), controllers = ref(new Map())
  const options = { adventureId: () => adventureId.value, target, open, prompt,
    advanced: ref(false), reference: ref(false), controllers,
    refresh: async () => { refreshes++ }, notify: (...args) => notices.push(args) }
  const scope = effectScope()
  const controls = scope.run(() => module.exports.useManualVision(options))
  t.after(() => scope.stop())
  return { ...controls, adventureId, target, open, prompt, requests, notices, scope, controllers,
    refreshes: () => refreshes }
}

test('a late suggestion cannot overwrite another target or unlock its pending request', async t => {
  const f = fixture(t)
  const old = f.suggest()
  f.cancel()
  f.target.value = { kind: 'npc', id: 'B', label: 'Beatrice' }
  f.open.value = true
  f.prompt.value = 'My Beatrice prompt.'
  const current = f.suggest()
  f.requests[0].resolve('Old Alice prompt.')
  await old
  assert.equal(f.prompt.value, 'My Beatrice prompt.')
  assert.equal(f.isSuggestingPrompt.value, true)
  f.requests[1].resolve('New Beatrice prompt.')
  await current
  assert.equal(f.prompt.value, 'New Beatrice prompt.')
  assert.equal(f.isSuggestingPrompt.value, false)
})

test('a canceled image completion cannot close a newly opened dialog or clear its busy state', async t => {
  const f = fixture(t)
  const old = f.regenerate()
  f.cancel()
  f.target.value = { kind: 'object', id: 'COAT', label: 'Coat' }
  f.open.value = true
  const current = f.regenerate()
  f.requests[0].resolve()
  await old
  assert.equal(f.open.value, true)
  assert.equal(f.isRegenerating.value, true)
  assert.equal(f.refreshes(), 0)
  f.requests[1].resolve()
  await current
  assert.equal(f.open.value, false)
  assert.equal(f.refreshes(), 1)
  assert.equal(f.notices.some(([message]) => message.includes('Alice')), false)
})

test('prompt suggestion and image generation cannot run concurrently in either direction', async t => {
  const f = fixture(t)
  const suggestion = f.suggest()
  const blockedGeneration = f.regenerate()
  assert.equal(f.requests.length, 1)
  await blockedGeneration
  f.requests[0].resolve('A prompt.')
  await suggestion
  const generation = f.regenerate()
  const blockedSuggestion = f.suggest()
  assert.equal(f.requests.length, 2)
  await blockedSuggestion
  f.requests[1].resolve()
  await generation
})

test('changing adventures aborts requests and ignores late failures', async t => {
  const f = fixture(t)
  const pending = f.suggest()
  f.adventureId.value = 'different-adventure'
  await nextTick()
  assert.equal(f.isSuggestingPrompt.value, false)
  assert.equal(f.requests[0].args.at(-1).aborted, true)
  f.requests[0].reject(new Error('Late provider failure'))
  await pending
  assert.equal(f.error.value, '')
  assert.deepEqual(f.notices, [])
})

test('empty prompt suggestions leave the manual draft intact and show an actionable error', async t => {
  const f = fixture(t)
  const pending = f.suggest()
  f.requests[0].resolve('   ')
  await pending
  assert.equal(f.prompt.value, 'A manual prompt.')
  assert.match(f.error.value, /no usable prompt.*Suggest Prompt/i)
  assert.equal(f.open.value, true)
  assert.equal(f.isSuggestingPrompt.value, false)
})

test('image errors stay in the open dialog and can be retried with the same prompt', async t => {
  const f = fixture(t)
  const pending = f.regenerate()
  f.requests[0].reject(new Error('Image provider unavailable.'))
  await pending
  assert.equal(f.error.value, 'Image provider unavailable.')
  assert.equal(f.open.value, true)
  assert.equal(f.prompt.value, 'A manual prompt.')
  const retry = f.regenerate()
  f.requests[1].resolve()
  await retry
  assert.equal(f.error.value, '')
  assert.equal(f.open.value, false)
})

test('unmount aborts a pending lookup and discards its late response', async t => {
  const f = fixture(t)
  const pending = f.suggest()
  f.scope.stop()
  assert.equal(f.requests[0].args.at(-1).aborted, true)
  f.requests[0].resolve('Late suggested prompt.')
  await pending
  assert.equal(f.prompt.value, 'A manual prompt.')
  assert.deepEqual(f.notices, [])
})

test('manual images supersede quick generation through the existing shared cancel registry', async t => {
  const f = fixture(t)
  const quick = new AbortController()
  f.controllers.value.set('npc_A', quick)
  const pending = f.regenerate()
  assert.equal(quick.signal.aborted, true)
  const manual = f.controllers.value.get('npc_A')
  assert.equal(manual.signal, f.requests[0].args[5])
  f.requests[0].resolve()
  await pending
  assert.equal(f.controllers.value.size, 0)
})

test('an externally superseded manual image cannot publish or delete the newer cancel handle', async t => {
  const f = fixture(t)
  const pending = f.regenerate()
  f.controllers.value.get('npc_A').abort()
  const newer = new AbortController()
  f.controllers.value.set('npc_A', newer)
  f.requests[0].resolve()
  await pending
  assert.equal(f.open.value, true)
  assert.equal(f.refreshes(), 0)
  assert.deepEqual(f.notices, [])
  assert.equal(f.controllers.value.get('npc_A'), newer)
  assert.equal(f.isRegenerating.value, false)
})
