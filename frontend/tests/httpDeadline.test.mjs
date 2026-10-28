/* eslint-env node, browser, es2020 */
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
