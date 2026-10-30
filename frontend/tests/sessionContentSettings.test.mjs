import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import { effectScope, nextTick, ref } from 'vue'
import ts from 'typescript'

const source = readFileSync(new URL('../src/composables/useSessionContentSettings.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText.replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
  .replace(/import .* from '@\/services\/http';/, 'const apiFetch = (...args) => globalThis.fetch(...args);')
const { useSessionContentSettings } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
const tick = () => new Promise(resolve => setImmediate(resolve))
const preferences = { enabled: false, level: 'soft' }

function fixture(t, fetch) {
  t.mock.method(globalThis, 'fetch', fetch)
  const scope = effectScope()
  const session = ref('one')
  t.after(() => scope.stop())
  return { session, scope, ...scope.run(() => useSessionContentSettings(() => session.value)) }
}

test('loading and local selection do not save; save sends expected values and reloads persistence', async t => {
  const calls = []
  let server = preferences
  const f = fixture(t, async (url, options) => {
    calls.push({ url, options })
    if (options.method === 'PATCH') {
      const body = JSON.parse(options.body)
      assert.deepEqual(body.expected, preferences)
      server = body.settings
    }
    return new Response(JSON.stringify(server))
  })
  await tick()
  assert.equal(f.loaded.value, true)
  f.draft.value.enabled = true
  f.draft.value.level = 'medium'
  assert.equal(calls.length, 1)
  assert.equal(f.dirty.value, true)
  assert.equal(await f.save(), true)
  assert.equal(f.dirty.value, false)
  assert.equal(calls[1].url, '/adventures/one/content-settings')
  await f.load()
  assert.deepEqual(f.draft.value, { enabled: true, level: 'medium' })
  const count = calls.length
  await f.save()
  assert.equal(calls.length, count)
})

test('conflict keeps the edit visible and blocks parent save until resolved', async t => {
  const f = fixture(t, async (_url, options) => options.method === 'GET'
    ? new Response(JSON.stringify(preferences))
    : new Response(JSON.stringify({ detail: 'Settings changed elsewhere.' }), { status: 409 }))
  await tick()
  f.draft.value.enabled = true
  assert.equal(await f.save(), false)
  assert.equal(f.draft.value.enabled, true)
  assert.equal(f.dirty.value, true)
  assert.equal(f.error.value, 'Settings changed elsewhere.')
  await f.load()
  assert.equal(f.error.value, '')
  assert.equal(f.draft.value.enabled, false)
})

test('unavailable settings cannot overwrite server preferences or block unrelated settings', async t => {
  const f = fixture(t, async () => new Response(JSON.stringify({ detail: 'Snapshot unavailable.' }), { status: 409 }))
  await tick()
  assert.equal(f.loaded.value, false)
  assert.equal(await f.save(), true)
  assert.equal(globalThis.fetch.mock.callCount(), 1)
  assert.equal(f.error.value, 'Snapshot unavailable.')
})

test('changing sessions aborts loading and ignores late data from the old session', async t => {
  let finish
  let oldSignal
  const f = fixture(t, async (url, options) => {
    if (url.includes('/one/')) {
      oldSignal = options.signal
      return new Promise(resolve => { finish = resolve })
    }
    return new Response(JSON.stringify({ enabled: true, level: 'medium' }))
  })
  f.session.value = 'two'
  await nextTick()
  await tick()
  assert.equal(oldSignal.aborted, true)
  finish(new Response(JSON.stringify(preferences)))
  await tick()
  assert.deepEqual(f.draft.value, { enabled: true, level: 'medium' })
})

test('double save is ignored while the first request is running', async t => {
  let finish
  const f = fixture(t, async (_url, options) => options.method === 'GET'
    ? new Response(JSON.stringify(preferences))
    : new Promise(resolve => { finish = resolve }))
  await tick()
  f.draft.value.enabled = true
  const saving = f.save()
  assert.equal(await f.save(), false)
  assert.equal(globalThis.fetch.mock.callCount(), 2)
  finish(new Response(JSON.stringify({ enabled: true, level: 'soft' })))
  assert.equal(await saving, true)
})
