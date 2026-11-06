import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import { effectScope, nextTick, ref } from 'vue'
import ts from 'typescript'

function compile(source) {
  return ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
}
const utils = `data:text/javascript;base64,${Buffer.from(compile(readFileSync(new URL('../src/utils/npcPresentation.ts', import.meta.url), 'utf8'))).toString('base64')}`
const source = readFileSync(new URL('../src/composables/useSessionPortraitSettings.ts', import.meta.url), 'utf8')
const compiled = compile(source).replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
  .replace(/import .* from '@\/services\/http';/, 'const apiFetch = (...args) => globalThis.fetch(...args);')
  .replace("from '@/utils/npcPresentation'", `from '${utils}'`)
const { useSessionPortraitSettings } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
const tick = () => new Promise(resolve => setImmediate(resolve))
const off = { emotion_palette: false, character_thoughts: false, brightness: 40 }

function fixture(t, fetch) {
  t.mock.method(globalThis, 'fetch', fetch)
  const scope = effectScope()
  const session = ref('one')
  t.after(() => scope.stop())
  return { session, ...scope.run(() => useSessionPortraitSettings(() => session.value)) }
}

test('two independent opt-ins save only on explicit Save with expected server settings', async t => {
  const calls = []
  const f = fixture(t, async (url, options) => {
    calls.push({ url, options })
    return new Response(JSON.stringify(options.method === 'GET' ? off : JSON.parse(options.body).settings))
  })
  await tick()
  f.draft.value.character_thoughts = true
  assert.equal(calls.length, 1)
  assert.equal(await f.save(), true)
  const body = JSON.parse(calls[1].options.body)
  assert.equal(calls[1].url, '/adventures/one/portrait-settings')
  assert.deepEqual(body.expected, off)
  assert.deepEqual(body.settings, { ...off, character_thoughts: true })
  assert.equal(f.dirty.value, false)
})

test('conflict preserves the edit and blocks Save until the user reloads', async t => {
  const f = fixture(t, async (_url, options) => options.method === 'GET' ? new Response(JSON.stringify(off)) : new Response(JSON.stringify({ detail: 'Changed elsewhere' }), { status: 409 }))
  await tick()
  f.draft.value.emotion_palette = true
  assert.equal(await f.save(), false)
  assert.equal(f.dirty.value, true)
  assert.equal(f.error.value, 'Changed elsewhere')
})

test('late response from previous session is ignored and aborted', async t => {
  let finish
  let signal
  const f = fixture(t, async (url, options) => {
    if (url.includes('/one/')) { signal = options.signal; return new Promise(resolve => { finish = resolve }) }
    return new Response(JSON.stringify({ ...off, emotion_palette: true }))
  })
  f.session.value = 'two'
  await nextTick()
  await tick()
  assert.equal(signal.aborted, true)
  finish(new Response(JSON.stringify(off)))
  await tick()
  assert.equal(f.draft.value.emotion_palette, true)
})
