import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import { effectScope, ref } from 'vue'
import ts from 'typescript'
import { statusPollerModule } from './statusPollerModule.mjs'

let sequence = 0
const settle = () => new Promise(resolve => setImmediate(resolve))

async function fixture(t, read) {
  t.mock.timers.enable({ apis: ['setTimeout', 'setInterval'] })
  const key = `portalPoll${sequence++}`
  globalThis[key] = { getAdventureStatus: read }
  globalThis.window = { setInterval: (...args) => setInterval(...args) }
  const source = readFileSync(
    new URL('../src/composables/usePortalPendingState.ts', import.meta.url),
    'utf8'
  )
  const code = ts
    .transpileModule(source, {
      compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
    })
    .outputText.replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
    .replace(/import .* from '@\/composables\/useApi';/, `const api = globalThis['${key}'];`)
    .replace("from '@/services/statusPoller'", `from '${statusPollerModule}'`)
  const { usePortalPendingState } = await import(
    `data:text/javascript;base64,${Buffer.from(code).toString('base64')}#${key}`
  )
  const scope = effectScope()
  const model = scope.run(() => usePortalPendingState(ref([]), ref([])))
  t.after(() => {
    scope.stop()
    delete globalThis[key]
  })
  return { model, scope }
}

test('slow portal status requests never overlap', async t => {
  let count = 0,
    release
  const f = await fixture(t, async () => {
    count++
    return new Promise(resolve => {
      release = resolve
    })
  })
  f.model.trackNewAdventure('world', 'World', async () => {})
  t.mock.timers.tick(3000)
  await settle()
  assert.equal(count, 1)
  release({ status: 'Ready', is_ready: true })
  await settle()
})

test('portal monitoring stops when its effect scope is disposed', async t => {
  let count = 0
  const f = await fixture(t, async () => {
    count++
    return { status: 'Building', is_ready: false }
  })
  f.model.trackNewAdventure('world', 'World', async () => {})
  t.mock.timers.tick(1500)
  await settle()
  const before = count
  f.scope.stop()
  t.mock.timers.tick(30_000)
  await settle()
  assert.equal(count, before)
})

test('network failures pause bounded retries without declaring server generation failed', async t => {
  let count = 0,
    available = false,
    refreshed = 0
  const f = await fixture(t, async () => {
    count++
    if (!available) throw new TypeError('Offline')
    return { status: 'Ready', is_ready: true }
  })
  const refresh = async () => {
    refreshed++
  }
  f.model.trackNewAdventure('world', 'World', refresh)
  for (let index = 0; index < 12; index++) {
    t.mock.timers.tick(30_000)
    await settle()
  }
  assert.ok(count <= 6)
  assert.equal(f.model.pendingCards.value[0].hasError, false)
  assert.equal(f.model.pendingCards.value[0].connectionPaused, true)
  const paused = count
  available = true
  f.model.retryPendingAdventure('world', refresh)
  await settle()
  assert.equal(count, paused + 1)
  assert.equal(f.model.pendingCards.value.length, 0)
  assert.equal(refreshed, 1)
})

test('a confirmed backend failure stops monitoring and stays distinct from offline status', async t => {
  let count = 0
  const f = await fixture(t, async () => {
    count++
    return { status: 'Failed', is_ready: false, error: 'Generation stopped' }
  })
  f.model.trackNewAdventure('world', 'World', async () => {})
  await settle()
  t.mock.timers.tick(60_000)
  await settle()
  assert.equal(count, 1)
  assert.equal(f.model.pendingCards.value[0].hasError, true)
  assert.equal(f.model.pendingCards.value[0].connectionPaused, false)
})

test('a late response after disposal cannot mutate cards or refresh the library', async t => {
  let release,
    refreshed = 0,
    signal
  const f = await fixture(t, async (_id, input) => {
    signal = input
    return new Promise(resolve => {
      release = resolve
    })
  })
  f.model.trackNewAdventure('world', 'World', async () => {
    refreshed++
  })
  await settle()
  f.scope.stop()
  assert.equal(signal.aborted, true)
  release({ status: 'Ready', is_ready: true })
  await settle()
  assert.equal(refreshed, 0)
  assert.equal(f.model.pendingCards.value.length, 1)
})
