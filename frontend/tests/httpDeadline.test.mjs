import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import ts from 'typescript'

const source = ts.transpileModule(readFileSync(new URL('../src/services/http.ts', import.meta.url), 'utf8'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText.replace(/import .* from '@\/store\/auth';/, 'const authState = { token: null };')
const { apiFetch } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)

test('server-owned model deadline creates no browser timer', async t => {
  const timers = []
  globalThis.window = { setTimeout: (...args) => { timers.push(args); return 1 } }
  t.mock.method(globalThis, 'fetch', async () => new Response('{}'))
  await apiFetch('/rewrite', { timeoutMs: null })
  assert.equal(timers.length, 0)
  await apiFetch('/ordinary')
  assert.equal(timers[0][1], 15000)
})

test('explicit cancellation still works with a server-owned deadline', async t => {
  globalThis.window = { setTimeout: () => { throw new Error('Unexpected timer') } }
  const controller = new AbortController()
  controller.abort('navigation')
  t.mock.method(globalThis, 'fetch', async (_, options) => {
    assert.equal(options.signal.aborted, true)
    assert.equal(options.signal.reason, 'navigation')
    return new Response('{}')
  })
  await apiFetch('/rewrite', { timeoutMs: null, signal: controller.signal })
})

test('finite HTTP deadline includes a stalled response body', async t => {
  globalThis.window = { setTimeout: globalThis.setTimeout }
  let output
  const stream = new ReadableStream({ start(controller) { output = controller; output.enqueue(new TextEncoder().encode('{}')) } })
  const finish = setTimeout(() => output.close(), 80)
  t.mock.method(globalThis, 'fetch', async () => new Response(stream))
  try {
    await assert.rejects(apiFetch('/ordinary', { timeoutMs: 5 }).then(response => response.json()), { name: 'AbortError' })
  } finally {
    clearTimeout(finish)
    try { output.close() } catch { /* The deadline may already have closed the reader. */ }
  }
})

test('server-owned streaming responses remain unbuffered', async t => {
  globalThis.window = { setTimeout: () => { throw new Error('Unexpected timer') } }
  const response = new Response(new ReadableStream())
  t.mock.method(globalThis, 'fetch', async () => response)
  assert.equal(await apiFetch('/chat', { timeoutMs: null }), response)
})

test('completed requests release parent cancellation listeners', async t => {
  globalThis.window = { setTimeout: globalThis.setTimeout }
  const controller = new AbortController()
  const add = t.mock.method(controller.signal, 'addEventListener')
  const remove = t.mock.method(controller.signal, 'removeEventListener')
  t.mock.method(globalThis, 'fetch', async () => new Response('{"ok":true}'))
  assert.deepEqual(await (await apiFetch('/ordinary', { signal: controller.signal })).json(), { ok: true })
  assert.equal(remove.mock.callCount(), add.mock.callCount())
})
