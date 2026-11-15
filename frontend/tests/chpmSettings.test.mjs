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

test('twenty-person roster budgets active participants and explicitly supports all present', async t => {
  const f = fixture(t, async () => new Response(JSON.stringify(state())))
  await tick()
  f.draft.value.mode = 'live'
  f.draft.value.actor_ids = Array.from({ length: 20 }, (_, i) => `NPC-${i}`)
  f.draft.value.max_active_npcs = 3
  f.draft.value.max_calls_per_turn = 8
  assert.equal(f.minimumCalls.value, 8)
  assert.equal(f.budgetWarning.value, false)
  f.draft.value.max_active_npcs = 20
  assert.equal(f.minimumCalls.value, 25)
  assert.equal(f.budgetWarning.value, true)
  f.draft.value.max_calls_per_turn = 25
  assert.equal(f.budgetWarning.value, false)
})

function fixture(t, fetch) {
  t.mock.method(globalThis, 'fetch', fetch)
  const scope = effectScope()
  const session = ref('one')
  t.after(() => scope.stop())
  return { session, ...scope.run(() => useChpmSettings(() => session.value)) }
}

test('workflow switching preserves limits and the actual last-run timing mode', async t => {
  const saved = state(3)
  Object.assign(saved.settings, { workflow: 'staged', mode: 'live', actor_ids: ['NPC'], max_active_npcs: 1, agent_steps: 2, notebook_enabled: true, max_calls_per_turn: 8 })
  saved.usage.workflow = 'staged'
  const f = fixture(t, async (_url, options) => {
    if (options.method === 'GET') return Response.json(saved)
    const body = JSON.parse(options.body)
    assert.equal(body.expected_revision, 3)
    assert.equal(body.settings.workflow, 'integrated')
    assert.equal(body.settings.agent_steps, 2)
    assert.equal(body.settings.notebook_enabled, true)
    assert.equal(body.settings.max_calls_per_turn, 8)
    return Response.json({ ...saved, revision: 4, settings: body.settings })
  })
  await tick()
  const minimum = f.minimumCalls.value
  f.setWorkflow('integrated')
  assert.equal(f.draft.value.max_input_chars, 48000)
  assert.equal(f.status.value.usage.workflow, 'staged')
  assert.equal(f.minimumCalls.value, minimum)
  assert.equal(await f.save(), true)
  assert.equal(f.draft.value.workflow, 'integrated')
  assert.equal(f.status.value.usage.workflow, 'staged')
})

test('selecting either workflow preserves an already larger input budget', async t => {
  const saved = state()
  saved.settings.max_input_chars = 64000
  const f = fixture(t, async () => Response.json(saved))
  await tick()
  f.setWorkflow('integrated')
  assert.equal(f.draft.value.max_input_chars, 64000)
  f.setWorkflow('staged')
  assert.equal(f.draft.value.max_input_chars, 64000)
  assert.equal(saved.settings.max_input_chars, 64000)
})

test('semantic memory is opt-in, session-scoped, and does not increase generative calls', async t => {
  const saved = state(3)
  saved.settings.semantic_memory = false
  const f = fixture(t, async (url, options) => {
    if (options.method === 'GET') return new Response(JSON.stringify(saved))
    assert.ok(url.includes('/one/chpm'))
    const body = JSON.parse(options.body)
    assert.equal(body.settings.semantic_memory, true)
    return new Response(JSON.stringify({ ...saved, revision: 4, settings: body.settings }))
  })
  await tick()
  assert.equal(f.draft.value.semantic_memory, false)
  const calls = f.minimumCalls.value
  f.draft.value.semantic_memory = true
  assert.equal(f.minimumCalls.value, calls)
  assert.equal(f.status.value.settings.semantic_memory, false)
  assert.equal(await f.save(), true)
  assert.equal(f.status.value.settings.semantic_memory, true)
})

test('tool protocol changes persist without changing notebook data or request limits', async t => {
  const saved = state(3)
  Object.assign(saved.settings, { mode: 'live', actor_ids: ['NPC'], max_active_npcs: 1,
    notebook_enabled: true, agent_steps: 2, tool_protocol: 'auto', max_calls_per_turn: 8 })
  const f = fixture(t, async (_url, options) => {
    if (options.method === 'GET') return new Response(JSON.stringify(saved))
    const body = JSON.parse(options.body)
    assert.equal(body.settings.tool_protocol, 'json')
    assert.equal(body.settings.notebook_enabled, true)
    assert.equal(body.settings.agent_steps, 2)
    assert.equal(body.settings.max_calls_per_turn, 8)
    return new Response(JSON.stringify({ ...saved, revision: 4, settings: body.settings }))
  })
  await tick()
  const minimum = f.minimumCalls.value
  f.draft.value.tool_protocol = 'json'
  assert.equal(f.minimumCalls.value, minimum)
  assert.equal(await f.save(), true)
  assert.equal(f.status.value.settings.tool_protocol, 'json')
})

test('private notebooks stay off for legacy sessions until explicitly enabled and saved', async t => {
  const saved = state(2), methods = []
  const f = fixture(t, async (_url, options) => {
    methods.push(options.method)
    if (options.method === 'GET') return new Response(JSON.stringify(saved))
    const body = JSON.parse(options.body)
    assert.equal(body.expected_revision, 2)
    assert.equal(body.settings.notebook_enabled, true)
    assert.equal(body.settings.agent_steps, 1)
    return new Response(JSON.stringify({ ...saved, revision: 3, settings: body.settings }))
  })
  await tick()
  assert.equal(f.draft.value.notebook_enabled ?? false, false)
  assert.equal(f.draft.value.agent_steps ?? 0, 0)
  f.draft.value.mode = 'live'
  f.draft.value.actor_ids = ['NPC']
  f.setNotebookEnabled(true)
  assert.equal(f.draft.value.notebook_enabled, true)
  assert.equal(f.draft.value.agent_steps, 1)
  assert.equal(f.status.value.settings.notebook_enabled ?? false, false)
  assert.equal(f.draft.value.max_calls_per_turn, 6)
  assert.equal(f.minimumCalls.value, 7)
  assert.equal(await f.save(), false)
  assert.deepEqual(methods, ['GET'])
  f.draft.value.max_calls_per_turn = 7
  assert.equal(await f.save(), true)
  assert.deepEqual(methods, ['GET', 'PATCH'])
  assert.equal(f.status.value.settings.notebook_enabled, true)
})

test('notebook toggles preserve selected agent rounds and observe mode request costs', async t => {
  const f = fixture(t, async () => new Response(JSON.stringify(state())))
  await tick()
  f.draft.value.mode = 'live'
  f.draft.value.actor_ids = ['NPC']
  f.draft.value.agent_steps = 2
  f.setNotebookEnabled(true)
  assert.equal(f.draft.value.agent_steps, 2)
  assert.equal(f.minimumCalls.value, 8)
  f.setNotebookEnabled(false)
  assert.equal(f.draft.value.notebook_enabled, false)
  assert.equal(f.draft.value.agent_steps, 2)
  f.draft.value.mode = 'shadow'
  assert.equal(f.minimumCalls.value, 2)
  f.draft.value.mode = 'off'
  assert.equal(f.minimumCalls.value, 0)
})

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

test('three live NPCs need eight requests without silently raising the saved budget', async t => {
  const calls = []
  const f = fixture(t, async (_url, options) => {
    calls.push(options.method)
    return new Response(JSON.stringify(state()))
  })
  await tick()
  f.draft.value.mode = 'live'
  f.draft.value.actor_ids = ['NPC', 'B', 'C']
  assert.equal(f.minimumCalls.value, 8)
  assert.equal(f.budgetWarning.value, true)
  assert.equal(f.draft.value.max_calls_per_turn, 6)
  assert.equal(await f.save(), false)
  assert.deepEqual(calls, ['GET'])
  f.draft.value.max_calls_per_turn = 8
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

test('agent rounds reserve calls per active NPC and stay off in observe mode', async t => {
  const f = fixture(t, async () => new Response(JSON.stringify(state())))
  await tick()
  f.draft.value.mode = 'live'
  f.draft.value.actor_ids = ['A', 'B', 'C']
  f.draft.value.agent_steps = 2
  f.draft.value.max_calls_per_turn = 8
  assert.equal(f.minimumCalls.value, 14)
  assert.equal(await f.save(), false)
  f.draft.value.agent_steps = 3
  assert.equal(f.minimumCalls.value, 17)
  assert.equal(await f.save(), false)
  f.draft.value.mode = 'shadow'
  assert.equal(f.minimumCalls.value, 4)
})
