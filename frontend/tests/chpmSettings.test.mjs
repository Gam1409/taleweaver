/* eslint-env es2021 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import { setImmediate } from 'node:timers'
import { effectScope, nextTick, ref } from 'vue'
import ts from 'typescript'

const source = readFileSync(new URL('../src/composables/useChpmSettings.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText.replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
  .replace(/import .* from '@\/services\/http';/, 'const apiFetch = (...args) => globalThis.fetch(...args);')
const { useChpmSettings } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
const tick = () => new Promise(resolve => setImmediate(resolve))
const state = (revision = 0) => ({
  revision, available: true,
  settings: { mode: 'off', actor_ids: [], model_role: 'complex', max_output_tokens: 1200, max_input_chars: 24000, max_calls_per_turn: 6 },
  characters: [{ id: 'NPC', name: 'Lina' }], usage: { calls: 0, input_chars: 0, output_chars: 0, repairs: 0, status: 'idle', detail: '' }, trace: [],
})

function fixture(t, fetch) {
  t.mock.method(globalThis, 'fetch', fetch)
  const scope = effectScope()
  const session = ref('one')
  t.after(() => scope.stop())
  return { session, ...scope.run(() => useChpmSettings(() => session.value)) }
}

test('selection stays local and save fences the revision without aliasing the saved array', async t => {
  const calls = []
  const f = fixture(t, async (url, options) => {
    calls.push({ url, options })
    if (options.method === 'GET') return new Response(JSON.stringify(state(4)))
    const body = JSON.parse(options.body)
    assert.equal(body.expected_revision, 4)
    assert.deepEqual(body.settings.actor_ids, ['NPC'])
    return new Response(JSON.stringify({ ...state(5), settings: body.settings }))
  })
  await tick()
  f.draft.value.mode = 'shadow'
  f.draft.value.actor_ids.push('NPC')
  assert.deepEqual(f.status.value.settings.actor_ids, [])
  assert.equal(f.dirty.value, true)
  assert.equal(calls.length, 1)
  assert.equal(await f.save(), true)
  assert.equal(f.status.value.revision, 5)
  assert.equal(f.dirty.value, false)
  assert.equal(await f.save(), true)
  assert.equal(calls.length, 2)
})

test('conflict preserves edits and prevents the parent save from succeeding', async t => {
  const f = fixture(t, async (_url, options) => options.method === 'GET'
    ? new Response(JSON.stringify(state()))
    : new Response(JSON.stringify({ detail: 'Reload before saving.' }), { status: 409 }))
  await tick()
  f.draft.value.mode = 'live'
  f.draft.value.actor_ids.push('NPC')
  assert.equal(await f.save(), false)
  assert.equal(f.draft.value.mode, 'live')
  assert.equal(f.error.value, 'Reload before saving.')
})

test('switching sessions aborts and discards a late response', async t => {
  let finish
  let oldSignal
  const f = fixture(t, async (url, options) => {
    if (url.includes('/one/')) {
      oldSignal = options.signal
      return new Promise(resolve => { finish = resolve })
    }
    return new Response(JSON.stringify(state(8)))
  })
  f.session.value = 'two'
  await nextTick()
  await tick()
  assert.equal(oldSignal.aborted, true)
  finish(new Response(JSON.stringify(state(0))))
  await tick()
  assert.equal(f.status.value.revision, 8)
})

test('three live NPCs need seven requests without silently raising the saved budget', async t => {
  const calls = []
  const f = fixture(t, async (_url, options) => {
    calls.push(options.method)
    return new Response(JSON.stringify(state()))
  })
  await tick()
  f.draft.value.mode = 'live'
  f.draft.value.actor_ids = ['NPC', 'B', 'C']
  assert.equal(f.minimumCalls.value, 7)
  assert.equal(f.budgetWarning.value, true)
  assert.equal(f.draft.value.max_calls_per_turn, 6)
  assert.equal(await f.save(), false)
  assert.deepEqual(calls, ['GET'])
  f.draft.value.max_calls_per_turn = 7
  assert.equal(f.budgetWarning.value, false)
  f.draft.value.mode = 'shadow'
  assert.equal(f.minimumCalls.value, 4)
})

test('capacity warning offers an explicit draft-only switch preserving stored history', async t => {
  const saved = state()
  saved.settings.mode = 'live'
  saved.settings.actor_ids = ['NPC']
  saved.history_capacity = { NPC: {
    status: 'pause_required', used: { events: 500, beliefs: 10 },
    limits: { events: 512, beliefs: 256 }, blocking_resources: ['events'],
  } }
  const f = fixture(t, async () => new Response(JSON.stringify(saved)))
  await tick()
  assert.equal(f.historyWarnings.value[0].name, 'Lina')
  f.selectStandard()
  assert.equal(f.draft.value.mode, 'off')
  assert.equal(f.status.value.settings.mode, 'live')
  assert.equal(f.status.value.history_capacity.NPC.used.events, 500)
  assert.equal(f.historyWarnings.value.length, 0)
  assert.equal(f.dirty.value, true)
})
