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
  assert.equal(calls.length, 1)
  assert.equal(f.dirty.value, true)
  f.settings.value.voice.name = 'Personal noir'
  assert.equal(f.voices.value[0].name, 'Noir')
  assert.equal(await f.save(), true)
  assert.equal(f.dirty.value, false)
  assert.equal(JSON.parse(calls[1].options.body).verbosity, 'rich')
  assert.equal(calls[1].url, '/adventures/one/narrator-settings')
})

test('conflict keeps the draft and prevents parent save from reporting success', async t => {
  const f = setup(t, async (_url, options) => options.method === 'GET' ? response() : new Response(JSON.stringify({ detail: 'Settings changed.' }), { status: 409 }))
  await tick()
  f.settings.value.verbosity = 'epic'
  assert.equal(await f.save(), false)
  assert.equal(f.settings.value.verbosity, 'epic')
  assert.equal(f.dirty.value, true)
  assert.match(f.error.value, /changed/)
})

test('old session response cannot overwrite a newly opened session', async t => {
  let resolveOld
  const f = setup(t, async url => url.includes('/one/') ? new Promise(resolve => { resolveOld = resolve }) : response({ voice: null, verbosity: 'terse' }))
  f.endpoint.value = '/adventures/two/narrator-settings'
  await tick()
  resolveOld(response({ voice, verbosity: 'epic' }))
  await tick()
  assert.equal(f.settings.value.verbosity, 'terse')
  assert.equal(f.settings.value.voice, null)
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
