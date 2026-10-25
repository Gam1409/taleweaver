import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { effectScope, nextTick, ref } from 'vue'
import ts from 'typescript'

const source = readFileSync(new URL('../src/composables/useNpcCardSettings.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText.replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
  .replace("import { authState } from '@/store/auth';", 'const authState = { token: "test-token" };')
const { useNpcCardSettings } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
const reply = data => new Response(JSON.stringify(data))
const tick = async () => { await nextTick(); await new Promise(resolve => setImmediate(resolve)) }
function fixture(t, id = 'session') {
  const session = ref(id), scope = effectScope()
  const controller = scope.run(() => useNpcCardSettings(session))
  t.after(() => scope.stop())
  return { session, scope, ...controller }
}

test('settings default hidden, load persisted value and share immediate disable across cards', async t => {
  const calls = []
  let finish
  t.mock.method(globalThis, 'fetch', (url, options) => {
    calls.push({ url, ...options })
    return options.method === 'GET' ? Promise.resolve(reply({ show_state: true })) : new Promise(resolve => { finish = resolve })
  })
  const first = fixture(t, 'session / 1')
  const second = fixture(t, 'session / 1')
  assert.equal(first.showState.value, false)
  await tick()
  assert.equal(calls.length, 1)
  assert.equal(second.showState.value, true)
  const save = first.setShowState(false)
  assert.equal(second.showState.value, false)
  assert.equal(calls[1].url, '/api/adventures/session%20%2F%201/npc-card-settings')
  assert.equal(calls[1].body, '{"show_state":false}')
  finish(reply({ show_state: false }))
  await save
  assert.equal(first.loaded.value, true)
})

test('late GET cannot reverse a subsequent disable even when fetch ignores abort', async t => {
  const requests = []
  t.mock.method(globalThis, 'fetch', (_, options) => new Promise(resolve => requests.push({ resolve, ...options })))
  const settings = fixture(t)
  const save = settings.setShowState(false)
  assert.equal(requests[0].signal.aborted, true)
  requests[1].resolve(reply({ show_state: false }))
  await save
  requests[0].resolve(reply({ show_state: true }))
  await tick()
  assert.equal(settings.showState.value, false)
})

test('enable awaits acknowledgement; failed save leaves indicators hidden and offers retry', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => reply({ show_state: false }))
  const settings = fixture(t)
  await tick()
  let finish
  fetch.mock.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const save = settings.setShowState(true)
  assert.equal(settings.showState.value, false)
  finish(new Response('', { status: 500 }))
  await save
  assert.equal(settings.showState.value, false)
  assert.match(settings.error.value, /Could not save/)
  fetch.mock.mockImplementation(async () => reply({ show_state: true }))
  await settings.refresh()
  assert.equal(settings.showState.value, true)
  assert.equal(settings.error.value, '')
})

test('session switch releases old request and never carries its visibility over', async t => {
  const requests = []
  t.mock.method(globalThis, 'fetch', (_, options) => new Promise(resolve => requests.push({ resolve, ...options })))
  const settings = fixture(t, 'old')
  settings.session.value = 'new'
  await nextTick()
  assert.equal(requests[0].signal.aborted, true)
  requests[0].resolve(reply({ show_state: true }))
  await tick()
  assert.equal(settings.showState.value, false)
  requests[1].resolve(reply({ show_state: false }))
  await tick()
  assert.equal(settings.loaded.value, true)
})
