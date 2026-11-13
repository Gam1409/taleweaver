import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import { effectScope, ref } from 'vue'
import ts from 'typescript'

const source = readFileSync(new URL('../src/composables/useNarratorSettings.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText.replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
  .replace(/import .* from '@\/services\/http';/, 'const apiFetch = (...args) => globalThis.fetch(...args);')
const { useNarratorSettings } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
const tick = () => new Promise(resolve => setImmediate(resolve))
const voice = { id: 'noir', name: 'Noir', description: 'Dry', instruction: 'Use dry prose.', sample: 'Rain again.' }
const empty = { voice: null, verbosity: 'default' }
const response = (settings = empty) => new Response(JSON.stringify({ settings, voices: [voice] }))

function setup(t, fetch) {
  t.mock.method(globalThis, 'fetch', fetch)
  const scope = effectScope()
  const endpoint = ref('/adventures/one/narrator-settings')
  t.after(() => scope.stop())
  return { scope, endpoint, ...scope.run(() => useNarratorSettings(() => endpoint.value)) }
}

test('selection remains a draft and save sends an independent copy of the chosen voice', async t => {
  const calls = []
  const f = setup(t, async (url, options) => {
    calls.push({ url, options })
    return response(options.method === 'PUT' ? JSON.parse(options.body) : empty)
  })
  await tick()
  f.selectVoice('noir')
  f.settings.value.verbosity = 'rich'
  f.settings.value.flow = 'balanced'
  assert.equal(calls.length, 1)
  assert.equal(f.dirty.value, true)
  f.settings.value.voice.name = 'Personal noir'
  assert.equal(f.voices.value[0].name, 'Noir')
  assert.equal(await f.save(), true)
  assert.equal(f.dirty.value, false)
  assert.equal(JSON.parse(calls[1].options.body).verbosity, 'rich')
  assert.equal(JSON.parse(calls[1].options.body).flow, 'balanced')
  assert.equal(JSON.parse(calls[1].options.body).voice.name, 'Personal noir')
  assert.equal(calls[1].url, '/adventures/one/narrator-settings')
})

test('conflict keeps the draft and prevents parent save from reporting success', async t => {
  const f = setup(t, async (_url, options) => options.method === 'GET' ? response() : new Response(JSON.stringify({ detail: 'Settings changed.' }), { status: 409 }))
  await tick()
  f.settings.value.verbosity = 'epic'
  f.settings.value.flow = 'off'
  assert.equal(await f.save(), false)
  assert.equal(f.settings.value.verbosity, 'epic')
  assert.equal(f.settings.value.flow, 'off')
  assert.equal(f.dirty.value, true)
  assert.match(f.error.value, /changed/)
})

test('old session response cannot overwrite a newly opened session', async t => {
  let resolveOld
  const f = setup(t, async url => url.includes('/one/') ? new Promise(resolve => { resolveOld = resolve }) : response({ voice: null, verbosity: 'terse', flow: 'off' }))
  f.endpoint.value = '/adventures/two/narrator-settings'
  await tick()
  resolveOld(response({ voice, verbosity: 'epic', flow: 'balanced' }))
  await tick()
  assert.equal(f.settings.value.verbosity, 'terse')
  assert.equal(f.settings.value.voice, null)
  assert.equal(f.settings.value.flow, 'off')
})

test('failed loading and untouched settings never overwrite server defaults', async t => {
  let count = 0
  const f = setup(t, async () => { count += 1; throw new Error('Offline') })
  await tick()
  assert.equal(f.loaded.value, false)
  assert.equal(await f.save(), true)
  assert.equal(count, 1)
  assert.match(f.error.value, /Offline/)
})

test('custom and neutral choices are explicit, and disposing cancels the pending request', async t => {
  let signal
  const f = setup(t, async (_url, options) => { signal = options.signal; return response() })
  await tick()
  f.selectVoice('custom')
  assert.equal(f.settings.value.voice.id, 'custom')
  f.selectVoice('')
  assert.equal(f.settings.value.voice, null)
  f.scope.stop()
  assert.equal(signal.aborted, true)
})

for (const flow of [undefined, null, 'unknown']) {
  test(`legacy or unsupported flow ${String(flow)} defaults gently without creating an unsaved change`, async t => {
    let count = 0
    const f = setup(t, async () => { count += 1; return response({ voice, verbosity: 'rich', ...(flow === undefined ? {} : { flow }) }) })
    await tick()
    assert.equal(f.settings.value.flow, 'gentle')
    assert.deepEqual(f.settings.value.voice, voice)
    assert.equal(f.settings.value.verbosity, 'rich')
    assert.equal(f.dirty.value, false)
    assert.equal(await f.save(), true)
    assert.equal(count, 1)
  })
}

test('a late session save cannot overwrite newly opened adventure defaults', async t => {
  let finishSave, savedSignal
  const f = setup(t, async (url, options) => {
    if (options.method === 'PUT') {
      savedSignal = options.signal
      return new Promise(resolve => { finishSave = resolve })
    }
    return response(url.endsWith('/narrator-defaults') ? { voice: null, verbosity: 'terse', flow: 'balanced' } : empty)
  })
  await tick()
  f.settings.value.flow = 'off'
  const saving = f.save()
  f.endpoint.value = '/adventures/template/narrator-defaults'
  await tick()
  assert.equal(savedSignal.aborted, true)
  finishSave(response({ voice, verbosity: 'epic', flow: 'off' }))
  assert.equal(await saving, false)
  assert.deepEqual(f.settings.value, { voice: null, verbosity: 'terse', flow: 'balanced' })
  assert.equal(f.dirty.value, false)
  assert.equal(f.error.value, '')
})

test('disposing before a response arrives cannot load narrator settings afterwards', async t => {
  let finish, signal
  const f = setup(t, async (_url, options) => { signal = options.signal; return new Promise(resolve => { finish = resolve }) })
  f.scope.stop()
  assert.equal(signal.aborted, true)
  finish(response({ voice, verbosity: 'epic', flow: 'balanced' }))
  await tick()
  assert.equal(f.loaded.value, false)
  assert.equal(f.settings.value.voice, null)
  assert.equal(f.settings.value.flow, 'gentle')
})
