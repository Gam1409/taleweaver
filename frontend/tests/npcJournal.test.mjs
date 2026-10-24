import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import { effectScope, nextTick, ref } from 'vue'
import ts from 'typescript'

const source = readFileSync(new URL('../src/composables/useNpcJournal.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
}).outputText.replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
  .replace("import { authState } from '@/store/auth';", 'const authState = { token: "test-token" };')
const { useNpcJournal } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
const reply = data => new Response(JSON.stringify(data))
const tick = async () => { await nextTick(); await new Promise(resolve => setImmediate(resolve)) }

function fixture(t, id = undefined) {
  const session = ref('русская-сессия'), npc = ref(id), scope = effectScope()
  const controller = scope.run(() => useNpcJournal(session, npc))
  t.after(() => scope.stop())
  return { session, npc, scope, ...controller }
}

test('directory uses the saved session ID and reports background work', async t => {
  const calls = []
  t.mock.method(globalThis, 'fetch', async url => {
    calls.push(url)
    return reply({ characters: [{ id: 'mira', name: 'Мира' }], pending: 2, failed: 1 })
  })
  const f = fixture(t)
  await tick()
  assert.equal(calls[0], `/api/adventures/${encodeURIComponent('русская-сессия')}/npcs`)
  assert.equal(f.characters.value[0].name, 'Мира')
  assert.equal(f.pending.value, 2)
  assert.equal(f.failed.value, 1)
})

test('history pages append and do not repeat the first page', async t => {
  const urls = []
  t.mock.method(globalThis, 'fetch', async url => {
    urls.push(url)
    return reply({ id: 'mira', name: 'Мира', entries: [{ id: String(urls.length), text: 'Факт' }], has_more: urls.length < 2 })
  })
  const f = fixture(t, 'mira')
  await tick()
  await f.load(true)
  assert.ok(urls[1].endsWith('?offset=1'))
  assert.equal(f.details.value.entries.length, 2)
  assert.equal(f.details.value.has_more, false)
})

test('changing session ignores an old response and aborts its request', async t => {
  const pending = []
  t.mock.method(globalThis, 'fetch', (url, options) => new Promise(resolve => pending.push({ resolve, signal: options.signal })))
  const f = fixture(t)
  f.session.value = 'other-session'
  await nextTick()
  assert.equal(pending[0].signal.aborted, true)
  pending[0].resolve(reply({ characters: [{ name: 'Old character' }], pending: 0, failed: 0 }))
  await tick()
  assert.deepEqual(f.characters.value, [])
  pending[1].resolve(reply({ characters: [{ name: 'New character' }], pending: 0, failed: 0 }))
  await tick()
  assert.equal(f.characters.value[0].name, 'New character')
})

test('HTTP failure is visible and can be retried', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => new Response('error', { status: 500 }))
  const f = fixture(t, 'mira')
  await tick()
  assert.match(f.error.value, /Could not load/)
  fetch.mock.mockImplementation(async () => reply({ id: 'mira', name: 'Мира', entries: [] }))
  await f.load()
  assert.equal(f.error.value, '')
  assert.equal(f.details.value.name, 'Мира')
})

test('retry learning is one POST followed by an updated directory', async t => {
  const methods = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    methods.push(options.method)
    return reply({ characters: [], pending: 1, failed: 0 })
  })
  const f = fixture(t)
  await tick()
  await f.retryLearning()
  assert.deepEqual(methods, ['GET', 'POST', 'GET'])
  assert.equal(f.loading.value, false)
})

test('disposing the card cancels its request and ignores late data', async t => {
  let finish, signal
  t.mock.method(globalThis, 'fetch', (url, options) => {
    signal = options.signal
    return new Promise(resolve => { finish = resolve })
  })
  const f = fixture(t, 'mira')
  f.scope.stop()
  assert.equal(signal.aborted, true)
  finish(reply({ name: 'Late response', entries: [] }))
  await tick()
  assert.equal(f.details.value, null)
})
