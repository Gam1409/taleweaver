import { test } from 'node:test'
import { setImmediate } from 'node:timers'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

const source = readFileSync(new URL('../src/composables/useLivingWorldPresence.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
}).outputText.replace(/^import .*$/gm, '').replace('export function', 'function')
const build = new Function('onMounted', 'onBeforeUnmount', 'watch', 'createPresenceId', 'livingWorldRequest', 'document', 'window', 'setInterval', 'clearInterval', `${compiled}; return useLivingWorldPresence;`)
const tick = () => new Promise(resolve => setImmediate(resolve))
const enabled = { settings: { living_world_enabled: true, live_enabled: true } }
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { resolve, promise } }

function fixture(request) {
  const callbacks = {}
  const doc = { hidden: false, addEventListener: (key, cb) => { callbacks[key] = cb }, removeEventListener: () => {} }
  const win = { addEventListener: (key, cb) => { callbacks[key] = cb }, removeEventListener: () => {} }
  let id = 'first'
  const use = build(cb => { callbacks.mount = cb }, cb => { callbacks.unmount = cb }, (_, cb) => { callbacks.watch = cb }, () => 'tab', request, doc, win, cb => { callbacks.timer = cb; return 1 }, () => {})
  use(() => id, () => true)
  callbacks.mount()
  return { doc, callbacks, navigate: value => { id = value; callbacks.watch() } }
}

for (const leave of ['hide', 'unmount']) {
  test(`pending status cannot reactivate a session after ${leave}`, async () => {
    const pending = deferred(), calls = []
    const env = fixture(async (id, suffix, method, payload) => {
      calls.push({ id, suffix, payload })
      return suffix ? {} : pending.promise
    })
    if (leave === 'hide') { env.doc.hidden = true; env.callbacks.visibilitychange() }
    else env.callbacks.unmount()
    pending.resolve(enabled)
    await tick()
    assert.equal(calls.filter(call => call.payload?.active).length, 0)
  })
}

test('queued heartbeats coalesce and use the latest session', async () => {
  const pending = deferred(), calls = []
  const env = fixture(async (id, suffix, method, payload) => {
    calls.push({ id, suffix, payload })
    if (suffix) return {}
    return id === 'first' ? pending.promise : enabled
  })
  for (let index = 0; index < 50; index++) env.callbacks.timer()
  env.navigate('second')
  pending.resolve(enabled)
  await tick()
  assert.deepEqual(calls.map(call => [call.id, call.suffix || 'GET']), [
    ['first', 'GET'], ['second', 'GET'], ['second', '/presence']
  ])
})

test('hiding during an already sent heartbeat sends a departure', async () => {
  const pending = deferred(), calls = []
  const env = fixture(async (id, suffix, method, payload) => {
    calls.push({ suffix, payload })
    return payload?.active ? pending.promise : enabled
  })
  await tick()
  env.doc.hidden = true
  env.callbacks.visibilitychange()
  pending.resolve({})
  await tick()
  assert.deepEqual(calls.filter(call => call.suffix).map(call => call.payload.active), [true, false])
})
