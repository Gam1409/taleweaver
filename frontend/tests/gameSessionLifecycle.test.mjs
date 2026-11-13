import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRenderer, h, ref } from 'vue'
import ts from 'typescript'

const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
const tick = () => new Promise(resolve => setImmediate(resolve))
const renderer = createRenderer({ createElement: type => ({ type, children: [] }), createText: text => ({ text }), createComment: text => ({ text }), setText() {}, setElementText() {}, patchProp() {}, insert(node, parent) { parent.children.push(node) }, remove() {}, parentNode: () => null, nextSibling: () => null })
let serial = 0
async function fixture(t, delayConnect = false) {
  const fallback = deferred(), initialConnect = deferred(), routeId = ref('old-template'), status = ref('disconnected')
  const replaced = [], connections = [], fallbacks = [], key = `routeFixture${serial++}`
  globalThis[key] = { fetchGameSettings: async () => null, ensureGameIdForRouteId: id => { fallbacks.push(id); return fallback.promise } }
  const service = `data:text/javascript;base64,${Buffer.from('export const gameViewService = globalThis[new URL(import.meta.url).hash.slice(1)]').toString('base64')}#${key}`
  const source = readFileSync(new URL('../src/composables/useGameSessionLifecycle.ts', import.meta.url), 'utf8')
  const code = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
    .replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
    .replace("from '@/services/gameViewService'", `from '${service}'`)
  const module = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)
  const originalWindow = globalThis.window
  globalThis.window = new EventTarget()
  const app = renderer.createApp({ setup() {
    module.useGameSessionLifecycle({ routeId, status, gameSettings: ref({}), router: { replace: async value => { replaced.push(value) } },
      connect: async id => { connections.push(id); if (delayConnect && connections.length === 1) await initialConnect.promise; status.value = id === 'working-session' ? 'connected' : 'error' },
      disconnect: () => { status.value = 'disconnected' }, closePanels() {} })
    return () => h('div')
  } })
  app.mount({ children: [] })
  t.after(() => { app.unmount(); delete globalThis[key]; globalThis.window = originalWindow })
  await tick()
  return { fallback, initialConnect, routeId, status, replaced, connections, fallbacks, app }
}

for (const ending of ['switch', 'unmount', 'return']) test(`stale route fallback cannot navigate after ${ending}`, async t => {
  const f = await fixture(t)
  if (ending === 'unmount') f.app.unmount()
  else { f.routeId.value = 'working-session'; await tick() }
  if (ending === 'return') { f.routeId.value = 'old-template'; await tick() }
  f.fallback.resolve('resolved-old-session')
  await tick()
  assert.equal(f.replaced.length, ending === 'return' ? 1 : 0)
})

test('a stale initial connection cannot start a fallback for the next route error', async t => {
  const f = await fixture(t, true)
  f.routeId.value = 'second-template'
  await tick()
  f.initialConnect.resolve()
  await tick()
  assert.deepEqual(f.fallbacks, ['second-template'])
  f.fallback.resolve(null)
})

test('active alias fallback still redirects once, and empty/same aliases do not', async t => {
  const f = await fixture(t)
  f.fallback.resolve('resolved-old-session')
  await tick()
  assert.deepEqual(f.replaced, [{ name: 'game', params: { id: 'resolved-old-session' } }])
})
for (const resolved of [null, 'old-template']) test(`an active fallback resolving ${resolved} leaves its route`, async t => {
  const f = await fixture(t)
  f.fallback.resolve(resolved)
  await tick()
  assert.deepEqual(f.replaced, [])
})

test('an A to B to A route change within one tick cannot revive the first fallback', async t => {
  const f = await fixture(t)
  f.routeId.value = 'working-session'
  f.routeId.value = 'old-template'
  f.fallback.resolve('resolved-old-session')
  await tick()
  assert.equal(f.replaced.length, 1)
  assert.deepEqual(f.connections, ['old-template', 'working-session', 'old-template'])
})
