import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'
const uri = code => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
const compile = path => ts.transpileModule(readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
const http = uri(compile('services/http.ts').replace(/import .* from '@\/store\/auth';/, 'const authState = {token:null};'))
const source = compile('composables/useApi.ts')
  .replace(/import .* from '@\/services\/visualJobs';/, 'const runVisualJob = () => { throw new Error("Unexpected visual request") };')
  .replace(/import .* from '@\/store\/auth';/, 'const authState = {token:null, isAuthenticated:false};')
  .replace(/import .* from '@\/store\/config';/, 'const configState = globalThis.voiceApiHealth;')
  .replace("from '@/services/http'", `from '${http}'`)
globalThis.voiceApiHealth = { isBackendReachable: true, lastErrorMessage: '' }
const { api } = await import(uri(source))
function setup(t) {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'window')
  Object.defineProperty(globalThis, 'window', { configurable: true, value: { setTimeout, dispatchEvent() {} } })
  t.after(() => { if (previous) Object.defineProperty(globalThis, 'window', previous); else delete globalThis.window })
  Object.assign(globalThis.voiceApiHealth, { isBackendReachable: true, lastErrorMessage: '' })
  return globalThis.voiceApiHealth
}
test('transcription forwards cancellation while preserving its WAV multipart request', async t => {
  const health = setup(t), controller = new AbortController()
  let finish, sent
  t.mock.method(globalThis, 'fetch', (path, options) => { sent = { path, options }; return new Promise(resolve => { finish = resolve }) })
  const request = api.transcribeAudio(new Blob(['wav'], { type: 'audio/wav' }), controller.signal)
  controller.abort('session changed')
  finish(Response.json({ text: 'stale' }))
  await assert.rejects(request, { name: 'AbortError' })
  assert.equal(sent.path, '/api/stt/transcribe')
  assert.equal(sent.options.signal.aborted, true)
  assert.equal(sent.options.body.get('file').name, 'audio.wav')
  assert.equal(sent.options.headers.has('Content-Type'), false)
  assert.equal(health.isBackendReachable, true); assert.equal(health.lastErrorMessage, '')
})
test('intentional request cancellation keeps backend health while real network errors still report failure', async t => {
  const health = setup(t), controller = new AbortController()
  let finish
  t.mock.method(globalThis, 'fetch', () => new Promise(resolve => { finish = resolve }))
  const request = api.getAdventureStatus('one', controller.signal)
  controller.abort('navigation')
  finish(Response.json({ status: 'ready' }))
  await assert.rejects(request, { name: 'AbortError' })
  assert.equal(health.isBackendReachable, true); assert.equal(health.lastErrorMessage, '')
  t.mock.method(globalThis, 'fetch', async () => { throw new TypeError('Connection lost') })
  await assert.rejects(api.transcribeAudio(new Blob(['wav'])), /Connection lost/)
  assert.equal(health.isBackendReachable, false); assert.equal(health.lastErrorMessage, 'Connection lost')
})
