/* eslint-env node, browser, es2020 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import { effectScope, nextTick, ref } from 'vue'
import ts from 'typescript'

const source = ts.transpileModule(readFileSync(new URL('../src/composables/useLivingWorldPresence.ts', import.meta.url), 'utf8'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText
  .replace(/import .* from 'vue';/, `import { watch } from '${import.meta.resolve('vue')}';
    export const mounted = []; export const unmounted = [];
    const onMounted = fn => mounted.push(fn); const onBeforeUnmount = fn => unmounted.push(fn);`)
  .replace(/import .* from '@\/services\/livingWorld';/, 'const createPresenceId = () => "tab-test"; const livingWorldRequest = (...args) => globalThis.worldRequest(...args);')
const { useLivingWorldPresence, mounted, unmounted } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
const settle = () => new Promise(resolve => setImmediate(resolve))

async function fixture(t, enabled = true, automatic = false) {
  globalThis.document = new EventTarget()
  document.visibilityState = 'visible'
  globalThis.window = new EventTarget()
  mounted.length = 0
  unmounted.length = 0
  const requests = []
  const data = { revision: 1, status: 'PARTIAL', target: 9999, settings: { living_world_enabled: enabled, auto_catchup_on_resume: automatic } }
  globalThis.worldRequest = async (id, suffix = '', method = 'GET', payload) => {
    requests.push({ id, suffix, method, payload })
    return data
  }
  t.mock.timers.enable({ apis: ['setInterval'] })
  const id = ref('session-a'), ready = ref(false)
  const scope = effectScope()
  scope.run(() => useLivingWorldPresence(() => id.value, () => ready.value))
  mounted.forEach(fn => fn())
  t.after(async () => { unmounted.forEach(fn => fn()); scope.stop(); await settle() })
  return { id, ready, requests, data }
}

test('disabled sessions do not heartbeat or start catch-up', async t => {
  const f = await fixture(t, false)
  f.ready.value = true
  await nextTick(); await settle()
  t.mock.timers.tick(20_000)
  await settle()
  assert.equal(f.requests.filter(row => row.method !== 'GET').length, 0)
})

test('presence starts, closes and switches sessions in order', async t => {
  const f = await fixture(t)
  f.ready.value = true
  await nextTick(); await settle()
  assert.equal(f.requests.at(-1).payload.active, true)
  f.id.value = 'session-b'
  await nextTick(); await settle()
  const heartbeats = f.requests.filter(row => row.suffix === '/presence')
  assert.deepEqual(heartbeats.map(row => [row.id, row.payload.active]), [['session-a', true], ['session-a', false], ['session-b', true]])
  document.visibilityState = 'hidden'
  document.dispatchEvent(new Event('visibilitychange'))
  await settle()
  assert.equal(f.requests.at(-1).payload.active, true)
  window.dispatchEvent(new Event('pagehide'))
  await settle()
  assert.equal(f.requests.at(-1).payload.active, false)
})

test('auto catch-up performs one bounded request, never loops over backlog', async t => {
  const f = await fixture(t, true, true)
  f.ready.value = true
  await nextTick(); await settle()
  t.mock.timers.tick(40_000)
  await settle()
  assert.equal(f.requests.filter(row => row.suffix === '/resume').length, 1)
  const heartbeat = f.requests.findIndex(row => row.suffix === '/presence')
  const resume = f.requests.findIndex(row => row.suffix === '/resume')
  assert.ok(heartbeat < resume)
})

test('enabling the feature through settings starts presence without reloading the session', async t => {
  const f = await fixture(t, false)
  f.ready.value = true
  await nextTick(); await settle()
  f.data.settings.living_world_enabled = true
  window.dispatchEvent(new Event('living-world-settings-changed'))
  await settle()
  assert.equal(f.requests.at(-1).payload.active, true)
})
