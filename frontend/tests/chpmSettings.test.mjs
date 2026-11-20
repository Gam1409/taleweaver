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

test('legacy missing tool profile loads as Auto without making settings dirty or saving', async t => {
  const methods = []
  const saved = state()
  const f = fixture(t, async (_url, options) => {
    methods.push(options.method)
    return Response.json(saved)
  })
  await tick()
  assert.equal(f.draft.value.tool_profile, 'auto')
  assert.equal(f.status.value.settings.tool_profile, 'auto')
  assert.equal(saved.settings.tool_profile, undefined)
  assert.equal(f.dirty.value, false)
  assert.equal(await f.save(), true)
  assert.deepEqual(methods, ['GET'])
})

for (const profile of ['auto', 'anthropic', 'openai', 'mistral', 'gemma', 'deepseek', 'qwen']) {
  test(`tool profile ${profile} persists independently of saved protocol and dormant preferences`, async t => {
    const saved = state(7)
    Object.assign(saved.settings, {
      tool_profile: 'openai', tool_protocol: 'json', workflow: 'integrated',
      notebook_enabled: true, semantic_memory: true, agent_steps: 3,
      max_calls_per_turn: 25, max_input_chars: 64000, future_preference: 'retained',
    })
    const f = fixture(t, async (_url, options) => {
      if (options.method === 'GET') return Response.json(saved)
      const body = JSON.parse(options.body)
      assert.equal(body.expected_revision, 7)
      assert.deepEqual(body.settings, { ...saved.settings, tool_profile: profile })
      return Response.json({ ...saved, revision: 8, settings: body.settings })
    })
    await tick()
    assert.equal(f.draft.value.tool_profile, 'openai')
    const budget = f.minimumCalls.value
    f.setToolProfile(profile)
    assert.equal(f.minimumCalls.value, budget)
    assert.equal(f.status.value.settings.tool_profile, 'openai')
    assert.equal(await f.save(), true)
    assert.equal(f.draft.value.tool_profile, profile)
    assert.equal(f.dirty.value, false)
  })
}

test('unrecognized saved profile preferences are retained without a silent rewrite or save loop', async t => {
  const saved = state(), methods = []
  saved.settings.tool_profile = 'future-profile'
  const f = fixture(t, async (_url, options) => { methods.push(options.method); return Response.json(saved) })
  await tick()
  assert.equal(f.draft.value.tool_profile, 'future-profile')
  assert.equal(f.dirty.value, false)
  assert.equal(await f.save(), true)
  assert.deepEqual(methods, ['GET'])
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

test('world actions opt in locally with an integrated round and are saved explicitly', async t => {
  const saved = state(3)
  Object.assign(saved.settings, { mode: 'live', actor_ids: ['NPC'], max_active_npcs: 1, max_calls_per_turn: 8 })
  const f = fixture(t, async (_url, options) => {
    if (options.method === 'GET') return Response.json(saved)
    const body = JSON.parse(options.body)
    assert.equal(body.settings.action_tools, true)
    assert.equal(body.settings.workflow, 'integrated')
    assert.equal(body.settings.agent_steps, 1)
    assert.equal(body.settings.max_input_chars, 48000)
    assert.equal(body.settings.max_calls_per_turn, 8)
    return Response.json({ ...saved, revision: 4, settings: body.settings })
  })
  await tick()
  assert.equal(f.draft.value.action_tools ?? false, false)
  f.setActionToolsEnabled(true)
  assert.equal(f.draft.value.action_tools, true)
  assert.equal(f.status.value.settings.action_tools, undefined)
  assert.equal(await f.save(), true)
  assert.equal(f.status.value.settings.action_tools, true)
})

test('disabling world actions preserves notebook choice, selected rounds and larger input limits', async t => {
  const saved = state()
  Object.assign(saved.settings, { workflow: 'integrated', action_tools: true, notebook_enabled: true, agent_steps: 3, max_input_chars: 64000 })
  const f = fixture(t, async () => Response.json(saved))
  await tick()
  f.setActionToolsEnabled(false)
  assert.equal(f.draft.value.action_tools, false)
  assert.equal(f.draft.value.workflow, 'integrated')
  assert.equal(f.draft.value.notebook_enabled, true)
  assert.equal(f.draft.value.agent_steps, 3)
  assert.equal(f.draft.value.max_input_chars, 64000)
})

test('returning to staged decisions disables incompatible world actions without disabling notes', async t => {
  const saved = state()
  Object.assign(saved.settings, { workflow: 'integrated', action_tools: true, notebook_enabled: true, agent_steps: 2 })
  const f = fixture(t, async () => Response.json(saved))
  await tick()
  f.setWorkflow('staged')
  assert.equal(f.draft.value.action_tools, false)
  assert.equal(f.draft.value.workflow, 'staged')
  assert.equal(f.draft.value.notebook_enabled, true)
  assert.equal(f.draft.value.agent_steps, 2)
  assert.equal(saved.settings.action_tools, true)
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

test('RPG saves require compatible explicit action control and preserve the server-derived scope', async t => {
  const saved = { ...state(4), host_mode: 'rpg' }
  Object.assign(saved.settings, { control_scope: 'combat_actions', actor_ids: ['NPC'], max_calls_per_turn: 8 })
  const methods = []
  const f = fixture(t, async (_url, options) => {
    methods.push(options.method)
    if (options.method === 'GET') return Response.json(saved)
    const body = JSON.parse(options.body)
    assert.equal(body.settings.control_scope, 'combat_actions')
    assert.equal(body.settings.workflow, 'integrated')
    assert.equal(body.settings.action_tools, true)
    return Response.json({ ...saved, revision: 5, settings: body.settings })
  })
  await tick()
  f.draft.value.mode = 'live'
  assert.equal(await f.save(), false)
  assert.match(f.error.value, /Enable combat action control/)
  assert.deepEqual(methods, ['GET'])
  f.setActionToolsEnabled(true)
  assert.equal(await f.save(), true)
  f.selectStandard()
  assert.equal(await f.save(), true)
})

test('combat tool budgets track active selection and rounds without dialogue reserves or history warnings', async t => {
  const saved = { ...state(), host_mode: 'rpg', history_capacity: { NPC: { status: 'pause_required' } } }
  Object.assign(saved.settings, { mode: 'live', actor_ids: ['NPC', 'B', 'C'], max_active_npcs: 2,
    control_scope: 'combat_actions', workflow: 'integrated', action_tools: true, agent_steps: 3, max_calls_per_turn: 5 })
  const f = fixture(t, async () => Response.json(saved))
  await tick()
  assert.equal(f.minimumCalls.value, 18)
  assert.equal(f.budgetWarning.value, true)
  assert.deepEqual(f.historyWarnings.value, [])
  assert.equal(await f.save(), false)
  assert.match(f.error.value, /combat tool rounds/)
  assert.doesNotMatch(f.error.value, /perception|review|narration/)
  f.draft.value.agent_steps = 1
  assert.equal(f.minimumCalls.value, 6)
  f.draft.value.max_active_npcs = 3
  assert.equal(f.minimumCalls.value, 9)
  f.selectStandard()
  assert.equal(f.minimumCalls.value, 0)
})

test('combat budget reserves crossing initiative turns within the 25-call cap', async t => {
  const saved = { ...state(), host_mode: 'rpg' }
  Object.assign(saved.settings, { mode: 'live', actor_ids: Array.from({ length: 9 }, (_, index) => `NPC-${index}`),
    max_active_npcs: 8, workflow: 'integrated', action_tools: true, agent_steps: 1, max_calls_per_turn: 25 })
  const f = fixture(t, async () => Response.json(saved))
  await tick()
  assert.equal(f.minimumCalls.value, 24)
  assert.equal(f.budgetWarning.value, false)
  f.draft.value.max_active_npcs = 9
  assert.equal(f.minimumCalls.value, 27)
  assert.equal(await f.save(), false)
  f.draft.value.max_active_npcs = 4
  f.draft.value.agent_steps = 2
  assert.equal(f.minimumCalls.value, 24)
  assert.equal(f.budgetWarning.value, false)
  f.draft.value.max_active_npcs = 2
  f.draft.value.agent_steps = 3
  assert.equal(f.minimumCalls.value, 18)
  assert.equal(f.draft.value.max_calls_per_turn, 25)
})

test('session switching away from two-phase decisions retains the command budget and clears the opt-in', async t => {
  const saved = state(5)
  Object.assign(saved.settings, { mode: 'live', actor_ids: ['NPC'], workflow: 'integrated', action_tools: true,
    agent_steps: 1, npc_decision_mode: 'two_phase', max_calls_per_turn: 8 })
  let written
  const f = fixture(t, async (_url, options) => {
    if (options.method === 'GET') return Response.json(saved)
    written = JSON.parse(options.body).settings
    return Response.json({ ...saved, revision: 6, settings: written })
  })
  await tick()
  assert.equal(f.minimumCalls.value, 7)
  f.setWorkflow('staged')
  assert.equal(f.draft.value.action_tools, false)
  assert.equal(f.draft.value.npc_decision_mode, undefined)
  f.setActionToolsEnabled(true)
  f.draft.value.npc_decision_mode = 'two_phase'
  f.setMode('shadow')
  assert.equal(f.draft.value.npc_decision_mode, undefined)
  assert.equal(await f.save(), true)
  assert.equal(written.mode, 'shadow')
  assert.equal(written.max_calls_per_turn, 8)
  assert.equal(written.npc_decision_mode, undefined)
})
