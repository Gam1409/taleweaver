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

function fixture(t, id = undefined, showState = undefined, history = undefined) {
  const session = ref('русская-сессия'), npc = ref(id), scope = effectScope()
  const controller = scope.run(() => useNpcJournal(session, npc, showState, history))
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


test('disabling indicators clears estimates and keeps history across a late response', async t => {
  const shown = ref(true)
  const card = { id: 'mira', name: 'Mira', summary: [{ id: '1', text: 'We met at the gate' }], state_visible: true, insights: { available: true, emotion: 'calm', relationship: null } }
  let finish
  const fetch = t.mock.method(globalThis, 'fetch', async () => reply(card))
  const f = fixture(t, 'mira', shown)
  await tick()
  assert.equal(f.details.value.insights.emotion, 'calm')
  fetch.mock.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const request = f.load()
  shown.value = false
  await nextTick()
  assert.equal(f.details.value.insights, null)
  assert.equal(f.details.value.summary[0].text, 'We met at the gate')
  finish(reply(card))
  await request
  assert.equal(f.details.value.insights, null)
  assert.equal(f.details.value.state_visible, false)
})

test('enabling indicators refetches and still respects server visibility', async t => {
  const shown = ref(false)
  let calls = 0
  t.mock.method(globalThis, 'fetch', async () => {
    calls++
    return reply({ id: 'mira', state_visible: false, insights: { available: true, emotion: 'secret' } })
  })
  const f = fixture(t, 'mira', shown)
  await tick()
  shown.value = true
  await tick()
  assert.equal(calls, 2)
  assert.equal(f.details.value.insights, null)
})


test('history tabs paginate independently, preserve profile while loading and ignore late old-tab data', async t => {
  const history = ref('general'), requests = []
  t.mock.method(globalThis, 'fetch', (url, options) => new Promise(resolve => requests.push({ url, signal: options.signal, resolve })))
  const f = fixture(t, 'mira', undefined, history)
  requests[0].resolve(reply({ id: 'mira', name: 'Mira', description: 'Current profile', history_kind: 'general', entries: [{ id: 'g1' }], has_more: true }))
  await tick()
  const more = f.load(true)
  assert.match(requests[1].url, /offset=1&history=general$/)
  history.value = 'shared'
  await nextTick()
  assert.equal(f.details.value.description, 'Current profile')
  assert.deepEqual(f.details.value.entries, [])
  assert.equal(requests[1].signal.aborted, true)
  assert.match(requests[2].url, /offset=0&history=shared$/)
  requests[2].resolve(reply({ id: 'mira', name: 'Mira', history_kind: 'shared', entries: [{ id: 's1' }], has_more: true }))
  await tick()
  requests[1].resolve(reply({ id: 'mira', history_kind: 'general', entries: [{ id: 'g2' }] }))
  await more
  assert.deepEqual(f.details.value.entries.map(entry => entry.id), ['s1'])
  const sharedMore = f.load(true)
  assert.match(requests[3].url, /offset=1&history=shared$/)
  requests[3].resolve(reply({ id: 'mira', history_kind: 'shared', entries: [{ id: 's2' }], has_more: false }))
  await sharedMore
  assert.deepEqual(f.details.value.entries.map(entry => entry.id), ['s1', 's2'])
  history.value = 'general'
  await nextTick()
  assert.match(requests[4].url, /offset=0&history=general$/)
  requests[4].resolve(reply({ id: 'mira', history_kind: 'general', entries: [{ id: 'g1' }] }))
  await tick()
  assert.deepEqual(f.details.value.entries.map(entry => entry.id), ['g1'])
})
