import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'
import { sessionTransferModule } from './sessionTransferModule.mjs'

const uri = code => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
const compile = path => ts.transpileModule(readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText
const auth = { token: 'test-session-transfer', isAuthenticated: true }
const health = { isBackendReachable: true, lastErrorMessage: '' }
globalThis.__sessionTransferAuth = auth
globalThis.__sessionTransferHealth = health
const http = uri(compile('services/http.ts').replace(/import .* from '@\/store\/auth';/, 'const authState = globalThis.__sessionTransferAuth;'))
const source = compile('composables/useApi.ts')
  .replace(/import .* from '@\/services\/visualJobs';/, 'const runVisualJob = () => { throw new Error("Unexpected visual request") };')
  .replace(/import .* from '@\/store\/auth';/, 'const authState = globalThis.__sessionTransferAuth;')
  .replace(/import .* from '@\/store\/config';/, 'const configState = globalThis.__sessionTransferHealth;')
  .replace("from '@/services/http'", `from '${http}'`)
  .replace("from '@/services/sessionTransfer'", `from '${sessionTransferModule}'`)
const { api } = await import(uri(source))
const { SESSION_TRANSFER_TIMEOUT_MS, withSessionTransferDeadline } = await import(sessionTransferModule)
const tick = () => new Promise(resolve => setImmediate(resolve))
const deferred = () => {
  let resolve
  const promise = new Promise(finish => { resolve = finish })
  return { promise, resolve }
}

function fixture(t) {
  const timers = [], events = []
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'window')
  const clear = timer => { timer.cleared = true }
  Object.defineProperty(globalThis, 'window', { configurable: true, value: {
    setTimeout(callback, delay) { const timer = { callback, delay, cleared: false }; timers.push(timer); return timer },
    clearTimeout: clear,
    dispatchEvent(event) { events.push(event.type); return true },
  } })
  const originalClear = globalThis.clearTimeout
  t.mock.method(globalThis, 'clearTimeout', timer => timers.includes(timer) ? clear(timer) : originalClear(timer))
  Object.assign(health, { isBackendReachable: true, lastErrorMessage: '' })
  t.after(() => { if (previous) Object.defineProperty(globalThis, 'window', previous); else delete globalThis.window })
  return { timers, events }
}

test('ADS download consumes the native Blob without first materializing an ArrayBuffer', async t => {
  const { timers } = fixture(t), blob = new Blob(['zip'], { type: 'application/zip' })
  const response = new Response(blob)
  const arrays = t.mock.method(response, 'arrayBuffer', () => { throw new Error('Archive must not be buffered as an ArrayBuffer') })
  const bodies = t.mock.method(response, 'blob', async () => blob)
  t.mock.method(globalThis, 'fetch', async (path, options) => {
    assert.equal(path, '/api/adventures/sessions/session/export')
    assert.equal(options.headers.get('Authorization'), 'Bearer test-session-transfer')
    assert.equal(options.credentials, 'same-origin')
    return response
  })
  assert.equal(await api.downloadSessionAds('session'), blob)
  assert.equal(arrays.mock.callCount(), 0)
  assert.equal(bodies.mock.callCount(), 1)
  assert.deepEqual(timers.map(timer => timer.delay), [SESSION_TRANSFER_TIMEOUT_MS])
  assert.equal(timers[0].cleared, true)
})

test('ADS total deadline stays active through a stalled native response body', async t => {
  const { timers } = fixture(t), body = deferred(), response = new Response('zip')
  let sent
  t.mock.method(response, 'blob', () => body.promise)
  t.mock.method(response, 'arrayBuffer', () => { throw new Error('Unexpected ArrayBuffer') })
  t.mock.method(globalThis, 'fetch', async (_path, options) => { sent = options; return response })
  const download = api.downloadSessionAds('session')
  await tick()
  assert.equal(timers[0].delay, 3_600_000)
  assert.equal(timers[0].cleared, false)
  timers[0].callback()
  await assert.rejects(download, { name: 'AbortError', message: 'Session transfer timed out.' })
  assert.equal(sent.signal.aborted, true)
  assert.equal(timers[0].cleared, true)
  body.resolve(new Blob(['late']))
})

test('ADS total deadline also covers waiting for response headers', async t => {
  const { timers } = fixture(t), headers = deferred()
  let signal
  t.mock.method(globalThis, 'fetch', (_path, options) => { signal = options.signal; return headers.promise })
  const download = api.downloadSessionAds('session')
  timers[0].callback()
  await assert.rejects(download, { name: 'AbortError', message: 'Session transfer timed out.' })
  assert.equal(signal.aborted, true)
  headers.resolve(new Response('late'))
})

test('caller cancellation reaches native ADS consumption and releases listeners', async t => {
  const { timers } = fixture(t), parent = new AbortController(), body = deferred()
  const add = t.mock.method(parent.signal, 'addEventListener'), remove = t.mock.method(parent.signal, 'removeEventListener')
  const response = new Response('zip')
  let signal
  t.mock.method(response, 'blob', () => body.promise)
  t.mock.method(response, 'arrayBuffer', () => { throw new Error('Unexpected ArrayBuffer') })
  t.mock.method(globalThis, 'fetch', async (_path, options) => { signal = options.signal; return response })
  const download = api.downloadSessionAds('session', parent.signal)
  await tick()
  parent.abort('navigation')
  await assert.rejects(download, { name: 'AbortError', message: 'Session transfer cancelled.' })
  assert.equal(signal.reason, 'navigation')
  assert.equal(remove.mock.callCount(), add.mock.callCount())
  assert.equal(timers[0].cleared, true)
  body.resolve(new Blob(['late']))
})

test('pre-cancelled ADS download starts no network request or timer', async t => {
  const { timers } = fixture(t), parent = new AbortController()
  parent.abort('navigation')
  const fetch = t.mock.method(globalThis, 'fetch', () => { throw new Error('Unexpected request') })
  await assert.rejects(api.downloadSessionAds('session', parent.signal), { name: 'AbortError' })
  assert.equal(fetch.mock.callCount(), 0)
  assert.equal(timers.length, 0)
})

test('ADS upload keeps native multipart data and uses a scoped one-hour finite deadline', async t => {
  const { timers } = fixture(t), file = new File(['zip'], 'session.ads', { type: 'application/zip' })
  const arrays = t.mock.method(file, 'arrayBuffer', () => { throw new Error('Do not read the upload into memory') })
  const data = { status: 'ok', game_id: 'imported', message: 'Imported' }
  t.mock.method(globalThis, 'fetch', async (path, options) => {
    assert.equal(path, '/api/adventures/sessions/import')
    assert.equal(options.method, 'POST')
    assert.ok(options.body instanceof FormData)
    assert.equal(options.body.get('file').name, 'session.ads')
    assert.equal(options.headers.has('Content-Type'), false)
    assert.equal(options.headers.get('Authorization'), 'Bearer test-session-transfer')
    return Response.json(data)
  })
  assert.deepEqual(await api.importSession(file), data)
  assert.equal(arrays.mock.callCount(), 0)
  assert.deepEqual(timers.map(timer => timer.delay), [3_600_000])
  assert.equal(timers[0].cleared, true)
})

test('ADS upload remains bounded while a server response is stalled', async t => {
  const { timers } = fixture(t), pending = deferred()
  let signal
  t.mock.method(globalThis, 'fetch', (_path, options) => { signal = options.signal; return pending.promise })
  const upload = api.importSession(new File(['zip'], 'session.ads'))
  assert.equal(timers[0].delay, 3_600_000)
  timers[0].callback()
  await assert.rejects(upload, { name: 'AbortError' })
  assert.equal(signal.aborted, true)
  pending.resolve(Response.json({ status: 'ok' }))
})

test('session transfers retain central structured errors and unauthorized notifications', async t => {
  const { events } = fixture(t)
  t.mock.method(globalThis, 'fetch', async () => Response.json({ detail: 'Sign in again.' }, { status: 401 }))
  await assert.rejects(api.downloadSessionAds('session'), error => error.name === 'ApiError' && error.status === 401 && error.body.detail === 'Sign in again.')
  assert.ok(events.includes('auth-unauthorized'))
  t.mock.method(globalThis, 'fetch', async () => Response.json({ detail: 'Archive unavailable.' }, { status: 503 }))
  await assert.rejects(api.importSession(new File(['zip'], 'session.ads')), error => error.status === 503 && error.message === 'Archive unavailable.')
  assert.equal(health.isBackendReachable, false)
  assert.equal(health.lastErrorMessage, 'Server Error (503): Archive unavailable.')
})

test('ordinary adventure downloads retain their existing finite body timeout', async t => {
  const { timers } = fixture(t), response = new Response('ordinary zip')
  const arrays = t.mock.method(response, 'arrayBuffer')
  t.mock.method(globalThis, 'fetch', async () => response)
  assert.equal(await (await api.downloadAdventureAdz('adventure')).text(), 'ordinary zip')
  assert.equal(arrays.mock.callCount(), 1)
  assert.deepEqual(timers.map(timer => timer.delay), [20_000])
})

test('transfer completion and synchronous failures clear only their scoped deadline', async t => {
  const { timers } = fixture(t)
  assert.equal(await withSessionTransferDeadline(async () => 'done'), 'done')
  assert.equal(timers[0].cleared, true)
  await assert.rejects(withSessionTransferDeadline(() => { throw new Error('Local failure') }), /Local failure/)
  assert.equal(timers[1].cleared, true)
})
