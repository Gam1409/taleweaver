/* eslint-env node, browser, es2020 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import { effectScope, ref } from 'vue'
import ts from 'typescript'

const source = readFileSync(new URL('../src/composables/useNarrationRegeneration.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText.replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
  .replace(/import .* from '@\/services\/http';/, 'const apiFetch = (...args) => globalThis.fetch(...args);')
  .replace(/import .* from '@\/composables\/useNotifications';/, 'export const notices = []; const useNotifications = () => ({ addNotification: (...args) => notices.push(args) });')
const { useNarrationRegeneration, notices } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

function fixture(t) {
  const socket = {
    messages: ref([{ id: 'reply', role: 'assistant', content: 'Original' }]),
    status: ref('connected'), statusText: ref(''), inputLocked: ref(false), sheet: ref({}),
  }
  const scope = effectScope()
  t.after(() => scope.stop())
  return { socket, scope, ...scope.run(() => useNarrationRegeneration(() => 'session', socket)) }
}

test('regeneration locks input, prevents double clicks and replaces the same message', async t => {
  const f = fixture(t)
  let finish
  t.mock.method(globalThis, 'fetch', () => new Promise(resolve => { finish = resolve }))
  const pending = f.regenerate()
  assert.equal(f.socket.status.value, 'loading')
  assert.equal(f.busy.value, true)
  await f.regenerate()
  assert.equal(globalThis.fetch.mock.callCount(), 1)
  assert.equal(globalThis.fetch.mock.calls[0].arguments[1].timeoutMs, null)
  finish(new Response(JSON.stringify({ id: 'reply', role: 'assistant', content: 'Replacement' })))
  await pending
  assert.deepEqual(f.socket.messages.value, [{ id: 'reply', role: 'assistant', content: 'Replacement' }])
  assert.equal(f.socket.status.value, 'connected')
})

test('failed regeneration keeps the original and displays an error', async t => {
  const f = fixture(t)
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ detail: 'Unavailable' }), { status: 502 }))
  await f.regenerate()
  assert.equal(f.socket.messages.value[0].content, 'Original')
  assert.equal(f.socket.status.value, 'connected')
  assert.equal(notices.at(-1)[0], 'Unavailable')
})

test('a pending player message disables regeneration', t => {
  const f = fixture(t)
  f.socket.messages.value.push({ id: 'action', role: 'user', content: 'Open gate' })
  assert.equal(f.canRegenerate.value, false)
})

test('leaving the view prevents late writes to a different session', async t => {
  const f = fixture(t)
  let finish
  t.mock.method(globalThis, 'fetch', () => new Promise(resolve => { finish = resolve }))
  const pending = f.regenerate()
  f.scope.stop()
  f.socket.messages.value = []
  f.socket.status.value = 'connecting'
  finish(new Response(JSON.stringify({ id: 'reply', role: 'assistant', content: 'Replacement' })))
  await pending
  assert.deepEqual(f.socket.messages.value, [])
  assert.equal(f.socket.status.value, 'connecting')
})
