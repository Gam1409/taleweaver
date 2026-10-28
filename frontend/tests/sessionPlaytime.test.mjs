/* eslint-env node, browser, es2020 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import { effectScope, nextTick, ref } from 'vue'
import ts from 'typescript'

function compile(path) {
  return ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
}
const source = compile('../src/composables/useSessionPlaytime.ts')
  .replace(/import .* from 'vue';/, `import { watch } from '${import.meta.resolve('vue')}';
    export const mounted = []; export const unmounted = [];
    const onMounted = fn => mounted.push(fn); const onBeforeUnmount = fn => unmounted.push(fn);`)
  .replace(/import .* from '@\/services\/http';/, 'const apiFetch = (...args) => globalThis.fetch(...args);')
const { useSessionPlaytime, mounted, unmounted } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
const { formatPlaytime } = await import(`data:text/javascript;base64,${Buffer.from(compile('../src/utils/playtime.ts')).toString('base64')}`)
const settle = () => new Promise(resolve => setImmediate(resolve))

async function fixture(t) {
  globalThis.document = new EventTarget()
  document.visibilityState = 'visible'
  globalThis.window = new EventTarget()
  mounted.length = 0
  unmounted.length = 0
  const requests = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    requests.push({ url, ...JSON.parse(options.body) })
    return new Response('{}')
  })
  t.mock.timers.enable({ apis: ['setInterval'] })
  const id = ref('session-a'), ready = ref(false)
  const scope = effectScope()
  scope.run(() => useSessionPlaytime(() => id.value, () => ready.value))
  mounted.forEach(fn => fn())
  t.after(() => { unmounted.forEach(fn => fn()); scope.stop() })
  return { id, ready, requests }
}

test('tracks only ready visible sessions and closes intervals when hidden', async t => {
  const f = await fixture(t)
  assert.equal(f.requests.length, 0)
  f.ready.value = true
  await nextTick()
  await settle()
  assert.equal(f.requests[0].start, true)
  t.mock.timers.tick(15_000)
  await settle()
  assert.equal(f.requests[1].start, false)
  document.visibilityState = 'hidden'
  document.dispatchEvent(new Event('visibilitychange'))
  await settle()
  assert.equal(f.requests[2].active, false)
  t.mock.timers.tick(60_000)
  await settle()
  assert.equal(f.requests.length, 3)
  document.visibilityState = 'visible'
  document.dispatchEvent(new Event('visibilitychange'))
  await settle()
  assert.equal(f.requests[3].start, true)
})

test('navigation closes the old session before starting the new one', async t => {
  const f = await fixture(t)
  f.ready.value = true
  await nextTick()
  await settle()
  f.id.value = 'session-b'
  await nextTick()
  await settle()
  assert.equal(f.requests[1].url, '/adventures/sessions/session-a/playtime')
  assert.equal(f.requests[1].active, false)
  assert.equal(f.requests[2].url, '/adventures/sessions/session-b/playtime')
  assert.equal(f.requests[2].start, true)
  unmounted.forEach(fn => fn())
  await settle()
  assert.equal(f.requests.at(-1).active, false)
})

test('playtime formatting shows short sessions and hours without story-clock units', () => {
  for (const [seconds, expected] of [[0, '0 min'], [15, '<1 min'], [120, '2 min'], [3660, '1 h 1 min'], [-1, '0 min'], [NaN, '0 min']]) {
    assert.equal(formatPlaytime(seconds), expected)
  }
})
